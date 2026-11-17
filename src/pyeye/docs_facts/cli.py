"""``generate``, ``check`` and ``changed``: keep the docs' facts equal to the code's.

- ``generate`` rewrites every marker block in the registered docs, every
  generated reference page, the snapshot ``docs/facts/facts.json``, the removed
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

from . import binding, changed, docs, ledger, pages, registry, removed, review, rules
from .facts import Bindable, snapshot

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
    """

    outputs: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def snapshot_text(facts: Mapping[str, Bindable]) -> str:
    """The snapshot file: every item fact's value, sorted by ID."""
    return json.dumps({"facts": snapshot(facts)}, indent=2, sort_keys=True) + "\n"


def plan(root: Path, facts: Mapping[str, Bindable] | None = None) -> Plan:
    """Compute the generated text of every registered doc, page and the snapshot."""
    if facts is None:
        facts = registry.build(root)
    result = Plan()
    generated = set(docs.REFERENCE_PAGES)
    for path in docs.missing_files(root):
        if path not in generated:
            result.problems.append(f"{path}: registered in the doc registry but missing")
    entries = removed.load(root)
    live = removed.live_names(facts)
    changelog = root / CHANGELOG
    major = removed.current_major(
        changelog.read_text(encoding="utf-8") if changelog.is_file() else ""
    )
    covered: set[str] = set()
    for path, entry in docs.registered_files(root):
        if path in generated:
            continue
        text = (root / path).read_text(encoding="utf-8")
        new_text, blocks, problems = binding.render(text, facts)
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
    for path, build_page in pages.PAGES.items():
        result.outputs[path] = build_page(facts)
    result.outputs[SNAPSHOT] = snapshot_text(facts)
    result.problems.extend(rules.run(root, facts))
    old_snapshot = _committed_snapshot(root)
    result.outputs[removed.REMOVED] = removed.render(removed.updated(entries, old_snapshot, facts))
    review_state = review.load(root)
    result.problems.extend(review.orphaned(review_state, facts))
    result.outputs[ledger.UNCOVERED] = ledger.render(
        ledger.updated(
            ledger.load(root), facts, covered, review.dismissed_uncovered(review_state, facts)
        )
    )
    return result


def _committed_snapshot(root: Path) -> dict[str, object]:
    current = _current(root, SNAPSHOT)
    if current is None:
        return {}
    facts: dict[str, object] = json.loads(current)["facts"]
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


def generate(root: Path) -> int:
    """Write every stale output. Returns the exit code (1 on a problem)."""
    result = plan(root)
    for path in stale(root, result):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.outputs[path], encoding="utf-8", newline="\n")
        print(f"docs_facts: regenerated {path}")
    for problem in result.problems:
        print(f"docs_facts: {problem}", file=sys.stderr)
    return 1 if result.problems else 0


def check(root: Path) -> int:
    """Fail if any output is stale or any marker is malformed or unknown."""
    result = plan(root)
    paths = stale(root, result)
    for path in paths:
        print(_diff(root, path, result.outputs[path]))
    for problem in result.problems:
        print(f"docs_facts: {problem}")
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


def report_changed(root: Path, base: str) -> int:
    """Print the changed-fact list against *base* as Markdown. Never fails on a change."""
    head = _committed_snapshot(root)
    before = changed.base_snapshot(root, base, SNAPSHOT)
    if before is None:
        print(f"### Docs facts changed against `{base}`\n\n`{base}` has no `{SNAPSHOT}`.")
        return 0
    facts = registry.build(root)
    print(changed.summary(changed.diff(before, head, changed.bound_pages(root, facts)), base))
    return 0


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
        if args.command == "generate":
            return generate(args.root)
        if args.command == "changed":
            return report_changed(args.root, args.base)
        return check(args.root)
    except ValueError as error:
        # An extractor whose source changed shape, or two sources of one fact
        # that disagree (e.g. the coverage threshold in pyproject and ci.yml).
        print(f"docs_facts: cannot extract the facts: {error}", file=sys.stderr)
        return 1
