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
from typing import Any, Protocol

from ..architecture_review import state as review_state
from .facts import Bindable, Fact, View

#: The committed review state: section coverage and dismissals (C13).
STATE_PATH = "docs/facts/review-state.json"

#: What a finding is about. Closed: an unknown category is rejected.
CATEGORIES = (
    "fact_drift",
    "uncovered_fact",
    "code_contradiction",
    "honest_claims",
    "audience",
    "style",
)

#: What a finding rests on (§6), and the closed set of IDs for each rule kind.
#: ``fact`` is any extracted fact ID; ``task`` (a failed scoring task) arrives
#: with #830 and has no IDs yet. An ID outside its set is rejected, so a
#: reviewer can't invent an anchor.
RULE_IDS: dict[str, dict[str, str]] = {
    "claims_rule": {
        "D12-absolute": "an absolute claim without the scope the code guarantees",
        "D12-comparison": "an implied comparison with no record behind it",
        "D12-projection": "a projection or target stated as fact",
    },
    "audience_rule": {
        "human-explains": "human docs explain, with no enforcement language",
        "claude-directs": "Claude docs are concise and directive, with no tutorials",
        "bridge-problem-fix": "bridge docs give the problem and an executable fix",
        "right-audience": "content belongs to another audience's docs",
        "link-not-restate": "reference material is linked, not restated",
    },
    "style_rule": {
        "invalid-example": "a copyable example that doesn't work as written",
        "broken-link": "a link to a missing file or section",
        "orphaned-text": "text under the wrong heading, or about something absent",
        "missing-prerequisite": "a step that assumes setup the page never gives",
        "imprecise-limit": "a configurable default stated as a fixed limit",
        "dated-claim": "an external fact that may be stale and needs checking",
        "duplication": "content repeated from another page",
        "restated-example": "prose describing an executed example's output, not what it demonstrates",
    },
    "task": {},
}
#: ``symbol`` is a code symbol by its canonical pyeye handle (``pkg.mod.func``),
#: never ``path:line``, so it is stable under unrelated edits; ``validate`` checks
#: it resolves, in the project, to exactly that handle.
ANCHOR_KINDS = ("fact", "symbol", *RULE_IDS)

#: The anchor kinds whose findings name their ``subject``: the exact text of the
#: page they are about. It is part of a dismissal's identity (C15), so dismissing
#: one broken link doesn't hide a different one added to the section later.
SUBJECT_KINDS = ("claims_rule", "audience_rule", "style_rule")


class Symbols(Protocol):
    """What /docs-review asks pyeye about a code symbol (C15).

    :func:`project_symbols` answers with pyeye's own resolver, ``inspect`` and
    ``expand``; tests pass a fake.
    """

    def canonical(self, handle: str) -> str | None:
        """The canonical project handle *handle* resolves to, or ``None``."""

    def surface(self, handle: str) -> dict[str, str] | None:
        """``{signature, docstring}`` as pyeye ``inspect`` reports them, or ``None``."""

    def edge(self, handle: str, edge: str) -> list[str] | None:
        """The handles ``expand(handle, edge)`` lists, or ``None`` if it can't."""


#: The anchor kind each category rests on.
CATEGORY_ANCHOR = {
    "fact_drift": "fact",
    "uncovered_fact": "fact",
    "code_contradiction": "symbol",
    "honest_claims": "claims_rule",
    "audience": "audience_rule",
    "style": "style_rule",
}

#: The fields only a needs-decision finding may carry.
_DECISION_FIELDS = ("options", "question", "assessment", "recommended", "recommendation_anchor")

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


def _anchor_problems(
    anchor: Any, where: str, facts: Facts | None, symbols: Symbols | None = None
) -> list[str]:
    if not isinstance(anchor, dict):
        return [f"{where} must be an object {{kind, id}}"]
    kind, anchor_id = anchor.get("kind"), anchor.get("id")
    if kind not in ANCHOR_KINDS:
        return [f"{where}.kind must be one of {list(ANCHOR_KINDS)}"]
    if not _text(anchor_id):
        return [f"{where}.id must be a non-empty string"]
    if kind == "fact":
        if facts is not None and anchor_id not in facts:
            return [f"{where} names fact {anchor_id!r}, which doesn't exist"]
        return []
    if kind == "symbol":
        if symbols is None:
            return []
        canonical = symbols.canonical(str(anchor_id))
        if canonical is None:
            return [f"{where} names symbol {anchor_id!r}, which doesn't resolve in the project"]
        if canonical != anchor_id:
            return [f"{where} must use the canonical handle {canonical!r}, not {anchor_id!r}"]
        return []
    known = RULE_IDS[kind]
    if anchor_id not in known:
        listed = sorted(known) or "none yet (#830)"
        return [f"{where}.id {anchor_id!r} isn't a {kind}; known: {listed}"]
    return []


def _flat(text: str) -> str:
    return " ".join(text.split())


def section_text(root: Path, page: str, section_slug: str) -> str | None:
    """The text of *page*'s section *section_slug*, or ``None`` if either is gone."""
    path = root / page
    if not path.is_file():
        return None
    for found in sections(path.read_text(encoding="utf-8")):
        if found.slug == section_slug:
            return found.text
    return None


def _location_problems(finding: Mapping[str, Any], root: Path) -> list[str]:
    """Check that the page, section and subject exist.

    The page must be registered and on disk, the section one of its slugs, and a
    ``subject`` must occur in that section verbatim, whitespace aside (C15).
    """
    from . import docs

    page, section = finding.get("page"), finding.get("section")
    if not isinstance(page, str) or docs.entry_for(page) is None:
        return [f"page {page!r} isn't a registered doc"]
    path = root / page
    if not path.is_file():
        return [f"page {page!r} doesn't exist"]
    slugs = [s.slug for s in sections(path.read_text(encoding="utf-8"))]
    if section not in slugs:
        return [f"{page} has no section {section!r}; its sections: {slugs}"]
    subject = finding.get("subject")
    if _text(subject):
        count = _flat(section_text(root, page, str(section)) or "").count(_flat(str(subject)))
        if count == 0:
            return [f"subject {subject!r} doesn't occur verbatim in {page}#{section}"]
        if count > 1:
            return [
                f"subject {subject!r} occurs {count} times in {page}#{section}: quote enough "
                "text to be unique, so the dismissal lapses when that instance is fixed"
            ]
    return []


#: How a code_contradiction is fixed, in preference order (C15 as revised): prose
#: must not state code facts, so the claim becomes a bound fact (from an
#: extractor) or an executed example, and only when neither can work, wording.
ROUTES = ("fact", "example", "wording")


def _example_problems(finding: Mapping[str, Any], root: Path | None) -> list[str]:
    """An example route points at a runnable example, or proposes one (#828)."""
    from .examples import parse_examples

    at = finding.get("example_at")
    if at is not None:
        if not (isinstance(at, dict) and _text(at.get("page")) and isinstance(at.get("line"), int)):
            return ["example_at must be {page, line}: the opener line of a runnable example"]
        if root is not None:
            path = root / str(at["page"])
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            found, _ = parse_examples(text)
            if not any(e.line == at["line"] for e in found):
                return [f"no runnable example opens at {at['page']}:{at['line']}"]
        return []
    found, problems = parse_examples(str(finding.get("replacement", "")))
    if not found or problems:
        return [
            "an example route points at a runnable example (example_at) or its replacement "
            "is one: a fenced `json pyeye-example tool=<tool>` block"
        ]
    return []


def _route_problems(finding: Mapping[str, Any], root: Path | None = None) -> list[str]:
    """The route a code_contradiction takes, and why when it falls back to wording."""
    route = finding.get("route")
    if route not in ROUTES:
        return [
            f"a code_contradiction must say its route, one of {list(ROUTES)}: a fact or an "
            "executed example first, wording only when neither can work"
        ]
    if route == "fact":
        from .registry import EXTRACTORS

        extractor = finding.get("extractor")
        names = sorted(e.name for e in EXTRACTORS)
        new = isinstance(extractor, str) and re.match(r"new: \S", extractor) is not None
        if extractor not in names and not new:
            return [f"a fact route names its extractor: one of {names}, or 'new: <what it reads>'"]
    if route == "example":
        return _example_problems(finding, root)
    if route == "wording" and not _text(finding.get("route_reason")):
        return ["a wording route must say why neither a fact nor an executed example can work"]
    return []


_EVIDENCE_KEYS = ({"signature"}, {"docstring"}, {"edge", "includes"})

#: The fewest words a docstring excerpt may have: a short one ("the") matches
#: almost any docstring, so it proves nothing about what the code does.
MIN_EXCERPT_WORDS = 4


def _word_bounded_in(excerpt: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(_flat(excerpt))}(?!\w)", _flat(text)) is not None


def _evidence_problems(finding: Mapping[str, Any], symbols: Symbols | None) -> list[str]:
    """A code_contradiction carries what the code does, checked against pyeye (C15)."""
    evidence = finding.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return [
            "a code_contradiction must carry evidence: what pyeye reports the code does "
            "(a signature, a docstring excerpt, or an edge's handles)"
        ]
    handle = str((finding.get("anchor") or {}).get("id"))
    problems = []
    surface = symbols.surface(handle) if symbols is not None else None
    for i, item in enumerate(evidence):
        if not (isinstance(item, dict) and set(item) in _EVIDENCE_KEYS):
            problems.append(
                f"evidence[{i}] must be one of {{signature}}, {{docstring}} or {{edge, includes}}"
            )
            continue
        if "docstring" in item and (
            not isinstance(item["docstring"], str)
            or len(item["docstring"].split()) < MIN_EXCERPT_WORDS
        ):
            problems.append(
                f"evidence[{i}].docstring must quote at least {MIN_EXCERPT_WORDS} words"
            )
            continue
        if symbols is None:
            continue
        if "signature" in item:
            actual = (surface or {}).get("signature")
            if item["signature"] != actual:
                problems.append(f"evidence[{i}].signature isn't pyeye's: {actual!r}")
        elif "docstring" in item:
            if not _word_bounded_in(item["docstring"], (surface or {}).get("docstring", "")):
                problems.append(f"evidence[{i}].docstring isn't in {handle}'s docstring")
        else:
            listed = symbols.edge(handle, str(item["edge"]))
            includes = item["includes"]
            if listed is None:
                problems.append(f"evidence[{i}]: pyeye can't expand {item['edge']!r} on {handle}")
            elif not (isinstance(includes, list) and includes):
                problems.append(f"evidence[{i}].includes must list the handles shown")
            else:
                missing = [h for h in includes if h not in listed]
                if missing:
                    problems.append(
                        f"evidence[{i}]: expand({handle}, {item['edge']}) doesn't list {missing}"
                    )
    return problems


class _ProjectSymbols:
    """:class:`Symbols` over one project, with pyeye's resolver, ``inspect`` and ``expand``.

    The analyzer is built on the first question, so a run with no symbol anchor
    never pays for it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._analyzer: Any = None

    def _jedi(self) -> Any:
        if self._analyzer is None:
            from ..analyzers.jedi_analyzer import JediAnalyzer

            self._analyzer = JediAnalyzer(self._root.as_posix())
        return self._analyzer

    def canonical(self, handle: str) -> str | None:
        """The canonical project handle, following a re-export to its definition site.

        The resolver itself doesn't collapse a relative re-export yet (#857):
        ``pkg.run`` with ``from .core import run`` in ``pkg/__init__.py`` comes
        back as ``pkg.run``. So the binding is followed with Jedi's ``goto``; a
        single definition in another module, which resolves in the project,
        gives the canonical handle. Once #857 lands this guard is redundant, and
        the strict xfail in ``tests/test_docs_facts_review.py`` flags it.
        """
        from ..resolver import Resolved, resolve_handle

        found = resolve_handle(handle, self._jedi())
        if not (isinstance(found, Resolved) and found.scope == "project"):
            return None
        target = self._definition_site(found.anchor)
        if target is not None and target != found.handle:
            resolved = resolve_handle(target, self._jedi())
            if isinstance(resolved, Resolved) and resolved.scope == "project":
                return resolved.handle
        return found.handle

    @staticmethod
    def _definition_site(anchor: Any) -> str | None:
        """The ``full_name`` of the one definition *anchor*'s binding imports, if elsewhere."""
        from ..path_utils import paths_equal

        goto = getattr(anchor, "goto", None)
        here = getattr(anchor, "module_path", None)
        if goto is None or here is None:
            return None
        try:
            defs = goto(follow_imports=True)
        except Exception:  # noqa: BLE001 - Jedi internals; no guard is the safe answer
            return None
        if len(defs) != 1 or not defs[0].full_name or defs[0].module_path is None:
            return None
        if paths_equal(defs[0].module_path, here):
            return None
        return str(defs[0].full_name)

    def surface(self, handle: str) -> dict[str, str] | None:
        import asyncio

        from ..mcp.operations.inspect import inspect

        node = asyncio.run(inspect(handle, self._jedi()))
        if not node.get("found"):
            return None
        return {"signature": node.get("signature") or "", "docstring": node.get("docstring") or ""}

    def edge(self, handle: str, edge: str) -> list[str] | None:
        import asyncio

        from ..mcp.operations.expand import expand

        result = asyncio.run(expand(handle, edge, self._jedi()))
        if not result.get("found") or "stubs" not in result:
            return None
        return [stub["handle"] for stub in result["stubs"]]


def project_symbols(root: Path) -> Symbols:
    """A :class:`Symbols` over the project at *root*, built lazily."""
    return _ProjectSymbols(root)


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


def finding_problems(
    finding: Mapping[str, Any],
    facts: Facts | None = None,
    root: Path | None = None,
    symbols: Symbols | None = None,
) -> list[str]:
    """Why *finding* can't be shown to a human; ``[]`` when it can.

    The shape (D8, C13, C14):

    - ``page``, ``problem``: non-empty strings; ``section``: a string (``""`` is
      the text before the first heading). With *root*, the page must be
      registered and on disk, and the section must be one of its slugs.
    - ``category``: one of :data:`CATEGORIES`.
    - ``anchor``: ``{kind, id}``, what the finding rests on, of the kind its
      category rests on (:data:`CATEGORY_ANCHOR`). A ``fact`` anchor must name a
      fact in *facts*, when given; a ``symbol`` anchor must be the canonical
      handle of a project symbol, checked by *symbols* when given; any other
      kind's ID must be in :data:`RULE_IDS`.
    - A ``code_contradiction`` (prose that says the code does what it doesn't)
      is always a clear fix. Prose must not state code facts (C15, revised), so
      it says its ``route``, in :data:`ROUTES` order: ``fact`` (with the
      ``extractor`` that would produce it), ``example`` (an executed example),
      or, only when neither can work, ``wording`` (with its ``route_reason``).
      It carries ``evidence`` of what pyeye reports for the handle, checked by
      *symbols* when given.
    - A finding on a rule anchor (:data:`SUBJECT_KINDS`) carries its
      ``subject``: the exact page text it is about. With *root*, it must occur
      in the section verbatim, whitespace aside (C15).
    - **A clear fix:** ``replacement``, the proposed text, and none of the
      decision fields (options, question, assessment, recommendation).
    - **Genuine ambiguity:** ``needs_decision: true``, a ``question``, 2 or 3
      ``options`` each with its ``text`` and ``cost``, and either a
      ``recommended`` option index with its ``recommendation_anchor`` (checked
      like the anchor), or, when no anchor backs one, an ``assessment`` starting
      with :data:`UNANCHORED`.

    The tool never decides: a finding without a way forward is rejected, and so
    is a needs-decision finding presented as settled (a replacement).
    """
    problems = [
        f"{name} must be a non-empty string"
        for name in ("page", "problem")
        if not _text(finding.get(name))
    ]
    if not isinstance(finding.get("section"), str):
        problems.append(
            "section must be a string (a slug, or '' for the text before the first heading)"
        )
    category = finding.get("category")
    if category not in CATEGORIES:
        problems.append(f"category must be one of {list(CATEGORIES)}")
    anchor = finding.get("anchor")
    problems.extend(_anchor_problems(anchor, "anchor", facts, symbols))
    if category == "code_contradiction":
        if finding.get("needs_decision") is True:
            problems.append(
                "a code_contradiction is a clear fix: route it to a fact, an example or wording"
            )
        problems.extend(_route_problems(finding, root))
        problems.extend(_evidence_problems(finding, symbols))
    if isinstance(anchor, dict) and anchor.get("kind") in SUBJECT_KINDS:
        if not _text(finding.get("subject")):
            problems.append(
                "a finding on a rule anchor must quote its subject: the exact text it is about"
            )
    if category in CATEGORY_ANCHOR and isinstance(anchor, dict):
        expected = CATEGORY_ANCHOR[category]
        if anchor.get("kind") in ANCHOR_KINDS and anchor.get("kind") != expected:
            problems.append(f"a {category} finding rests on a {expected} anchor")
    if root is not None and not problems:
        problems.extend(_location_problems(finding, root))

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
                _anchor_problems(
                    finding.get("recommendation_anchor"), "recommendation_anchor", facts, symbols
                )
            )
        else:
            if "recommendation_anchor" in finding:
                problems.append("a recommendation_anchor needs a recommended option")
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
        extra = [name for name in _DECISION_FIELDS if name in finding]
        if extra:
            problems.append(f"a clear fix carries no decision fields: {extra}")
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


def _structural_fact(
    kind: str,
    anchor_id: str,
    facts: Facts,
    category: str,
    *,
    symbols: Symbols | None = None,
    subject: str | None = None,
) -> str:
    """The dismissed observation: its identity, then the pin that makes it lapse.

    - A fact anchor is pinned to the fact's value.
    - A symbol anchor is pinned to its signature and docstring as pyeye
      ``inspect`` reports them (C15): a body edit doesn't lapse it, a change to
      either does.
    - A rule anchor's subject is part of its identity (C15), so a different
      subject is a different observation; it has no pin.
    """
    identity = f"{_FACT_PREFIX}{category}:{kind}:{anchor_id}"
    if kind == "fact":
        return f"{identity}:{_digest(fact_value(anchor_id, facts))[:16]}"
    if kind == "symbol":
        if symbols is None:
            raise ValueError("a symbol-anchored dismissal needs pyeye (symbols) to pin it")
        return f"{identity}:{_digest(symbols.surface(anchor_id))[:16]}"
    if kind in SUBJECT_KINDS and subject is not None:
        return f"{identity}:subject={_digest(_flat(subject))[:16]}:-"
    return f"{identity}:-"


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
    symbols: Symbols | None = None,
) -> dict[str, Any]:
    """Record a reviewed *finding* as dismissed; the human's call, never the tool's.

    Keyed on the finding's page and section, category and anchor, and, for a
    rule anchor, its subject (:func:`_structural_fact` has the pins): a
    reworded finding stays dismissed, and a change to what it rests on brings it
    back.
    """
    anchor = finding["anchor"]
    handles = [coverage_key(finding["page"], finding["section"])]
    subject = finding.get("subject")
    fact = _structural_fact(
        anchor["kind"],
        anchor["id"],
        facts,
        finding["category"],
        symbols=symbols,
        subject=subject,
    )
    entry = _entry(handles, fact, reason, dismissed_on, review_after)
    entry["category"] = finding["category"]
    entry["anchor"] = {"kind": anchor["kind"], "id": anchor["id"]}
    if subject is not None:
        entry["subject"] = subject
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
    entry["category"] = "uncovered_fact"
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


#: The command that fixes an orphaned dismissal, as the message gives it.
_SCRIPT = "uv run python scripts/docs_review.py"


def subject_lapsed(entry: Mapping[str, Any], root: Path | None) -> bool:
    """Whether a subject-keyed dismissal's quoted subject has left its live section.

    Such a dismissal LAPSES (C16): ``check`` stays green, the next ``/docs-review``
    command prunes it (:func:`prune`), and its finding may resurface. A prose
    editor never has to touch the review state. Only fact and symbol orphans
    fail ``check``.
    """
    anchor = entry.get("anchor") or {}
    subject = entry.get("subject")
    handles = entry.get("handles")
    if anchor.get("kind") not in SUBJECT_KINDS or root is None or not _text(subject) or not handles:
        return False
    page, _, slug_ = str(handles[0]).partition("#")
    text = section_text(root, page, slug_)
    return text is not None and _flat(str(subject)) not in _flat(text)


def _orphan_reason(
    entry: Mapping[str, Any], facts: Facts, _root: Path | None, symbols: Symbols | None
) -> tuple[str, str] | None:
    """Why *entry* is an orphan that fails ``check``, and ``move``'s argument; else ``None``.

    Only fact and symbol anchors orphan. A subject-keyed dismissal lapses
    instead (:func:`subject_lapsed`).
    """
    anchor = entry.get("anchor") or {}
    kind, anchor_id = anchor.get("kind"), anchor.get("id")
    if kind == "fact" and anchor_id not in facts:
        return (f"names fact {anchor_id!r}, which no longer exists", "<new fact ID>")
    if kind == "symbol" and symbols is not None and symbols.canonical(str(anchor_id)) is None:
        return (
            f"names symbol {anchor_id!r}, which no longer resolves in the project",
            "<new canonical handle>",
        )
    return None


def orphaned(
    state: Mapping[str, Any],
    facts: Facts,
    root: Path | None = None,
    symbols: Symbols | None = None,
) -> list[str]:
    """Dismissals whose anchor is gone (C14, C15); ``check`` fails on each.

    An anchor is gone when its fact no longer exists or its symbol no longer
    resolves (with *symbols*). A subject that left its section lapses instead,
    and a gone section is pruned (:func:`prune`): neither fails ``check`` (C16).
    The message is for whoever made the change, who may never have heard of
    ``/docs-review``: it names the anchor, the file, what the dismissal was for,
    and the command for each fix (move it to the new anchor, or forget it).
    """
    problems = []
    for entry in state.get("confirmed_non_issues", []):
        if not _ours(entry):
            continue
        reason = _orphan_reason(entry, facts, root, symbols)
        if reason is None:
            continue
        what, new = reason
        key = entry.get("key")
        target = (
            "the uncovered-fact ledger (deliberately not covered)"
            if entry.get("reason") == "not-covered"
            else f"a finding on {', '.join(entry.get('handles', []))}"
        )
        problems.append(
            f"{STATE_PATH}: a /docs-review dismissal {what}: it was removed or changed in this "
            f"change. The dismissal is for {target}, recorded {entry.get('date')}. If it was "
            f"renamed or reworded, move it: `{_SCRIPT} move {key} {new}`. Otherwise delete it: "
            f"`{_SCRIPT} forget {key}`."
        )
    return problems


def _find(state: Mapping[str, Any], key: str) -> dict[str, Any]:
    for entry in state.get("confirmed_non_issues", []):
        if _ours(entry) and entry.get("key") == key:
            return dict(entry)
    raise ValueError(f"no /docs-review dismissal with key {key!r} in {STATE_PATH}")


def forget(state: dict[str, Any], key: str) -> dict[str, Any]:
    """Delete the dismissal with *key*, and return it.

    Raises:
        ValueError: If no /docs-review dismissal has that key.
    """
    entry = _find(state, key)
    state["confirmed_non_issues"] = [
        e for e in state["confirmed_non_issues"] if not (_ours(e) and e.get("key") == key)
    ]
    return entry


def move(
    state: dict[str, Any],
    key: str,
    new: str,
    facts: Facts,
    root: Path | None = None,
    symbols: Symbols | None = None,
) -> dict[str, Any]:
    """Carry an orphaned dismissal over to its anchor's new form (C14, C15).

    *new* is the new fact ID, the new canonical handle, or the reworded subject,
    by the dismissal's anchor kind. Only an orphan moves (:func:`orphaned`), so a
    live dismissal can't be re-pointed at something unrelated. A fact or symbol
    keeps its old pin: the moved dismissal holds only if the value, or the
    signature and docstring, are unchanged; otherwise it lapses and the finding
    comes back.

    Raises:
        ValueError: If no dismissal has *key*, it isn't an orphan, or *new*
            doesn't exist, resolve or occur.
    """
    old = _find(state, key)
    anchor = old.get("anchor") or {}
    kind = anchor.get("kind")
    if kind not in ("fact", "symbol", *SUBJECT_KINDS):
        raise ValueError(f"dismissal {key} has no anchor that can move")
    if _orphan_reason(old, facts, root, symbols) is None and not subject_lapsed(old, root):
        if kind in SUBJECT_KINDS and root is None:
            raise ValueError("moving a subject needs the repo root to read the section")
        if kind == "symbol" and symbols is None:
            raise ValueError("moving a symbol needs pyeye (symbols) to resolve it")
        raise ValueError(
            f"dismissal {key}'s anchor still exists: only a dismissal whose anchor was "
            "removed, renamed or reworded can move"
        )
    category = old.get("category", "uncovered_fact")
    pin = str(old["structural_fact"]).rsplit(":", 1)[1]
    new_anchor_id, subject = anchor.get("id"), old.get("subject")
    if kind == "fact":
        if new not in facts:
            raise ValueError(f"no fact {new!r} to move the dismissal to")
        new_anchor_id = new
        fact = f"{_FACT_PREFIX}{category}:fact:{new}:{pin}"
    elif kind == "symbol":
        assert symbols is not None  # orphaned above needs it  # nosec B101
        if symbols.canonical(new) != new:
            raise ValueError(f"{new!r} isn't the canonical handle of a project symbol")
        new_anchor_id = new
        fact = f"{_FACT_PREFIX}{category}:symbol:{new}:{pin}"
    else:
        assert root is not None  # nosec B101
        page, _, slug_ = str(old["handles"][0]).partition("#")
        if _flat(new) not in _flat(section_text(root, page, slug_) or ""):
            raise ValueError(f"{new!r} doesn't occur verbatim in {old['handles'][0]}")
        subject = new
        fact = _structural_fact(kind, str(new_anchor_id), facts, category, subject=new)
    forget(state, key)
    handles = [str(new_anchor_id)] if old.get("reason") == "not-covered" else list(old["handles"])
    entry = _entry(handles, fact, old["reason"], old["date"], old.get("review_after"))
    entry.update({k: v for k, v in old.items() if k in ("note",)})
    entry["category"] = category
    entry["anchor"] = {"kind": kind, "id": new_anchor_id}
    if subject is not None:
        entry["subject"] = subject
    _replace(state, entry)
    return entry


def prune(state: dict[str, Any], root: Path) -> list[str]:
    """Drop coverage and finding dismissals for gone sections, and lapsed subjects.

    A subject-keyed dismissal whose subject left its section has lapsed (C16):
    it is dropped here, and its finding may resurface.

    A renamed heading or a deleted page leaves them behind: a finding there would
    have a new key anyway, so they can never match again. They are removed, not
    failed on: a heading rename isn't something the PR author must repair. The
    ``page#section`` of each one removed is returned.
    """
    live: dict[str, set[str]] = {}

    def exists(handle: str) -> bool:
        page, _, slug_ = handle.partition("#")
        if page not in live:
            path = root / page
            live[page] = (
                {s.slug for s in sections(path.read_text(encoding="utf-8"))}
                if path.is_file()
                else set()
            )
        return slug_ in live[page]

    removed = sorted(h for h in state.get("coverage", {}) if not exists(h))
    for handle in removed:
        del state["coverage"][handle]
    kept = []
    for entry in state.get("confirmed_non_issues", []):
        handles = entry.get("handles") or []
        is_section = _ours(entry) and entry.get("reason") != "not-covered" and handles
        if is_section and (not exists(handles[0]) or subject_lapsed(entry, root)):
            removed.append(handles[0])
            continue
        kept.append(entry)
    if "confirmed_non_issues" in state:
        state["confirmed_non_issues"] = kept
    return removed


#: A finding's status after the state is applied (as ``/duplication-review``'s).
STATUSES = ("new", "resurfaced", "review-due")


def triage(
    findings: Iterable[Mapping[str, Any]],
    state: Mapping[str, Any],
    facts: Facts,
    today: str | None = None,
    symbols: Symbols | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """The findings to show, each with its status; dismissed ones are left out.

    - ``new``: no dismissal matches it (a different subject is a different finding).
    - ``resurfaced``: it was dismissed, but what it rests on has changed: the
      anchor fact's value, or the symbol's signature or docstring.
    - ``review-due``: its dismissal's ``review_after`` has been reached (*today*,
      caller-supplied; with no *today*, nothing comes due).
    """
    entries = [e for e in state.get("confirmed_non_issues", []) if _ours(e)]
    shown: list[tuple[dict[str, Any], str]] = []
    for finding in findings:
        anchor = finding["anchor"]
        handles = [coverage_key(finding["page"], finding["section"])]
        fact = _structural_fact(
            anchor["kind"],
            anchor["id"],
            facts,
            finding["category"],
            symbols=symbols,
            subject=finding.get("subject"),
        )
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


def _section_fact_ids(section: Section, entry: Any, facts: Facts, text: str) -> list[str]:
    """The facts a section's freshness depends on.

    Its own blocks' facts, plus the page's ``covers`` facts that the section
    names, as the fact's inline-code rendering (```PYEYE_CACHE_TTL```). A covered
    fact that no section names counts for every section: where the prose
    explains it is unknown, so any of them may need review when it changes.
    """
    from . import binding, ledger

    blocks, _ = binding.parse(section.text)
    ids = ledger.expand([b.fact_id for b in blocks], facts)
    covered = ledger.expand(entry.covers, facts)
    every = sections(text)
    for fact_id in covered:
        mark = facts[fact_id].markdown
        named_by = [s for s in every if mark and mark in s.text]
        if not named_by or any(s.slug == section.slug for s in named_by):
            ids.add(fact_id)
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
        ids = _section_fact_ids(section, entry, facts, text)
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
        if before is None:
            raise ValueError(
                f"can't read {SNAPSHOT} at {base!r}: give a git revision that has it "
                "(e.g. origin/main), or name pages instead"
            )
        diff = changed_facts.diff(before, _committed_snapshot(root), {})
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


def _with_pruned(out: Any, pruned: list[str]) -> Any:
    if pruned and isinstance(out, dict):
        out = {**out, "pruned": pruned}
    return out


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
    p_forget = sub.add_parser("forget", help="delete a dismissal (one whose fact is gone)")
    p_forget.add_argument("key")
    p_move = sub.add_parser(
        "move", help="carry an orphaned dismissal over to its new fact, handle or subject"
    )
    p_move.add_argument("key")
    p_move.add_argument("new", help="the new fact ID, canonical handle or reworded subject")
    p_unc = sub.add_parser("dismiss-uncovered", help="record a fact as deliberately not covered")
    p_unc.add_argument("fact")
    p_unc.add_argument("--reason", required=True, help="why it is deliberately not covered")
    p_unc.add_argument("--date", required=True)
    args = parser.parse_args(argv)
    base: Path = args.root
    try:
        facts = build(base)
        symbols = project_symbols(base)
        if args.command == "scope":
            out: Any = scope(base, facts, pages=args.pages, audience=args.audience, base=args.base)
        elif args.command == "validate":
            findings = _read_findings(args.findings)
            problems = {
                str(i): found
                for i, f in enumerate(findings)
                if (found := finding_problems(f, facts, base, symbols))
            }
            if problems:
                print(json.dumps({"problems": problems}, indent=2))
                return 1
            shown = triage(findings, load(base), facts, args.today, symbols)
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
            ids = _section_fact_ids(match[0], entry, facts, text)
            mark_reviewed(state, args.page, match[0], ids, facts, args.date)
            out = {"marked": coverage_key(args.page, args.section)}
            out = _with_pruned(out, prune(state, base))
            save(base, state)
        elif args.command == "dismiss":
            findings = _read_findings(args.findings)
            finding = findings[args.index]
            found = finding_problems(finding, facts, base, symbols)
            if found:
                raise ValueError(f"finding {args.index} is invalid: {found}")
            state = load(base)
            out = dismiss_finding(
                state, finding, facts, args.reason, args.date, args.review_after, symbols
            )
            out = _with_pruned(out, prune(state, base))
            save(base, state)
        elif args.command == "forget":
            state = load(base)
            out = {"forgot": forget(state, args.key)}
            out = _with_pruned(out, prune(state, base))
            save(base, state)
        elif args.command == "move":
            state = load(base)
            out = {"moved": move(state, args.key, args.new, facts, base, symbols)}
            out = _with_pruned(out, prune(state, base))
            save(base, state)
        else:
            state = load(base)
            out = dismiss_uncovered(state, args.fact, facts, args.reason, args.date)
            out = _with_pruned(out, prune(state, base))
            save(base, state)
            out["next"] = "run `uv run python scripts/docs_facts.py generate` to update the ledger"
    except (ValueError, IndexError, OSError) as exc:
        print(f"docs_review: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0
