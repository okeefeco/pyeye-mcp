"""``generate``, ``check`` and ``changed``: keep the docs' facts equal to the code's.

- ``generate`` rewrites every marker block in the registered docs, every
  generated reference page, the snapshot ``docs/facts/facts.json`` (and each
  family's own snapshot file, #1108), the removed
  names ``docs/facts/removed.json`` (a fact that left the snapshot is appended,
  #826) and the uncovered-fact ledger ``docs/facts/uncovered.json``.
  Pre-commit runs it; a commit whose docs it changes fails, like a formatter.
- ``changed`` prints the changed-fact list against a base revision, the scope
  of a change-triggered ``/docs-review`` (§3). It never fails on a change.
- ``check`` computes the same output in memory and fails if anything on disk
  differs: a stale or hand-edited block, page or snapshot. It also fails on a
  block naming an unknown fact (a removed fact, D4), a malformed marker, or a
  registered file that doesn't exist, on a prose-rule violation beyond a page's
  allow-list (:mod:`.rules`), and on a live page naming a removed name
  (:mod:`.removed`). CI runs it.

All three read only :data:`~.docs.DOCS`; none globs on its own.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import binding, changed, config, docs, examples, ledger, registry, removed, review, rules
from .facts import Bindable, snapshot
from .setup import Paths, Setup, pyeye_setup

SNAPSHOT = "docs/facts/facts.json"
CHANGELOG = "CHANGELOG.md"
#: Kinds whose prose explains facts and must not name removed things.
_LIVE_KINDS = ("prose", "skill")
_DIFF_LINES = 40


@dataclass
class Plan:
    """What ``generate`` would write, and what stops it.

    Attributes:
        outputs: Repo-relative path -> the text it should hold.
        problems: ``path:line: message`` for each marker or registry problem.
        notes: What was left out, not a failure: each rule skipped because its
            facts are absent (#1091).
    """

    outputs: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def snapshot_text(facts: Mapping[str, Bindable]) -> str:
    """The snapshot file: every item fact's value, sorted by ID."""
    return json.dumps({"facts": snapshot(facts)}, indent=2, sort_keys=True) + "\n"


def snapshot_texts(facts: Mapping[str, Bindable], paths: Paths) -> dict[str, str]:
    """Every snapshot file's text: a family with its own file (#1108) is recorded there."""
    split: dict[str, dict[str, Bindable]] = {p: {} for p in paths.snapshot_files()}
    for fact_id, item in facts.items():
        split[paths.snapshot_of(fact_id)][fact_id] = item
    return {path: snapshot_text(items) for path, items in split.items()}


def reference_only_note(setup: Setup) -> list[str]:
    """The note naming the reference-only families, if there are any (#1108)."""
    if not setup.reference_only:
        return []
    names = ", ".join(sorted(setup.reference_only))
    return [f"reference-only fact families, outside the uncovered-fact ledger: {names}"]


def plan(
    root: Path, facts: Mapping[str, Bindable] | None = None, setup: Setup | None = None
) -> Plan:
    """Compute the generated text of every registered doc, page and the snapshot.

    *setup* is the repository's (#1091): its extractors, doc registry, rules and
    pages. Default: pyeye's own (:func:`~.setup.pyeye_setup`).
    """
    setup = pyeye_setup() if setup is None else setup
    if facts is None:
        facts = registry.build(root, setup.extractors)
    result = Plan()
    generated = set(setup.pages)
    for path in docs.missing_files(root, setup.docs):
        if path not in generated:
            result.problems.append(f"{path}: registered in the doc registry but missing")
    entries = removed.load(root, setup.paths.removed)
    live = removed.live_names(facts)
    changelog = root / setup.changelog if setup.changelog else None
    major = removed.current_major(
        changelog.read_text(encoding="utf-8") if changelog and changelog.is_file() else ""
    )
    covered: set[str] = set()
    for path, entry in docs.registered_files(root, setup.docs):
        if path in generated:
            continue
        text = (root / path).read_text(encoding="utf-8")
        new_text, blocks, problems = binding.render(text, facts)
        runnable, example_problems = examples.parse_examples(text)
        problems.extend(example_problems)
        if runnable and not examples.allows_examples(entry):
            problems.append(
                binding.Problem(
                    runnable[0].line,
                    f"runnable examples belong in {examples.WHERE_EXAMPLES_LIVE}",
                )
            )
        result.problems.extend(f"{path}:{p.line}: {p.message}" for p in problems)
        result.outputs[path] = new_text
        if entry.kind not in _LIVE_KINDS:
            continue
        covered |= ledger.expand((b.fact_id for b in blocks), facts)
        unknown = [i for i in entry.covers if i not in facts]
        if unknown:
            result.problems.append(f"{path}: `covers` names unknown fact IDs {unknown}")
        covered |= ledger.expand(entry.covers, facts)
        found = removed.mentions(path, text, entries, live, major)
        result.problems.extend(_removed_name_problems(path, entry, found))
    for path, build_page in setup.pages.items():
        result.outputs[path] = build_page(facts)
    result.outputs.update(snapshot_texts(facts, setup.paths))
    result.problems.extend(rules.run(root, facts, setup.docs, setup.rules))
    result.notes.extend(rules.skipped(setup.rules, facts))
    result.notes.extend(reference_only_note(setup))
    old_snapshot = _committed_snapshots(root, setup.paths)
    result.outputs[setup.paths.removed] = removed.render(
        removed.updated(entries, old_snapshot, facts)
    )
    review_state = review.load(root, setup.paths.review_state)
    result.problems.extend(review.orphaned(review_state, facts, root, review.project_symbols(root)))
    result.outputs[setup.paths.uncovered] = ledger.render(
        ledger.updated(
            ledger.load(root, setup.paths.uncovered),
            facts,
            covered,
            review.dismissed_uncovered(review_state, facts),
            reference_only=setup.reference_only,
        )
    )
    return result


def _committed_snapshot(root: Path, path: str = SNAPSHOT) -> dict[str, object]:
    current = _current(root, path)
    if current is None:
        return {}
    facts: dict[str, object] = json.loads(current)["facts"]
    return facts


def base_snapshots(root: Path, base: str, paths: Paths) -> dict[str, object] | None:
    """Every snapshot file's facts at git revision *base*, or None if it has no main one.

    A family's own file (#1108) that *base* lacks adds nothing: before the split,
    its facts were in the main snapshot.
    """
    before = changed.base_snapshot(root, base, paths.snapshot)
    if before is None:
        return None
    for path in paths.snapshot_files()[1:]:
        before.update(changed.base_snapshot(root, base, path) or {})
    return before


def _committed_snapshots(root: Path, paths: Paths) -> dict[str, object]:
    """Every snapshot file's facts together, so moving a family between files loses none."""
    facts: dict[str, object] = {}
    for path in paths.snapshot_files():
        facts.update(_committed_snapshot(root, path))
    return facts


def _removed_name_problems(
    path: str, entry: docs.DocEntry, found: list[removed.Mention]
) -> list[str]:
    """The removed-name rule for one live page (C8): failures, then its ratchet."""
    problems = [removed.problem(m) for m in found if m.fails]
    allowed = [removed.allowance(m) for m in found if not m.fails]
    over = rules.ratchet(entry, removed.RULE_ID, allowed)
    if over is not None:
        problems.append(f"{path}: {over}")
    return problems


def _current(root: Path, path: str) -> str | None:
    target = root / path
    return target.read_text(encoding="utf-8") if target.is_file() else None


def stale(root: Path, result: Plan) -> list[str]:
    """Paths whose file on disk differs from the planned text."""
    return [p for p, text in sorted(result.outputs.items()) if _current(root, p) != text]


def _diff(root: Path, path: str, text: str) -> str:
    current = _current(root, path)
    if current is None:
        return f"{path}: missing (run generate)"
    lines = list(
        difflib.unified_diff(
            current.splitlines(),
            text.splitlines(),
            f"{path} (on disk)",
            f"{path} (generated)",
            lineterm="",
        )
    )
    if len(lines) > _DIFF_LINES:
        lines = [*lines[:_DIFF_LINES], f"... {len(lines) - _DIFF_LINES} more diff lines"]
    return "\n".join(lines)


def generate(root: Path, setup: Setup | None = None) -> int:
    """Write every stale output. Returns the exit code (1 on a problem)."""
    result = plan(root, setup=setup)
    for path in stale(root, result):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.outputs[path], encoding="utf-8", newline="\n")
        print(f"docs_facts: regenerated {path}")
    for problem in result.problems:
        print(f"docs_facts: {problem}", file=sys.stderr)
    for note in result.notes:
        print(f"docs_facts: {note}", file=sys.stderr)
    return 1 if result.problems else 0


def check(root: Path, setup: Setup | None = None) -> int:
    """Fail if any output is stale or any marker is malformed or unknown."""
    result = plan(root, setup=setup)
    paths = stale(root, result)
    for path in paths:
        print(_diff(root, path, result.outputs[path]))
    for problem in result.problems:
        print(f"docs_facts: {problem}")
    for note in result.notes:  # left out, not failed (#1091)
        print(f"docs_facts: {note}")
    if paths:
        print(
            f"docs_facts: {len(paths)} file(s) differ from the code's facts. Run "
            "`uv run python scripts/docs_facts.py generate` and commit the result; "
            "never edit inside a fact block or a generated page."
        )
    if paths or result.problems:
        return 1
    print(f"docs_facts: {len(result.outputs)} files match the code's facts")
    return 0


def report_changed(root: Path, base: str, setup: Setup | None = None) -> int:
    """Print the changed-fact list against *base* as Markdown. Never fails on a change."""
    setup = pyeye_setup() if setup is None else setup
    snapshot = setup.paths.snapshot
    head = _committed_snapshots(root, setup.paths)
    before = base_snapshots(root, base, setup.paths)
    if before is None:
        print(f"### Docs facts changed against `{base}`\n\n`{base}` has no `{snapshot}`.")
        return 0
    facts = registry.build(root, setup.extractors)
    bound = changed.bound_pages(root, facts, setup.docs)
    print(changed.summary(changed.diff(before, head, bound), base))
    return 0


def _setup_for(root: Path) -> Setup | None:
    """The repository's configured setup (#1091), or ``None`` for pyeye's own.

    A repository with a ``docs_facts`` config is checked by it alone. Without
    one, the default is pyeye's own setup until pyeye's repository declares
    its own (the ``preset`` question with the maintainer), when no config
    becomes an error (``config.load`` already says so).
    """
    return config.load(root) if config.find(root) is not None else None


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """Entry point for ``scripts/docs_facts.py``."""
    parser = argparse.ArgumentParser(
        prog="docs_facts", description="Keep the docs' facts equal to the code's."
    )
    parser.add_argument("command", choices=["generate", "check", "changed"])
    parser.add_argument("--root", type=Path, default=root or Path.cwd(), help="repository root")
    parser.add_argument(
        "--base", default="origin/main", help="changed: the git revision to diff against"
    )
    args = parser.parse_args(argv)
    try:
        setup = _setup_for(args.root)
    except config.ConfigError as error:
        print(f"docs_facts: {error}", file=sys.stderr)
        return 1
    try:
        if args.command == "generate":
            return generate(args.root, setup)
        if args.command == "changed":
            return report_changed(args.root, args.base, setup)
        return check(args.root, setup)
    except ValueError as error:
        # An extractor whose source changed shape, or two sources of one fact
        # that disagree (e.g. the coverage threshold in pyproject and ci.yml).
        print(f"docs_facts: cannot extract the facts: {error}", file=sys.stderr)
        return 1
