"""Prose rules: phrasing the docs must not use, or must carry (#818, #825).

A fact check compares a documented value with an extracted one. A prose rule
can't: it requires or forbids *phrasing* that no extractor produces, such as
calling an unresolved handle one that "doesn't exist" (#568). Each rule here runs
over every registered doc of the kinds it applies to (:data:`~.docs.DOCS`, never
a list of its own) and over the live MCP tool descriptions, which are the docs a
model reads.

The text inside fact blocks is skipped: it is generated from the code, so it is
the fact checks' business, not a rule's.

**The ratchet.** Today's violations are recorded per page in
:attr:`~.docs.DocEntry.allow` (rule ID -> count of violating lines). The count
can only shrink. ``check`` fails when a page has more violating lines than its
entry allows, and also when it has fewer and the entry wasn't lowered, so a fix
always lowers the count in the same PR. Tool descriptions have no allow-list:
they must be clean.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import (
    binding,
    docs as doc_registry,
)
from .docs import DocEntry, Kind, registered_files
from .facts import Bindable, Fact

Facts = Mapping[str, Bindable]

# ---------------------------------------------------------------------------
# Rule IDs
# ---------------------------------------------------------------------------

STATIC_CEILING = "static-ceiling"
ABSENCE_PROSE = "absence-prose"
EDGE_COUNTS_PROSE = "edge-counts-prose"
HONEST_CLAIMS = "honest-claims"
#: Owned by #826 (removed names in prose); registered here so its allow-list
#: entries are valid keys.
REMOVED_NAME = "removed-name"
ENV_NAME = "env-name"
SERVER_COMMAND = "server-command"

#: Every rule ID a :attr:`~.docs.DocEntry.allow` key may name. A key outside this
#: set is a typo that would silently allow nothing, so it fails.
RULE_IDS: frozenset[str] = frozenset(
    {
        STATIC_CEILING,
        ABSENCE_PROSE,
        EDGE_COUNTS_PROSE,
        HONEST_CLAIMS,
        REMOVED_NAME,
        ENV_NAME,
        SERVER_COMMAND,
    }
)

#: Kinds the phrasing rules apply to. History pages must be free to quote what
#: was once wrong (C1); generated reference pages hold no hand-written prose.
_LIVE: frozenset[Kind] = frozenset({"prose", "skill"})


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
    """One violation: the 1-based line it starts on and what's wrong."""

    line: int
    message: str


@dataclass(frozen=True)
class Page:
    """A surface a rule scans.

    Attributes:
        name: A registered path, or ``tool:<name>`` for a tool description.
        text: The full text, fact blocks included.
        prose: The text with fact-block content blanked (:func:`prose_text`).
        kind: The page's registry kind, or ``None`` for a tool description.
    """

    name: str
    text: str
    prose: str
    kind: Kind | None


@dataclass(frozen=True)
class Rule:
    """A named prose rule.

    Attributes:
        id: The rule ID, a key of :attr:`~.docs.DocEntry.allow`.
        kinds: The registry kinds it scans.
        descriptions: Whether it also scans the live tool descriptions.
        scan: Returns the page's violations; takes the page and the facts.
    """

    id: str
    kinds: frozenset[Kind]
    descriptions: bool
    scan: Callable[[Page, Facts], list[Finding]]


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
            snippet = flat if len(flat) <= 160 else flat[:157] + "..."
            found.append(Finding(line, f"unmeasured edge {edge!r} shown in edge_counts: {snippet}"))
    return found


# ---------------------------------------------------------------------------
# #417: the static-surface ceiling caveat
# ---------------------------------------------------------------------------

#: The one phrase every surface that presents a static structural edge carries.
CEILING_MARKER = "Static-surface ceiling"

#: The structural edges whose answer is bounded by what is written in source.
_STATIC_STRUCTURAL = ("members", "subclasses")
_NAMED_EDGE = re.compile(r"[\"`](" + "|".join(_STATIC_STRUCTURAL) + r")[\"`]")


def missing_ceiling(page: Page, facts: Facts) -> list[Finding]:  # noqa: ARG001
    """The ceiling marker is missing from a surface that presents a static edge (#417).

    A registered page presents the edges when it binds ``edges.implemented`` or
    ``edges.table``; a tool description, when it names ``members`` or
    ``subclasses`` as an edge.
    """
    if CEILING_MARKER in page.text:
        return []
    if page.kind is None:
        match = _NAMED_EDGE.search(page.text)
        if match is None:
            return []
        line = page.text.count("\n", 0, match.start()) + 1
        return [Finding(line, f"names the {match.group(1)!r} edge without {CEILING_MARKER!r}")]
    blocks, _ = binding.parse(page.text)
    for block in blocks:
        if block.fact_id in {"edges.implemented", "edges.table"}:
            return [Finding(block.line, f"binds {block.fact_id} without {CEILING_MARKER!r}")]
    return []


# ---------------------------------------------------------------------------
# #556 and #553: env vars and server commands named in the docs exist
# ---------------------------------------------------------------------------


def _removed_names() -> frozenset[str]:
    """Names that are gone: a live page may name one only beside the word "removed".

    Empty until #826, which reads them from ``docs/facts/removed.json`` (C2).
    The wrong names the old checks caught (``PYEYE_PACKAGES``, ``uv run pyeye``,
    ``mcp dev`` and the like) were never read or never worked, so they were
    never *removed*. They always fail, and "removed" beside them would be a
    false claim (D12).
    """
    return frozenset()


# Includes lowercase suffixes, e.g. the once-documented ``PYEYE_NAMESPACE_company``.
_ENV = re.compile(r"\bPYEYE_[A-Za-z][A-Za-z0-9_]*[A-Za-z0-9]")


def _lines(text: str) -> Iterator[tuple[int, str]]:
    yield from enumerate(text.splitlines(), 1)


def _says_removed(line: str) -> bool:
    return "removed" in line.lower()


def env_name_claims(text: str, facts: Facts) -> list[Finding]:
    """Each ``PYEYE_*`` name that doesn't take effect, on its line (#556, #628).

    A name passes when pyeye reads *and uses* it (status ``live``), or when it is
    deprecated and the line says so. A loaded-but-unused variable fails: the docs
    would promise a knob that does nothing.
    """
    removed = _removed_names()
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


def server_command_claims(text: str, facts: Facts) -> list[Finding]:
    """Each documented way to start the server that doesn't work (#553).

    The ways that work are the ``cli.*`` facts: the console scripts and
    ``python -m pyeye.mcp``. The server module can't run as a file (relative
    imports), and ``mcp dev`` can't load it.
    """
    removed = _removed_names()
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

RULES: tuple[Rule, ...] = (
    Rule(STATIC_CEILING, _LIVE, True, missing_ceiling),
    Rule(ABSENCE_PROSE, _LIVE, True, lambda page, _facts: absence_claims(page.prose)),
    Rule(
        EDGE_COUNTS_PROSE,
        _LIVE,
        True,
        lambda page, facts: edge_counts_claims(page.prose, _unmeasured(facts)),
    ),
    Rule(ENV_NAME, _LIVE, False, lambda page, facts: env_name_claims(page.prose, facts)),
    Rule(
        SERVER_COMMAND, _LIVE, False, lambda page, facts: server_command_claims(page.prose, facts)
    ),
)


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


def ratchet(entry: DocEntry, rule_id: str, found: int) -> str | None:
    """Compare *found* violating lines with what *entry* allows for *rule_id*.

    Returns:
        ``None`` when they are equal, or the problem: more lines than allowed (a
        new violation), or fewer (a fix that didn't lower the count).
    """
    allowed = entry.allow.get(rule_id, 0)
    if found > allowed:
        return f"{rule_id}: {found} violating line(s), {allowed} allowed"
    if found < allowed:
        return (
            f"{rule_id}: {found} violating line(s) but {allowed} allowed; lower its "
            f"count in DOCS (src/pyeye/docs_facts/docs.py) to {found}"
        )
    return None


def allow_problems(docs: Iterable[DocEntry]) -> list[str]:
    """Allow-list keys that name no rule, or counts that aren't positive."""
    problems: list[str] = []
    for entry in docs:
        for rule_id, count in sorted(entry.allow.items()):
            if rule_id not in RULE_IDS:
                problems.append(
                    f"{entry.path}: allow names unknown rule {rule_id!r} "
                    f"(known: {', '.join(sorted(RULE_IDS))})"
                )
            elif count < 1:
                problems.append(f"{entry.path}: allow[{rule_id!r}] is {count}; remove the key")
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


def pages(root: Path, docs: tuple[DocEntry, ...] | None = None) -> Iterator[tuple[Page, DocEntry]]:
    """Every registered doc as a :class:`Page`, with its entry."""
    for path, entry in registered_files(root, docs):
        text = (root / path).read_text(encoding="utf-8")
        yield Page(path, text, prose_text(text), entry.kind), entry


def run(
    root: Path,
    facts: Facts,
    docs: tuple[DocEntry, ...] | None = None,
    rules: Iterable[Rule] | None = None,
    descriptions: Mapping[str, str] | None = None,
) -> list[str]:
    """Run every rule; return ``path:line: message`` problems.

    Args:
        root: The repository root.
        facts: The registry's facts (:func:`~.registry.build`).
        docs: The doc registry (default :data:`~.docs.DOCS`, read at call time).
        rules: The rules to run (default :data:`RULES`, read at call time).
        descriptions: Tool name -> description (default: the live registration).
    """
    rules = RULES if rules is None else tuple(rules)
    entries = doc_registry.DOCS if docs is None else docs
    problems = allow_problems(entries)
    for page, entry in pages(root, entries):
        for rule in rules:
            if page.kind not in rule.kinds:
                continue
            findings = rule.scan(page, facts)
            lines = sorted({f.line for f in findings})
            verdict = ratchet(entry, rule.id, len(lines))
            if verdict is None:
                continue
            problems.append(f"{page.name}: {verdict}")
            if len(lines) > entry.allow.get(rule.id, 0):
                problems.extend(f"{page.name}:{f.line}: {rule.id}: {f.message}" for f in findings)
    if descriptions is None and any(r.descriptions for r in rules):
        descriptions = _tool_descriptions()
    for name, text in sorted((descriptions or {}).items()):
        page = Page(f"tool:{name}", text, text, None)
        for rule in rules:
            if rule.descriptions:
                problems.extend(
                    f"{page.name}:{f.line}: {rule.id}: {f.message}" for f in rule.scan(page, facts)
                )
    return problems
