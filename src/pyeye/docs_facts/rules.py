"""Prose rules: phrasing the docs must not use, or must carry (#818, #825).

A fact check compares a documented value with an extracted one. A prose rule
can't: it requires or forbids *phrasing* that no extractor produces, such as
calling an unresolved handle one that "doesn't exist" (#568). Each rule here runs
over every registered doc of the kinds it applies to (the repository's doc
registry, never a list of its own) and over the live MCP tool descriptions, which are the docs a
model reads.

The text inside fact blocks is skipped: it is generated from the code, so it is
the fact checks' business, not a rule's.

**The ratchet.** Today's violations are recorded per page in
:attr:`~.docs.DocEntry.allow` (rule ID -> the exact message of each finding still
allowed). It can only shrink. ``check`` fails on a finding the page doesn't
allow, and on an allowance no finding uses, so a fix removes its allowance in
the same PR and can't be traded for a new violation. Tool descriptions and the
``pyeye.mcp`` string literals have no allow-list: they must be clean.
"""

from __future__ import annotations

import ast
import asyncio
import io
import re
import tokenize
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..async_utils import filtered_rglob
from ..path_utils import relative_within
from . import (
    binding,
    claims,
    docs as doc_registry,
)
from .docs import DocEntry, Kind, registered_files
from .facts import Bindable, Fact

Facts = Mapping[str, Bindable]

# ---------------------------------------------------------------------------
# Rule IDs
# ---------------------------------------------------------------------------

STATIC_CEILING = "static-ceiling"
EDGE_CEILING = "edge-ceiling"
ABSENCE_PROSE = "absence-prose"
EDGE_COUNTS_PROSE = "edge-counts-prose"
HONEST_CLAIMS = "honest-claims"
#: Owned by #826 (removed names in prose); registered here so its allow-list
#: entries are valid keys.
REMOVED_NAME = "removed-name"
ENV_NAME = "env-name"
SERVER_COMMAND = "server-command"
#: The ``structure`` kind's rules (#1092), built per extractor so they follow
#: its fact prefix (:mod:`.extractors.structure`).
LAYERING = "layering"
STRUCTURE_COVERAGE = "structure-coverage"

#: Every rule ID a :attr:`~.docs.DocEntry.allow` key may name. A key outside this
#: set is a typo that would silently allow nothing, so it fails.
RULE_IDS: frozenset[str] = frozenset(
    {
        STATIC_CEILING,
        EDGE_CEILING,
        ABSENCE_PROSE,
        EDGE_COUNTS_PROSE,
        HONEST_CLAIMS,
        REMOVED_NAME,
        ENV_NAME,
        SERVER_COMMAND,
        LAYERING,
        STRUCTURE_COVERAGE,
    }
)

#: Kinds the phrasing rules apply to. History pages must be free to quote what
#: was once wrong (C1); generated reference pages hold no hand-written prose.
_LIVE: frozenset[Kind] = frozenset({"prose", "skill"})
#: The fact rules also cover history pages: a migration guide is where people
#: copy env vars and commands from (design C11). Released CHANGELOG sections stay
#: exempt (:func:`released_blanked`).
_LIVE_AND_HISTORY: frozenset[Kind] = frozenset({"prose", "skill", "history"})


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def prose_text(text: str) -> str:
    """*text* with every fact block's content blanked, line numbers kept.

    A malformed block is left as it is; ``check`` reports the marker itself.
    """
    blocks, _problems = binding.parse(text)
    pieces: list[str] = []
    cursor = 0
    for block in blocks:
        pieces.append(text[cursor : block.start])
        pieces.append(re.sub(r"[^\n]", " ", text[block.start : block.end]))
        cursor = block.end
    pieces.append(text[cursor:])
    return "".join(pieces)


#: A released version's heading in ``CHANGELOG.md``: ``## [2.1.0] - 2026-11-12``.
_RELEASED = re.compile(r"^## \[\d[^\]]*\]", re.MULTILINE)
CHANGELOG = "CHANGELOG.md"


def released_blanked(text: str) -> str:
    """*text* with every released CHANGELOG section blanked, line numbers kept.

    A released section is a historical record of what was said at that release,
    not a claim made now, so no rule reads it (design Q1). ``[Unreleased]``
    above it is still checked.
    """
    match = _RELEASED.search(text)
    if match is None:
        return text
    return text[: match.start()] + re.sub(r"[^\n]", " ", text[match.start() :])


def paragraphs(text: str) -> Iterator[tuple[int, str]]:
    """``(first line, flattened text)`` for each blank-line-separated paragraph.

    Backticks and line wrapping split phrases (an ``edge_counts`` span wrapped
    before ``.subclasses``), so both are removed before a rule matches.
    """
    start: int | None = None
    lines: list[str] = []
    for number, line in enumerate([*text.splitlines(), ""], 1):
        if line.strip():
            if start is None:
                start = number
            lines.append(line)
        elif start is not None:
            yield start, " ".join(" ".join(lines).replace("`", "").split())
            start, lines = None, []


@dataclass(frozen=True)
class Finding:
    """One violation: the 1-based line it starts on and what's wrong.

    The message carries no line number: it is also what an allowance names.
    """

    line: int
    message: str


@dataclass(frozen=True)
class Page:
    """A surface a rule scans.

    Attributes:
        name: A registered path, ``tool:<name>`` for a tool description, or
            ``pyeye/<module>:<line>`` for a string the MCP package ships.
        text: The full text, fact blocks included.
        prose: The text with fact-block content blanked (:func:`prose_text`).
        kind: The page's registry kind, or ``None`` for a code surface.
        line: The source line the text starts on (a string literal's), so a
            finding's line is reported in the file, not in the string.
        root: The repository root, for resolving links (registered pages only).
        records: Repo-relative paths of the registered ``record`` pages.
    """

    name: str
    text: str
    prose: str
    kind: Kind | None
    line: int = 1
    root: Path | None = None
    records: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Rule:
    """A named prose rule.

    Attributes:
        id: The rule ID, a key of :attr:`~.docs.DocEntry.allow`.
        kinds: The registry kinds it scans.
        descriptions: Whether it also scans the live tool descriptions.
        scan: Returns the page's violations; takes the page and the facts.
        strings: Whether it also scans the string literals of the ``pyeye.mcp``
            package: the hints and notes it returns inside responses, the most
            model-facing text pyeye has (design C10, Q8).
        requires: The facts it reads (#1091): a fact ID, or a prefix ending in
            ``.`` that some fact must start with. A rule whose facts are absent
            (another repository has none of pyeye's) is skipped and reported,
            never run on half a fact set (:func:`missing_facts`).
        audit: A repository-wide check, run once per ``check``/``generate``
            rather than per page (#1092): the facts in, one message per problem
            out. It is given a read-only view of the facts and nothing else (no
            root, so no file reads; C19), and its problems belong to no page, so
            no allow-list can hold them.
    """

    id: str
    kinds: frozenset[Kind]
    descriptions: bool
    scan: Callable[[Page, Facts], list[Finding]]
    strings: bool = False
    requires: frozenset[str] = frozenset()
    audit: Callable[[Facts], list[str]] | None = None


def missing_facts(rule: Rule, facts: Facts) -> list[str]:
    """The requirements of *rule* that *facts* don't meet, sorted (#1091).

    A requirement ending in ``.`` is a prefix: met when some fact ID starts with it.
    """
    missing = []
    for need in rule.requires:
        met = any(i.startswith(need) for i in facts) if need.endswith(".") else need in facts
        if not met:
            missing.append(need)
    return sorted(missing)


def skipped(rules: Iterable[Rule], facts: Facts) -> list[str]:
    """``skipped rule <id>: needs <facts>`` for each rule whose facts are absent (#1091)."""
    notes = []
    for rule in rules:
        missing = missing_facts(rule, facts)
        if missing:
            notes.append(f"skipped rule {rule.id}: needs {', '.join(missing)}")
    return notes


# ---------------------------------------------------------------------------
# #568: absence is unknown, not nonexistence
# ---------------------------------------------------------------------------

_NONEXISTENCE = re.compile(
    r"\b(?:handle|symbol|member|subclass|attribute|name)s?\b"
    r"[^.;:]{0,40}?\b(?:doesn't|does not|don't|do not) exist\b",
    re.IGNORECASE,
)
_NOT_IN_SOURCE = re.compile(r"not in source", re.IGNORECASE)
_WRITTEN_IN_SOURCE = re.compile(r"complete over what is \*?written in source", re.IGNORECASE)

_ABSENCE_PATTERNS = {
    "claims a symbol/handle/member doesn't exist": _NONEXISTENCE,
    'calls an absent member "not in source"': _NOT_IN_SOURCE,
    'claims completeness over "written in source"': _WRITTEN_IN_SOURCE,
}


def absence_claims(text: str) -> list[Finding]:
    """Each place *text* states a resolution miss or an absence as nonexistence (#568).

    The absence-vs-zero invariant (``docs/api-redesign.md``): what pyeye doesn't
    return, or can't resolve, is unknown, not absent. A filesystem fact ("a
    ``project_path`` that doesn't exist") is not a claim about a symbol, so it
    passes.
    """
    found: list[Finding] = []
    for line, flat in paragraphs(text):
        flat = flat.replace('"', "")
        for label, pattern in _ABSENCE_PATTERNS.items():
            for match in pattern.finditer(flat):
                start = max(0, match.start() - 60)
                found.append(Finding(line, f"{label}: ...{flat[start : match.end() + 20]}..."))
    return found


# ---------------------------------------------------------------------------
# #396: no unmeasured edge inside edge_counts
# ---------------------------------------------------------------------------

_BRACE_FORM = re.compile(r"edge_counts\s*[:=]\s*\{([^}]*)\}")
_BRACE_KEY = re.compile(r"[\"']?(\w+)[\"']?\s*:")
# edge_counts.X, edge_counts["X"], and result["edge_counts"]["X"]
_ACCESS_FORM = re.compile(r"edge_counts(?:[\"']\])?\s*(?:\.\s*(\w+)|\[\s*[\"'](\w+)[\"']\s*\])")
_COUNT_FORM = re.compile(r"\b(\w+)\s*:\s*\d")
#: The longest paragraph quoted in a finding.
_SNIPPET = 160


#: The fact holding the edges ``inspect`` doesn't measure (the response linter's set).
UNMEASURED_FACT = "edges.inspect_unmeasured"


def _unmeasured(facts: Facts) -> list[str]:
    fact = facts[UNMEASURED_FACT]
    if not isinstance(fact, Fact):
        raise TypeError(f"{UNMEASURED_FACT!r} is a view, not a fact")
    return list(fact.value)


def edge_counts_claims(text: str, unmeasured: Iterable[str]) -> list[Finding]:
    """Each place *text* shows an unmeasured edge as an ``edge_counts`` key (#396).

    Structural, not free text: within a paragraph that mentions ``edge_counts``,
    an edge is *claimed present* only as a brace key (``edge_counts: { …,
    subclasses: 0 }``), as dotted or subscript access, or as a count
    (``subclasses: 0``). Naming an edge to say it is omitted passes.
    """
    skip = frozenset(unmeasured)
    found: list[Finding] = []
    for line, flat in paragraphs(text):
        if "edge_counts" not in flat:
            continue
        claimed = [key for body in _BRACE_FORM.findall(flat) for key in _BRACE_KEY.findall(body)]
        claimed += [dotted or subscript for dotted, subscript in _ACCESS_FORM.findall(flat)]
        claimed += _COUNT_FORM.findall(flat)
        for edge in sorted(set(claimed) & skip):
            snippet = flat if len(flat) <= _SNIPPET else flat[: _SNIPPET - 3] + "..."
            found.append(Finding(line, f"unmeasured edge {edge!r} shown in edge_counts: {snippet}"))
    return found


# ---------------------------------------------------------------------------
# #417: the static-surface ceiling caveat
# ---------------------------------------------------------------------------

#: The one phrase every surface that presents a static structural edge carries.
CEILING_MARKER = "Static-surface ceiling"

#: The ceilings the static-surface caveat speaks for: what is literally written
#: in source (a class body, a ``class B(A):`` statement). Every edge whose
#: ceiling fact is one of these must carry the marker (design C12).
STATIC_CEILINGS = frozenset({"static_definitions", "literal_subclassing"})


def static_edges(facts: Facts) -> tuple[str, ...]:
    """The edges whose ``edge.*`` fact has a static-surface ceiling, sorted."""
    return tuple(
        sorted(
            fact_id.split(".", 1)[1]
            for fact_id, fact in facts.items()
            if fact_id.startswith("edge.")
            and isinstance(fact, Fact)
            and fact.value.get("ceiling") in STATIC_CEILINGS
        )
    )


def ceiling_edges(facts: Facts) -> tuple[str, ...]:
    """The edges whose ``edge.*`` fact has any ceiling, sorted; exact edges are left out.

    The edge-ceiling rule's set (#827, C12), derived from the same facts as
    :func:`static_edges`: every edge here must state its own ceiling meaning
    wherever a tool description exposes it. The static set is a subset of it.
    """
    return tuple(
        sorted(
            fact_id.split(".", 1)[1]
            for fact_id, fact in facts.items()
            if fact_id.startswith("edge.")
            and isinstance(fact, Fact)
            and isinstance(fact.value, dict)
            and fact.value.get("ceiling") is not None
        )
    )


def _named_edge(edges: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"[\"`](" + "|".join(map(re.escape, edges)) + r")[\"`]")


#: A description's entry for one edge: ``- ``members``  — …`` up to the next entry.
_EDGE_ENTRY = re.compile(r"^(?P<indent>[ \t]*)- ``(?P<edge>\w+)``", re.MULTILINE)


def _edge_entries(text: str) -> dict[str, tuple[int, str]]:
    """Edge name -> (line, text) of each ``- ``edge``  —`` entry in a description."""
    matches = list(_EDGE_ENTRY.finditer(text))
    entries: dict[str, tuple[int, str]] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blank = text.find("\n\n", match.start(), end)
        body = text[match.start() : blank if blank != -1 else end]
        entries[match.group("edge")] = (text.count("\n", 0, match.start()) + 1, body)
    return entries


def missing_ceiling(page: Page, facts: Facts) -> list[Finding]:
    """The ceiling marker is missing where a static edge is presented (#417).

    A registered page presents the edges when it binds ``edges.implemented`` or
    ``edges.table``. A tool description that gives a static edge its own entry
    (``- ``members``  — …``, as ``expand`` does) must carry the marker in that
    entry, per edge; one that only names the edges must carry it somewhere.
    """
    if page.kind is not None:
        if CEILING_MARKER in page.text:
            return []
        blocks, _ = binding.parse(page.text)
        for block in blocks:
            if block.fact_id in {"edges.implemented", "edges.table"}:
                return [Finding(block.line, f"binds {block.fact_id} without {CEILING_MARKER!r}")]
        return []
    static = static_edges(facts)
    if not static:
        return []
    entries = _edge_entries(page.text)
    found = [
        Finding(line, f"the {edge!r} entry lacks {CEILING_MARKER!r}")
        for edge, (line, body) in sorted(entries.items())
        if edge in static and CEILING_MARKER not in body
    ]
    if found or CEILING_MARKER in page.text:
        return found
    match = _named_edge(static).search(page.text)
    if match is None:
        return []
    line = page.text.count("\n", 0, match.start()) + 1
    return [Finding(line, f"names the {match.group(1)!r} edge without {CEILING_MARKER!r}")]


# ---------------------------------------------------------------------------
# #827 (design C12): each exposed edge states its own ceiling
# ---------------------------------------------------------------------------


def _edge_named(edge: str, text: str) -> re.Match[str] | None:
    return re.search(rf"(?:``|\")({re.escape(edge)})(?:``|\")", text)


def missing_edge_ceiling(page: Page, facts: Facts) -> list[Finding]:
    """An edge a tool description exposes doesn't state its own ceiling meaning.

    Every edge with a ceiling (its ``edge.*`` fact names one) that the
    description names, as ````edge```` or ``"edge"``, must be stated as
    :func:`~.describe.ceiling_statement` renders it, ````<ceiling>``: <meaning>``.
    An edge with its own entry (``- ``edge``  — …``, as ``expand`` gives each
    edge) must state it in that entry; an edge named elsewhere (a list of edges,
    as ``trace`` gives) must have it stated somewhere in the description. The
    ``ceiling`` and ``ceilings`` slot forms render exactly this text. Exact edges
    have no ceiling and are skipped. Registered pages aren't scanned: they show
    ceilings through ``edges.table`` and ``ceilings.table`` blocks.
    """
    from .describe import ceiling_statement

    if page.kind is not None:
        return []
    flat = " ".join(page.text.split())
    entries = _edge_entries(page.text)
    found = []
    for edge in ceiling_edges(facts):
        fact = facts[f"edge.{edge}"]
        assert isinstance(fact, Fact)  # nosec B101 - ceiling_edges yields only edge facts
        statement = ceiling_statement(fact, facts)
        if statement is None:
            continue
        if edge in entries:
            line, body = entries[edge]
            if statement not in " ".join(body.split()):
                found.append(Finding(line, f"the {edge!r} entry doesn't state its ceiling"))
            continue
        match = _edge_named(edge, page.text)
        if match is not None and statement not in flat:
            line = page.text.count("\n", 0, match.start()) + 1
            found.append(Finding(line, f"exposes the {edge!r} edge without its ceiling"))
    return found


# ---------------------------------------------------------------------------
# #556 and #553: env vars and server commands named in the docs exist
# ---------------------------------------------------------------------------


def _removed_names(root: Path | None) -> frozenset[str]:
    """Env vars and commands that are gone: a live page may name one only beside "removed".

    Read from ``docs/facts/removed.json`` (#826, C2): every ``env.*`` and ``cli.*``
    entry, whatever its ``match``. The record's own rule (:mod:`.removed`) handles
    the allow-list and the sunset for the same lines. An installed package has no
    record, so the set is empty there. The wrong names the old checks caught
    (``PYEYE_PACKAGES``, ``uv run pyeye``, ``mcp dev`` and the like) were never
    read or never worked, so they were never *removed* and aren't in the record.
    They always fail, and "removed" beside them would be a false claim (D12).
    """
    from . import removed

    if root is None:
        return frozenset()
    return frozenset(e.name for e in removed.load(root) if e.fact_id.startswith(("env.", "cli.")))


# Includes lowercase suffixes, e.g. the once-documented ``PYEYE_NAMESPACE_company``.
_ENV = re.compile(r"\bPYEYE_[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]")


def _lines(text: str) -> Iterator[tuple[int, str]]:
    yield from enumerate(text.splitlines(), 1)


def _says_removed(line: str) -> bool:
    return "removed" in line.lower()


def env_name_claims(text: str, facts: Facts, root: Path | None = None) -> list[Finding]:
    """Each ``PYEYE_*`` name that doesn't take effect, on its line (#556, #628).

    A name passes when pyeye reads *and uses* it (status ``live``), or when it is
    deprecated and the line says so. A loaded-but-unused variable fails: the docs
    would promise a knob that does nothing. *root* is the repository the page
    is in, whose ``removed.json`` names what was removed (#1091).
    """
    removed = _removed_names(root)
    found: list[Finding] = []
    for number, line in _lines(text):
        for name in sorted(set(_ENV.findall(line))):
            fact = facts.get(f"env.{name}")
            status = fact.value.get("status") if isinstance(fact, Fact) else None
            if status == "live":
                continue
            if status == "deprecated":
                if "deprecated" not in line.lower():
                    found.append(Finding(number, f"{name} is deprecated; say so on the line"))
                continue
            if status == "unused":
                found.append(Finding(number, f"{name} is loaded but nothing uses it"))
            elif name in removed and _says_removed(line):
                continue
            else:
                found.append(Finding(number, f"{name} is not a variable pyeye reads"))
    return found


_RUN_SCRIPT = re.compile(r"\buv (?:--directory \S+ )?run (pyeye[\w-]*)\b")
_OLD_SERVER_PATH = re.compile(r"src/pyeye/server\.py")
_RUN_AS_FILE = re.compile(r"python\s+\S*src/pyeye/mcp/server\.py")
_MCP_DEV = re.compile(r"\bmcp dev\b")
#: ``claude mcp add`` forms that aren't valid syntax.
_INVALID_FORMS = ("claude mcp add /", '--command "', '--directory "/path/to/your')


def server_command_claims(text: str, facts: Facts, root: Path | None = None) -> list[Finding]:
    """Each documented way to start the server that doesn't work (#553).

    The ways that work are the ``cli.*`` facts: the console scripts and
    ``python -m pyeye.mcp``. The server module can't run as a file (relative
    imports), and ``mcp dev`` can't load it. *root* is as for
    :func:`env_name_claims`.
    """
    removed = _removed_names(root)
    found: list[Finding] = []
    for number, line in _lines(text):
        for match in _RUN_SCRIPT.finditer(line):
            name = match.group(1)
            if f"cli.script.{name}" in facts:
                continue
            if name in removed and _says_removed(line):
                continue
            scripts = sorted(i.split(".", 2)[2] for i in facts if i.startswith("cli.script."))
            found.append(Finding(number, f"no console script {name!r} (have {scripts})"))
        for pattern, name, problem in (
            (
                _OLD_SERVER_PATH,
                "src/pyeye/server.py",
                "names src/pyeye/server.py, which doesn't exist (the module is "
                "src/pyeye/mcp/server.py; start it with `python -m pyeye.mcp`)",
            ),
            (
                _RUN_AS_FILE,
                "",
                "runs the server module as a file, which fails on its relative imports; "
                "use `python -m pyeye.mcp`",
            ),
            (_MCP_DEV, "mcp dev", "`mcp dev` can't load the server; use the MCP Inspector via npx"),
        ):
            if pattern.search(line) and not (name in removed and _says_removed(line)):
                found.append(Finding(number, problem))
        found.extend(
            Finding(number, f"invalid `claude mcp add` form {form!r}")
            for form in _INVALID_FORMS
            if form in line
        )
    return found


# ---------------------------------------------------------------------------
# The rule table
# ---------------------------------------------------------------------------

#: Every page that holds hand-written claims: history too (D12 applies to every
#: registered page). A ``record`` is the backing, and a reference page is facts.
_CLAIMS: frozenset[Kind] = frozenset({"prose", "skill", "history"})


def honest_claims(page: Page, facts: Facts) -> list[Finding]:  # noqa: ARG001
    """Each number or volatile status no fact, record or source backs (D12)."""
    return [
        Finding(c.line, c.message)
        for c in claims.claims(page.prose, page.name, page.root, page.records)
    ]


#: The facts pyeye's edge rules read: its edges and their ceilings (#1091).
_EDGE_FACTS = frozenset({"edge.", "ceiling."})
#: pyeye's absence and edge_counts conventions are about its own edges: the
#: set ``inspect`` leaves unmeasured is their marker (#1091).
_EDGE_COUNT_FACTS = frozenset({UNMEASURED_FACT})

RULES: tuple[Rule, ...] = (
    Rule(STATIC_CEILING, _LIVE, True, missing_ceiling, requires=_EDGE_FACTS),
    Rule(EDGE_CEILING, frozenset(), True, missing_edge_ceiling, requires=_EDGE_FACTS),
    Rule(
        ABSENCE_PROSE,
        _LIVE,
        True,
        lambda page, _facts: absence_claims(page.prose),
        strings=True,
        requires=_EDGE_COUNT_FACTS,
    ),
    Rule(
        EDGE_COUNTS_PROSE,
        _LIVE,
        True,
        lambda page, facts: edge_counts_claims(page.prose, _unmeasured(facts)),
        strings=True,
        requires=_EDGE_COUNT_FACTS,
    ),
    Rule(HONEST_CLAIMS, _CLAIMS, False, honest_claims),
    Rule(
        ENV_NAME,
        _LIVE_AND_HISTORY,
        False,
        lambda page, facts: env_name_claims(page.prose, facts, page.root),
        requires=frozenset({"env."}),
    ),
    Rule(
        SERVER_COMMAND,
        _LIVE_AND_HISTORY,
        False,
        lambda page, facts: server_command_claims(page.prose, facts, page.root),
        requires=frozenset({"cli.script."}),
    ),
)


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


#: Where a rule's allowances live, when not on the doc registry's entries themselves.
_ALLOW_HOME = {HONEST_CLAIMS: "claim_seeds.py"}


def ratchet(entry: DocEntry, rule_id: str, found: Sequence[str]) -> str | None:
    """Compare the *found* finding messages with what *entry* allows for *rule_id*.

    An allowance names what it covers: the exact message of each finding still
    allowed, one per occurrence. So a fix can't be traded for a new violation,
    and an allowance for one name covers no other.

    Returns:
        ``None`` when they match, or the problem: a finding not allowed (new), or
        an allowance no finding uses (a fix that didn't remove it).
    """
    allowed = Counter(entry.allow.get(rule_id, ()))
    actual = Counter(found)
    new = sorted((actual - allowed).elements())
    stale = sorted((allowed - actual).elements())
    if new:
        return f"{rule_id}: {len(new)} finding(s) not in the page's allow-list"
    if stale:
        return (
            f"{rule_id}: allowed but no longer found, so remove from the page's allow "
            f"(src/pyeye/docs_facts/{_ALLOW_HOME.get(rule_id, 'docs.py')}): {stale}"
        )
    return None


def allow_problems(docs: Iterable[DocEntry]) -> list[str]:
    """Allow-list keys that name no rule, or that allow nothing."""
    problems: list[str] = []
    for entry in docs:
        for rule_id, messages in sorted(entry.allow.items()):
            if rule_id not in RULE_IDS:
                problems.append(
                    f"{entry.path}: allow names unknown rule {rule_id!r} "
                    f"(known: {', '.join(sorted(RULE_IDS))})"
                )
            elif isinstance(messages, str) or not messages:
                problems.append(
                    f"{entry.path}: allow[{rule_id!r}] must be a non-empty tuple of messages"
                )
    return problems


def _tool_descriptions() -> dict[str, str]:
    """Every live tool's description: core, admin and plugin tools."""
    from mcp.server.mcpserver import MCPServer

    from ..mcp import server as srv

    async def listed(server: Any) -> list[Any]:
        return list(await server.list_tools())

    servers: list[Any] = [srv.mcp]
    admin = MCPServer("docs-rules-admin")
    admin.tool()(srv.get_connection_diagnostics)
    admin.tool()(srv.get_performance_metrics)
    servers.append(admin)
    for plugin_class in srv._PLUGIN_CLASSES:
        plugin_server = MCPServer("docs-rules-plugin")
        srv.register_plugin_tools(plugin_server, [plugin_class(".")])
        servers.append(plugin_server)
    return {t.name: t.description or "" for s in servers for t in asyncio.run(listed(s))}


def _rendered(node: ast.expr) -> str | None:
    """A string literal's text; an f-string's with each placeholder as ``{}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    return None


def _comment_blocks(source: str) -> Iterator[tuple[int, str]]:
    """``(first line, text)`` for each run of comments on consecutive lines.

    A run is one page, so a phrase wrapped across comment lines is still seen.
    """
    start, last = 0, -1
    lines: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        row = token.start[0]
        if lines and row != last + 1:
            yield start, "\n".join(lines)
            lines = []
        if not lines:
            start = row
        lines.append(token.string.lstrip("#").strip())
        last = row
    if lines:
        yield start, "\n".join(lines)


def code_strings() -> Iterator[Page]:
    """Every string literal, docstring and comment in the ``pyeye.mcp`` package.

    The package itself is the scope, never a list of its files: the response
    hints and notes (``not_found``, ``resolve`` …) and the tool docstrings all
    live there. Comments are included because the original #395 miss was a
    comment in ``server.py``, and comment wording is what gets copied into
    docstrings next (design C11). F-string pieces inside a larger f-string
    aren't repeated.
    """
    from .. import mcp as mcp_package

    package = Path(mcp_package.__file__).parent
    for path in sorted(filtered_rglob("*.py", package)):
        rel = relative_within(path, package.parent)
        if rel is None:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        name = f"pyeye/{rel.as_posix()}"
        for line, comment in _comment_blocks(source):
            yield Page(name, comment, comment, None, line)
        inner = {
            id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values
        }
        for node in ast.walk(tree):
            if id(node) in inner or not isinstance(node, ast.expr):
                continue
            text = _rendered(node)
            if text and text.strip():
                yield Page(name, text, text, None, node.lineno)


def pages(root: Path, docs: tuple[DocEntry, ...] | None = None) -> Iterator[tuple[Page, DocEntry]]:
    """Every registered doc as a :class:`Page`, with its entry."""
    found = list(registered_files(root, docs))
    records = claims.record_paths({path: entry.kind for path, entry in found})
    for path, entry in found:
        text = (root / path).read_text(encoding="utf-8")
        prose = prose_text(text)
        if path == CHANGELOG:
            prose = released_blanked(prose)
        yield Page(path, text, prose, entry.kind, root=root, records=records), entry


def _unallowed(page: Page, rule: Rule, facts: Facts) -> list[str]:
    return [
        f"{page.name}:{page.line + f.line - 1}: {rule.id}: {f.message}"
        for f in rule.scan(page, facts)
    ]


def run(
    root: Path,
    facts: Facts,
    docs: tuple[DocEntry, ...] | None = None,
    rules: Iterable[Rule] | None = None,
    descriptions: Mapping[str, str] | None = None,
    strings: Iterable[Page] | None = None,
) -> list[str]:
    """Run every rule; return ``path:line: message`` problems.

    Args:
        root: The repository root.
        facts: The registry's facts (:func:`~.registry.build`).
        docs: The doc registry (default: *root*'s own, :func:`~.docs.for_repo`).
        rules: The rules to run (default :data:`RULES`, read at call time).
        descriptions: Tool name -> description (default: the live registration).
        strings: The ``pyeye.mcp`` string literals (default :func:`code_strings`).
    """
    # A rule whose facts are absent doesn't run (#1091); :func:`skipped` reports it.
    rules = tuple(r for r in (RULES if rules is None else rules) if not missing_facts(r, facts))
    entries = doc_registry.for_repo(root) if docs is None else docs
    problems = allow_problems(entries)
    # An audit reads the facts and nothing else (C19): no root, no files, no
    # imports, and a read-only view, so it can't change what other rules see.
    view = MappingProxyType(dict(facts))
    problems.extend(f"{rule.id}: {m}" for rule in rules if rule.audit for m in rule.audit(view))
    for page, entry in pages(root, entries):
        problems.extend(_page_problems(page, entry, rules, facts))
    if descriptions is None and any(r.descriptions for r in rules):
        descriptions = _tool_descriptions()
    tool_pages = [Page(f"tool:{n}", t, t, None) for n, t in sorted((descriptions or {}).items())]
    problems.extend(_code_problems(tool_pages, [r for r in rules if r.descriptions], facts))
    if strings is None and any(r.strings for r in rules):
        strings = code_strings()
    problems.extend(_code_problems(strings or (), [r for r in rules if r.strings], facts))
    return problems


def _page_problems(page: Page, entry: DocEntry, rules: Iterable[Rule], facts: Facts) -> list[str]:
    """A registered page's problems: each rule's findings beyond its allow-list."""
    problems = claims.record_problems(page.name, page.text) if page.kind == "record" else []
    for rule in rules:
        if page.kind not in rule.kinds:
            continue
        findings = rule.scan(page, facts)
        verdict = ratchet(entry, rule.id, [f.message for f in findings])
        if verdict is None:
            continue
        problems.append(f"{page.name}: {verdict}")
        allowed = Counter(entry.allow.get(rule.id, ()))
        for finding in findings:
            if allowed[finding.message]:
                allowed[finding.message] -= 1
            else:
                problems.append(f"{page.name}:{finding.line}: {rule.id}: {finding.message}")
    return problems


def _code_problems(surfaces: Iterable[Page], rules: list[Rule], facts: Facts) -> list[str]:
    """Every finding on a code surface: they have no allow-list."""
    return [p for page in surfaces for rule in rules for p in _unallowed(page, rule, facts)]
