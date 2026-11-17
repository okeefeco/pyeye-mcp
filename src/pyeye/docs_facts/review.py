"""The deterministic substrate of the internal ``/docs-review`` skill (#829).

The skill (``.claude/skills/docs-review/``) dispatches a fresh-context reviewer
over a scope of registered pages and drives the human loop. This module is the
authority for every mechanical step, as :mod:`pyeye.architecture_review` is for
``/architecture-review``:

- the finding shape and :func:`finding_problems`, which enforces the review
  principle (D8, C13, C14): every finding names its anchor and gives a way
  forward, and nothing is decided for the human;
- a finding's identity (:func:`finding_key`), from fields, never from prose (#498);
- sections (:func:`sections`) and their review freshness: "this section is
  fine" is remembered until the section's text or its facts change;
- dismissals, stored with :mod:`pyeye.architecture_review.state` (D7) in
  ``docs/facts/review-state.json``: a reviewed finding, or an uncovered fact
  that is deliberately not covered (C13). A dismissal lapses when its anchor
  fact's value changes, and an orphaned one (its fact is gone) is a problem for
  ``check`` to fail on (C14).

Pure apart from :func:`load` / :func:`save`. No clock: dates are caller-supplied.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..architecture_review import state as review_state
from .facts import Bindable, Fact, View

#: The committed review state: section coverage and dismissals (C13).
STATE_PATH = "docs/facts/review-state.json"

#: What a finding is about. Closed: an unknown category is rejected.
CATEGORIES = ("fact_drift", "uncovered_fact", "honest_claims", "audience", "style")

#: What a finding rests on (§6). ``fact`` is a fact ID; ``claims_rule`` a D12
#: clause; ``audience_rule`` an audience rule (D11, ``00-documentation-system.md``);
#: ``style_rule`` a checklist entry; ``task`` a failed scoring task (#830).
ANCHOR_KINDS = ("fact", "claims_rule", "audience_rule", "style_rule", "task")

#: The label a needs-decision finding's assessment carries when no anchor backs
#: a recommendation (C13): an informed judgment, never presented as settled.
UNANCHORED = "unanchored: judgment only"

#: How many options a needs-decision finding offers.
MIN_OPTIONS, MAX_OPTIONS = 2, 3

#: Dismissal reasons. ``fine`` records a reviewed finding as not a problem;
#: ``not-covered`` an uncovered fact that is deliberately left uncovered (C13).
DISMISSAL_REASONS = ("fine", "deliberate", "not-covered", "other")

#: The structural-fact prefix of every docs-review dismissal, so they never
#: collide with ``/architecture-review`` or ``/duplication-review`` entries.
_FACT_PREFIX = "docs-review:"

Facts = Mapping[str, Bindable]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _anchor_problems(anchor: Any, where: str) -> list[str]:
    if not isinstance(anchor, dict):
        return [f"{where} must be an object {{kind, id}}"]
    problems = []
    if anchor.get("kind") not in ANCHOR_KINDS:
        problems.append(f"{where}.kind must be one of {list(ANCHOR_KINDS)}")
    if not _text(anchor.get("id")):
        problems.append(f"{where}.id must be a non-empty string")
    return problems


def _option_problems(options: Any) -> list[str]:
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        return [f"options must be a list of {MIN_OPTIONS} to {MAX_OPTIONS} options"]
    problems = []
    for i, option in enumerate(options):
        if not (
            isinstance(option, dict) and _text(option.get("text")) and _text(option.get("cost"))
        ):
            problems.append(f"options[{i}] must have a non-empty text and cost")
    return problems


def finding_problems(finding: Mapping[str, Any], facts: Facts | None = None) -> list[str]:
    """Why *finding* can't be shown to a human; ``[]`` when it can.

    The shape (D8, C13, C14):

    - ``page``, ``section``, ``problem``: non-empty strings.
    - ``category``: one of :data:`CATEGORIES`.
    - ``anchor``: ``{kind, id}``, what the finding rests on (:data:`ANCHOR_KINDS`).
      A ``fact`` anchor must name a fact in *facts*, when given.
    - **A clear fix:** ``replacement``, the proposed text, and no options.
    - **Genuine ambiguity:** ``needs_decision: true``, a ``question``, 2 or 3
      ``options`` each with its ``text`` and ``cost``, and either a
      ``recommended`` option index with its ``recommendation_anchor``, or, when
      no anchor backs one, an ``assessment`` starting with :data:`UNANCHORED`.

    The tool never decides: a finding without a way forward is rejected, and so
    is a needs-decision finding presented as settled (a replacement).
    """
    problems = [
        f"{name} must be a non-empty string"
        for name in ("page", "section", "problem")
        if not _text(finding.get(name))
    ]
    if finding.get("category") not in CATEGORIES:
        problems.append(f"category must be one of {list(CATEGORIES)}")
    anchor = finding.get("anchor")
    problems.extend(_anchor_problems(anchor, "anchor"))
    if (
        facts is not None
        and isinstance(anchor, dict)
        and anchor.get("kind") == "fact"
        and anchor.get("id") not in facts
    ):
        problems.append(f"anchor names fact {anchor.get('id')!r}, which doesn't exist")

    if finding.get("needs_decision") is True:
        if "replacement" in finding:
            problems.append("a needs-decision finding offers options, not a replacement")
        if not _text(finding.get("question")):
            problems.append("a needs-decision finding must state its question")
        options = finding.get("options")
        problems.extend(_option_problems(options))
        recommended = finding.get("recommended")
        if recommended is not None:
            count = len(options) if isinstance(options, list) else 0
            index = isinstance(recommended, int) and not isinstance(recommended, bool)
            if not (index and 0 <= recommended < count):
                problems.append("recommended must be the index of one of the options")
            problems.extend(
                _anchor_problems(finding.get("recommendation_anchor"), "recommendation_anchor")
            )
        else:
            assessment = finding.get("assessment")
            if not (_text(assessment) and str(assessment).startswith(UNANCHORED)):
                problems.append(
                    f"with no recommended option, an assessment starting {UNANCHORED!r} "
                    "is required"
                )
    else:
        if "needs_decision" in finding and finding["needs_decision"] is not False:
            problems.append("needs_decision must be true or false")
        if not _text(finding.get("replacement")):
            problems.append("a finding with a clear fix must propose its replacement text")
        if "options" in finding:
            problems.append("options belong only to a needs-decision finding")
    return problems


def finding_key(finding: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """A finding's identity: page, section, category and anchor; never its prose (#498)."""
    anchor = finding["anchor"]
    return (
        finding["page"],
        finding["section"],
        finding["category"],
        anchor["kind"],
        anchor["id"],
    )


# ---------------------------------------------------------------------------
# Sections and their freshness
# ---------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_FENCE = re.compile(r"^[ \t]*(```|~~~)", re.MULTILINE)


def slug(heading: str) -> str:
    """Return the anchor GitHub gives *heading*: lowercase, punctuation dropped, spaces to ``-``."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    marks = [m.start() for m in _FENCE.finditer(text)]
    return list(zip(marks[0::2], marks[1::2], strict=False))


@dataclass(frozen=True)
class Section:
    """One section of a page: the text from its heading to the next heading.

    Attributes:
        slug: The heading's anchor; ``""`` for the text before the first heading.
        text: The section's text, its heading line included.
        line: The 1-based line it starts on.
    """

    slug: str
    text: str
    line: int = 1


def sections(text: str) -> list[Section]:
    """Split a Markdown page at its headings; a ``#`` inside a code fence is not one.

    Repeated headings get GitHub's ``-1``, ``-2`` suffixes, so every slug is unique.
    """
    fences = _fenced_spans(text)
    starts = [
        m
        for m in _HEADING.finditer(text)
        if not any(start < m.start() < end for start, end in fences)
    ]
    found: list[Section] = []
    seen: dict[str, int] = {}
    if not starts or starts[0].start() > 0:
        head = text[: starts[0].start()] if starts else text
        if head.strip():
            found.append(Section("", head))
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        base = slug(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.append(
            Section(
                base if count == 0 else f"{base}-{count}",
                text[match.start() : end],
                text.count("\n", 0, match.start()) + 1,
            )
        )
    return found


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fact_value(fact_id: str, facts: Facts) -> Any:
    """The value a dismissal or a section hash pins: a fact's value, or a view's members' values."""
    item = facts.get(fact_id)
    if isinstance(item, Fact):
        return item.value
    if isinstance(item, View):
        return {m: fact_value(m, facts) for m in item.members}
    return None


def section_hash(section: Section, fact_ids: Iterable[str], facts: Facts) -> str:
    """The content a "this section is fine" verdict covers: its text and its facts' values."""
    values = {fact_id: fact_value(fact_id, facts) for fact_id in sorted(set(fact_ids))}
    return _digest({"text": " ".join(section.text.split()), "facts": values})


def coverage_key(page: str, section_slug: str) -> str:
    """The state's coverage key for a section: ``page#slug``."""
    return f"{page}#{section_slug}"


def needs_review(
    state: Mapping[str, Any], page: str, section: Section, fact_ids: Iterable[str], facts: Facts
) -> bool:
    """Whether *section* must be reviewed: never reviewed, or changed since (text or facts)."""
    entry = state.get("coverage", {}).get(coverage_key(page, section.slug))
    if entry is None:
        return True
    return review_state.is_stale(entry, section_hash(section, fact_ids, facts))


def mark_reviewed(
    state: dict[str, Any],
    page: str,
    section: Section,
    fact_ids: Iterable[str],
    facts: Facts,
    reviewed_on: str,
) -> None:
    """Record *section* as reviewed and fine on the caller-supplied date."""
    state.setdefault("coverage", {})[coverage_key(page, section.slug)] = {
        "last_audited_at": reviewed_on,
        "content_hash": section_hash(section, fact_ids, facts),
    }


# ---------------------------------------------------------------------------
# Dismissals
# ---------------------------------------------------------------------------


def _structural_fact(kind: str, anchor_id: str, facts: Facts, category: str) -> str:
    """The dismissed observation, pinned to the anchor fact's current value."""
    pinned = _digest(fact_value(anchor_id, facts))[:16] if kind == "fact" else "-"
    return f"{_FACT_PREFIX}{category}:{kind}:{anchor_id}:{pinned}"


def _check_date(value: str, what: str) -> None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise ValueError(f"{what} must be an ISO date YYYY-MM-DD, got {value!r}")


def _entry(
    handles: list[str], fact: str, reason: str, dismissed_on: str, review_after: str | None
) -> dict[str, Any]:
    if reason not in DISMISSAL_REASONS:
        raise ValueError(f"reason must be one of {list(DISMISSAL_REASONS)}, got {reason!r}")
    _check_date(dismissed_on, "date")
    entry: dict[str, Any] = {
        "handles": handles,
        "structural_fact": fact,
        "key": review_state.non_issue_key(handles, fact),
        "reason": reason,
        "date": dismissed_on,
    }
    if review_after is not None:
        _check_date(review_after, "review_after")
        entry["review_after"] = review_after
    return entry


def dismiss_finding(
    state: dict[str, Any],
    finding: Mapping[str, Any],
    facts: Facts,
    reason: str,
    dismissed_on: str,
    review_after: str | None = None,
) -> dict[str, Any]:
    """Record a reviewed *finding* as dismissed; the human's call, never the tool's.

    Keyed on the finding's page and section plus its category and anchor, pinned
    to the anchor fact's value: a reworded finding stays dismissed, and a change
    to the fact brings it back.
    """
    anchor = finding["anchor"]
    handles = [coverage_key(finding["page"], finding["section"])]
    fact = _structural_fact(anchor["kind"], anchor["id"], facts, finding["category"])
    entry = _entry(handles, fact, reason, dismissed_on, review_after)
    entry["anchor"] = {"kind": anchor["kind"], "id": anchor["id"]}
    _replace(state, entry)
    return entry


def dismiss_uncovered(
    state: dict[str, Any], fact_id: str, facts: Facts, reason_text: str, dismissed_on: str
) -> dict[str, Any]:
    """Record *fact_id* as deliberately not covered (C13), with the human's reason.

    ``docs_facts generate`` leaves it out of the ledger's uncovered entries and
    shows it in the ledger's read-only ``dismissed`` section. It lapses when the
    fact's value changes.

    Raises:
        ValueError: If the fact doesn't exist or the reason is empty.
    """
    if fact_id not in facts:
        raise ValueError(f"no fact {fact_id!r} to dismiss")
    if not _text(reason_text):
        raise ValueError("a not-covered dismissal needs its reason")
    fact = _structural_fact("fact", fact_id, facts, "uncovered_fact")
    entry = _entry([fact_id], fact, "not-covered", dismissed_on, None)
    entry["anchor"] = {"kind": "fact", "id": fact_id}
    entry["note"] = reason_text.strip()
    _replace(state, entry)
    return entry


def _ours(entry: Mapping[str, Any]) -> bool:
    return str(entry.get("structural_fact", "")).startswith(_FACT_PREFIX)


def _same_observation(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """Same handles and observation, whatever the pinned value."""
    return (
        a.get("handles") == b.get("handles")
        and str(a["structural_fact"]).rsplit(":", 1)[0]
        == str(b["structural_fact"]).rsplit(":", 1)[0]
    )


def _replace(state: dict[str, Any], entry: dict[str, Any]) -> None:
    entries = state.setdefault("confirmed_non_issues", [])
    entries[:] = [e for e in entries if not (_ours(e) and _same_observation(e, entry))]
    entries.append(entry)


def dismissed_uncovered(state: Mapping[str, Any], facts: Facts) -> dict[str, dict[str, str]]:
    """The facts deliberately not covered whose dismissal still holds: ``{id: {reason, date}}``."""
    held: dict[str, dict[str, str]] = {}
    for entry in state.get("confirmed_non_issues", []):
        if not (_ours(entry) and entry.get("reason") == "not-covered"):
            continue
        fact_id = entry["anchor"]["id"]
        current = _structural_fact("fact", fact_id, facts, "uncovered_fact")
        if fact_id in facts and current == entry["structural_fact"]:
            held[fact_id] = {"reason": entry.get("note", ""), "date": entry["date"]}
    return dict(sorted(held.items()))


def orphaned(state: Mapping[str, Any], facts: Facts) -> list[str]:
    """Dismissals whose anchor fact no longer exists (C14); ``check`` fails on each.

    The PR that removes or renames a fact removes its dismissals, or moves them
    to the new ID on purpose.
    """
    problems = []
    for entry in state.get("confirmed_non_issues", []):
        anchor = entry.get("anchor") or {}
        if _ours(entry) and anchor.get("kind") == "fact" and anchor.get("id") not in facts:
            problems.append(
                f"{STATE_PATH}: dismissal {entry.get('key')} names fact {anchor.get('id')!r}, "
                "which no longer exists; remove it, or move it to the fact's new ID"
            )
    return problems


#: A finding's status after the state is applied (as ``/duplication-review``'s).
STATUSES = ("new", "resurfaced", "review-due")


def triage(
    findings: Iterable[Mapping[str, Any]],
    state: Mapping[str, Any],
    facts: Facts,
    today: str | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """The findings to show, each with its status; dismissed ones are left out.

    - ``new``: no dismissal matches it.
    - ``resurfaced``: it was dismissed, but its anchor fact's value has changed.
    - ``review-due``: its dismissal's ``review_after`` has been reached (*today*,
      caller-supplied; with no *today*, nothing comes due).
    """
    entries = [e for e in state.get("confirmed_non_issues", []) if _ours(e)]
    shown: list[tuple[dict[str, Any], str]] = []
    for finding in findings:
        anchor = finding["anchor"]
        handles = [coverage_key(finding["page"], finding["section"])]
        fact = _structural_fact(anchor["kind"], anchor["id"], facts, finding["category"])
        probe = {"handles": handles, "structural_fact": fact}
        exact = [e for e in entries if e["handles"] == handles and e["structural_fact"] == fact]
        if exact:
            due = exact[0].get("review_after")
            if today is not None and due is not None and today >= due:
                shown.append((dict(finding), "review-due"))
            continue
        status = "resurfaced" if any(_same_observation(e, probe) for e in entries) else "new"
        shown.append((dict(finding), status))
    return shown


# ---------------------------------------------------------------------------
# Scope: which pages a review covers, and what the reviewer is given
# ---------------------------------------------------------------------------


def _page_fact_ids(text: str, entry: Any, facts: Facts) -> set[str]:
    """The item facts a page shows in its blocks or declares in ``covers``."""
    from . import binding, ledger

    blocks, _ = binding.parse(text)
    return ledger.expand([b.fact_id for b in blocks], facts) | ledger.expand(entry.covers, facts)


def _section_fact_ids(section: Section, entry: Any, facts: Facts) -> list[str]:
    from . import binding, ledger

    blocks, _ = binding.parse(section.text)
    ids = ledger.expand([b.fact_id for b in blocks], facts) | ledger.expand(entry.covers, facts)
    return sorted(ids)


def packet(
    root: Path,
    path: str,
    entry: Any,
    facts: Facts,
    state: Mapping[str, Any],
    changed_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """What the reviewer gets for one page: its audience, facts and sections.

    No page text: the reviewer reads the page itself (targeted reads). Each
    section says whether it needs review (never reviewed, or its text or facts
    changed since it was marked fine) and which facts it shows or covers.
    """
    text = (root / path).read_text(encoding="utf-8")
    fact_ids = sorted(_page_fact_ids(text, entry, facts))
    changed_here = sorted(set(changed_ids) & set(fact_ids))
    found = []
    for section in sections(text):
        ids = _section_fact_ids(section, entry, facts)
        found.append(
            {
                "section": section.slug,
                "line": section.line,
                "needs_review": needs_review(state, path, section, ids, facts),
                "facts": ids,
            }
        )
    return {
        "page": path,
        "audience": entry.audience,
        "kind": entry.kind,
        "facts": {i: facts[i].markdown for i in fact_ids},
        "changed": changed_here,
        "sections": found,
    }


def _reviewable(path: str, entry: Any) -> bool:
    """Hand-written pages only: generated reference pages hold no prose to review."""
    return bool(entry.kind != "reference" and path.endswith(".md"))


def scope(
    root: Path,
    facts: Facts,
    *,
    pages: Iterable[str] = (),
    audience: str | None = None,
    base: str | None = None,
) -> dict[str, Any]:
    """The review scope as reviewer packets (D6).

    - **On demand:** *pages* (registered paths or globs) and/or an *audience*.
    - **Change-triggered:** *base*, a git revision. The scope is every page that
      binds or covers a fact added or changed since *base*, plus the ledger's
      ``new`` uncovered facts, to cover or dismiss.

    Raises:
        ValueError: If nothing selects pages, or a named page isn't registered.
    """
    from fnmatch import fnmatchcase

    from . import (
        changed as changed_facts,
        docs,
        ledger,
    )
    from .cli import SNAPSHOT, _committed_snapshot

    wanted = list(pages)
    if not (wanted or audience or base):
        raise ValueError("give pages, an audience or a base revision: there is no default scope")
    registered = dict(docs.registered_files(root))
    for pattern in wanted:
        if not any(fnmatchcase(path, pattern) for path in registered):
            raise ValueError(f"{pattern!r} matches no registered page")
    changed_ids: set[str] = set()
    uncovered: list[str] = []
    if base is not None:
        before = changed_facts.base_snapshot(root, base, SNAPSHOT)
        diff = changed_facts.diff(before or {}, _committed_snapshot(root), {})
        changed_ids = set(diff.added) | set(diff.changed)
        current = ledger.load(root)
        uncovered = sorted(current.new) if current is not None else []
    state = load(root)
    selected = []
    for path, entry in registered.items():
        if not _reviewable(path, entry):
            continue
        picked = any(fnmatchcase(path, p) for p in wanted) or (
            audience is not None and entry.audience == audience
        )
        if base is not None and not picked:
            text = (root / path).read_text(encoding="utf-8")
            picked = bool(_page_fact_ids(text, entry, facts) & changed_ids)
        if picked:
            selected.append(packet(root, path, entry, facts, state, changed_ids))
    return {
        "base": base,
        "changed": sorted(changed_ids),
        "uncovered": [{"fact": i, "markdown": facts[i].markdown} for i in uncovered if i in facts],
        "pages": selected,
    }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load(root: Path) -> dict[str, Any]:
    """The committed review state, or an empty one."""
    return review_state.load_state(root / STATE_PATH)


def save(root: Path, state: dict[str, Any]) -> None:
    """Write the review state, sorted and stable, with a trailing newline."""
    path = root / STATE_PATH
    review_state.save_state(path, state)
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        path.write_text(text + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Command line: ``scripts/docs_review.py``
# ---------------------------------------------------------------------------


def _read_findings(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(f, dict) for f in data):
        raise ValueError(f"{path.as_posix()}: expected a JSON array of finding objects")
    return data


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    """Entry point for ``scripts/docs_review.py``; prints JSON for the skill to read."""
    import argparse
    import sys

    from .registry import build

    parser = argparse.ArgumentParser(prog="docs_review", description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=root or Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    p_scope = sub.add_parser("scope", help="reviewer packets for a scope")
    p_scope.add_argument("pages", nargs="*", help="registered paths or globs")
    p_scope.add_argument("--audience", choices=["human", "claude", "both"])
    p_scope.add_argument("--base", help="git revision: pages bound to facts changed since it")
    p_check = sub.add_parser("validate", help="check findings and give each one's status")
    p_check.add_argument("findings", type=Path)
    p_check.add_argument("--today", help="ISO date; a review-after dismissal comes due")
    p_fine = sub.add_parser("mark-fine", help="record a section as reviewed and fine")
    p_fine.add_argument("page")
    p_fine.add_argument(
        "section", help="the section's slug ('' for the text before the first heading)"
    )
    p_fine.add_argument("--date", required=True)
    p_dismiss = sub.add_parser("dismiss", help="record a finding as dismissed (the human's call)")
    p_dismiss.add_argument("findings", type=Path)
    p_dismiss.add_argument("--index", type=int, required=True)
    p_dismiss.add_argument("--reason", required=True, choices=list(DISMISSAL_REASONS))
    p_dismiss.add_argument("--date", required=True)
    p_dismiss.add_argument("--review-after")
    p_unc = sub.add_parser("dismiss-uncovered", help="record a fact as deliberately not covered")
    p_unc.add_argument("fact")
    p_unc.add_argument("--reason", required=True, help="why it is deliberately not covered")
    p_unc.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    base: Path = args.root
    try:
        facts = build(base)
        if args.command == "scope":
            out: Any = scope(base, facts, pages=args.pages, audience=args.audience, base=args.base)
        elif args.command == "validate":
            findings = _read_findings(args.findings)
            problems = {
                str(i): found
                for i, f in enumerate(findings)
                if (found := finding_problems(f, facts))
            }
            if problems:
                print(json.dumps({"problems": problems}, indent=2))
                return 1
            shown = triage(findings, load(base), facts, args.today)
            out = {"shown": [{"index": findings.index(f), "status": s} for f, s in shown]}
        elif args.command == "mark-fine":
            from . import docs

            entry = docs.entry_for(args.page)
            if entry is None:
                raise ValueError(f"{args.page!r} isn't registered")
            text = (base / args.page).read_text(encoding="utf-8")
            match = [s for s in sections(text) if s.slug == args.section]
            if not match:
                raise ValueError(f"{args.page} has no section {args.section!r}")
            _check_date(args.date, "--date")
            state = load(base)
            ids = _section_fact_ids(match[0], entry, facts)
            mark_reviewed(state, args.page, match[0], ids, facts, args.date)
            save(base, state)
            out = {"marked": coverage_key(args.page, args.section)}
        elif args.command == "dismiss":
            findings = _read_findings(args.findings)
            finding = findings[args.index]
            found = finding_problems(finding, facts)
            if found:
                raise ValueError(f"finding {args.index} is invalid: {found}")
            state = load(base)
            out = dismiss_finding(state, finding, facts, args.reason, args.date, args.review_after)
            save(base, state)
        else:
            state = load(base)
            out = dismiss_uncovered(state, args.fact, facts, args.reason, args.date)
            save(base, state)
            out["next"] = "run `uv run python scripts/docs_facts.py generate` to update the ledger"
    except (ValueError, IndexError, OSError) as exc:
        print(f"docs_review: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0
