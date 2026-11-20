"""Tool descriptions take their fact parts from the extractors (#827, #818 D9).

The slot filler (:mod:`pyeye.docs_facts.describe`) is tested on its own, and
then every registered tool description (core, admin and plugin) is checked:

- no slot token survives into it;
- its hand-written text doesn't hand-write a partial list of a guarded view;
- its ``Args`` section names only parameters its registered schema has, and
  every schema parameter is named there or in the plugin wrapper's note.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import re
import subprocess  # nosec B404 - runs this interpreter with a fixed argument list
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from mcp.server.mcpserver import MCPServer

from pyeye.docs_facts import describe
from pyeye.docs_facts.describe import SlotError, fill, hand_lists, unfilled
from pyeye.docs_facts.facts import Fact, view
from pyeye.docs_facts.registry import build
from pyeye.mcp import server as srv

_ROOT = Path(__file__).resolve().parents[1]

#: Parameters the plugin-tool wrapper adds; ``PLUGIN_PROJECT_PATH_NOTE`` documents them.
_WRAPPER_PARAMS = ("envelope", "project_path")


def _facts() -> dict[str, Any]:
    edge = Fact("edge.members", {"status": "implemented", "applies_to": ["class", "module"]}, "")
    callees = Fact("edge.callees", {"status": "implemented", "applies_to": ["function"]}, "")
    ceiling = Fact("ceiling.static_calls", {"meaning": "calls static analysis resolves"}, "")
    return {
        f.id: f
        for f in (
            edge,
            callees,
            ceiling,
            view("edges.implemented", [edge, callees], ""),
            view("ceilings.table", [ceiling], ""),
        )
    }


class TestFill:
    def test_list_is_the_default_form(self) -> None:
        assert fill("Edges: <<fact:edges.implemented>>.", _facts()) == (
            "Edges: ``members``, ``callees``."
        )

    def test_a_single_fact_renders_as_its_label(self) -> None:
        assert fill("<<fact:edge.members>>", _facts()) == "``members``"

    def test_bullets_take_the_slot_line_indentation(self) -> None:
        doc = "Ceilings:\n\n      <<fact:ceilings.table:bullets>>\n"
        facts = _facts()
        facts["ceiling.static_imports"] = Fact(
            "ceiling.static_imports", {"meaning": "import statements"}, ""
        )
        facts["ceilings.table"] = view(
            "ceilings.table", [facts["ceiling.static_calls"], facts["ceiling.static_imports"]], ""
        )
        assert fill(doc, facts) == (
            "Ceilings:\n\n"
            "      - ``static_calls``: calls static analysis resolves.\n"
            "      - ``static_imports``: import statements.\n"
        )

    def test_applies_to(self) -> None:
        assert fill("<<fact:edges.implemented:applies_to>>", _facts()) == (
            "``members`` → class, module; ``callees`` → function"
        )

    def test_tiers_list_each_tier_with_its_edges(self) -> None:
        """The determinism form (#452): ``- ``tier`` (``edge``, ...): meaning.``."""
        facts = _facts()
        tier = Fact(
            "determinism.goto", {"meaning": "goto targets", "edges": ["callees", "imports"]}, ""
        )
        facts[tier.id] = tier
        facts["determinism.table"] = view("determinism.table", [tier], "")
        assert fill("    <<fact:determinism.table:tiers>>", facts) == (
            "    - ``goto`` (``callees``, ``imports``): goto targets."
        )

    def test_literal_braces_are_untouched(self) -> None:
        doc = '{ "found": False, "edge": str }  <<fact:edge.members>>  {x}'
        assert fill(doc, _facts()) == '{ "found": False, "edge": str }  ``members``  {x}'

    @pytest.mark.parametrize(
        ("doc", "message"),
        [
            ("<<fact:edges.gone>>", "unknown fact 'edges.gone'"),
            ("<<fact:edges.implemented:table>>", "unknown form 'table'"),
            ("<<fact:edges.implemented:bullets>>", "has no meaning"),
            ("<<fact:ceilings.table:applies_to>>", "has no applies_to"),
            ("<<fact:edges.implemented:tiers>>", "is not a determinism tier"),
            ("<<fact:edges.implemented", "malformed slot"),
            ("<<fact:Edges Implemented>>", "malformed slot"),
        ],
    )
    def test_a_bad_slot_fails_loudly(self, doc: str, message: str) -> None:
        with pytest.raises(SlotError, match=message):
            fill(doc, _facts())

    @pytest.mark.parametrize(
        "doc",
        [
            "Ceilings: <<fact:ceilings.table:bullets>>",
            "    <<fact:ceilings.table:bullets>> and more",
        ],
    )
    def test_a_bullets_slot_must_be_on_its_own_line(self, doc: str) -> None:
        """Mid-line, its continuation lines would lose their indentation silently."""
        with pytest.raises(SlotError, match="on a line of its own"):
            fill(doc, _facts())

    def test_a_bullets_slot_at_column_zero_or_the_end_is_fine(self) -> None:
        assert fill("<<fact:ceilings.table:bullets>>", _facts()) == (
            "- ``static_calls``: calls static analysis resolves."
        )

    def test_unfilled_finds_whole_and_broken_tokens(self) -> None:
        assert unfilled("a <<fact:x.y>> b <<fact:z") == ["<<fact:x.y>>", "<<fact:z"]
        assert unfilled("plain << text >>") == []


class TestHandLists:
    """A partial hand list of a guarded view must be a slot instead."""

    def test_a_partial_list_is_reported(self) -> None:
        facts = describe.load_time_facts()
        doc = "Edges (``members``, ``callees``, ``imports``) are traversed."
        assert hand_lists(doc, facts) == [
            "edges.implemented: members, callees, imports in: "
            "'Edges (``members``, ``callees``, ``imports``) are traversed.'"
        ]

    def test_one_or_two_examples_are_fine(self) -> None:
        assert hand_lists("e.g. ``members`` or ``callees``", describe.load_time_facts()) == []

    def test_a_complete_list_with_prose_for_each_member_is_fine(self) -> None:
        facts = describe.load_time_facts()
        names = [describe.label(facts[i]) for i in facts["edges.implemented"].members]
        doc = "\n".join(f"- ``{name}``: what it does." for name in names)
        assert hand_lists(doc, facts) == []

    def test_slot_text_is_not_checked(self) -> None:
        assert hand_lists("Edges: <<fact:edges.implemented>>.", describe.load_time_facts()) == []

    def test_quoted_scope_forms_count(self) -> None:
        doc = '- "main": x\n- "all": y\n- "namespace:name": z'
        assert hand_lists(doc, describe.load_time_facts()) == [
            "scopes.options: main, namespace:<name>, all in: "
            '\'- "main": x - "all": y - "namespace:name": z\''
        ]


# --- every registered description -------------------------------------------


async def _list(server: MCPServer) -> list[Any]:
    return list(await server.list_tools())


class RegisteredTool(NamedTuple):
    """One registered tool, as a client sees it, plus its hand-written template."""

    name: str
    description: str
    template: str
    schema: dict[str, Any]
    plugin: bool


def _registered() -> list[RegisteredTool]:
    """Every registered tool: core, admin and plugin."""
    out = []
    admin = MCPServer("describe-admin")
    for func in srv.ADMIN_TOOLS:
        admin.tool()(func)
    for tool in asyncio.run(_list(srv.mcp)) + asyncio.run(_list(admin)):
        func = getattr(srv, tool.name)
        template = getattr(func, "__doc_template__", func.__doc__) or ""
        out.append(
            RegisteredTool(tool.name, tool.description or "", template, tool.input_schema, False)
        )
    for plugin_class in srv._PLUGIN_CLASSES:
        plugin = plugin_class(".")
        server = MCPServer(f"describe-{plugin.name()}")
        srv.register_plugin_tools(server, [plugin])
        funcs: dict[str, Callable[..., Any]] = plugin.register_tools()
        for tool in asyncio.run(_list(server)):
            template = (funcs[tool.name].__doc__ or "") + srv.PLUGIN_PROJECT_PATH_NOTE
            out.append(
                RegisteredTool(tool.name, tool.description or "", template, tool.input_schema, True)
            )
    return out


_TOOLS = _registered()
_IDS = [t.name for t in _TOOLS]


def test_every_tool_family_is_covered() -> None:
    """Guard against the checks below silently covering nothing."""
    names = set(_IDS)
    assert {"expand", "trace", "resolve", "get_performance_metrics", "find_flask_routes"} <= names
    assert {"find_pydantic_models", "find_django_models"} <= names


@pytest.mark.parametrize("tool", _TOOLS, ids=_IDS)
def test_no_slot_survives(tool: RegisteredTool) -> None:
    assert unfilled(tool.description) == [], tool.name


@pytest.mark.parametrize("tool", _TOOLS, ids=_IDS)
def test_no_hand_written_fact_list(tool: RegisteredTool) -> None:
    """The registry owns these lists; the description takes them through a slot (§5)."""
    problems = hand_lists(tool.template)
    assert not problems, f"{tool.name}: write these as <<fact:VIEW>> slots: {problems}"


def _documented_params(description: str) -> list[str] | None:
    """The parameter names in a Google-style ``Args:`` section, or ``None`` if it has none."""
    match = re.search(
        r"^(?P<i>[ \t]*)Args:\n(?P<body>(?:(?P=i)[ \t]+.*\n?|[ \t]*\n)*)", description, re.M
    )
    if match is None:
        return None
    lines = [line for line in match["body"].splitlines() if line.strip()]
    indent = min(len(line) - len(line.lstrip()) for line in lines)
    named = (re.match(rf" {{{indent}}}(\w+)(?: \([^)]*\))?:", line) for line in lines)
    return [m[1] for m in named if m]


@pytest.mark.parametrize("tool", _TOOLS, ids=_IDS)
def test_args_match_the_schema(tool: RegisteredTool) -> None:
    """A parameter is checked, not slotted: the docs name exactly the schema's (#827)."""
    params = list(tool.schema.get("properties", {}))
    documented = _documented_params(tool.description)
    if documented is None:
        assert params == [], f"{tool.name} has parameters {params} but no Args section"
        return
    assert [p for p in documented if p not in params] == [], f"{tool.name}: stale Args entries"
    # The plugin wrapper's parameters are documented once, in its shared note.
    exempt = set(_WRAPPER_PARAMS) if tool.plugin else set()
    missing = [p for p in params if p not in documented and p not in exempt]
    assert missing == [], f"{tool.name}: parameters missing from Args: {missing}"


def test_plugin_scope_docs_name_the_aliases() -> None:
    """The scope forms aren't the whole grammar: configured aliases expand first."""
    for tool in _TOOLS:
        if tool.plugin and "scope" in tool.schema.get("properties", {}):
            assert "``scope_aliases``" in tool.description, tool.name


def test_the_plugin_note_documents_every_wrapper_parameter() -> None:
    for param in _WRAPPER_PARAMS:
        assert f"``{param}``" in srv.PLUGIN_PROJECT_PATH_NOTE, param


# --- the load-time extractors -----------------------------------------------


@pytest.mark.parametrize("extractor", describe.LOAD_TIME_EXTRACTORS)
def test_load_time_extractors_never_read_the_server(extractor: str) -> None:
    """The server fills its descriptions from them while it loads, so they can't use it."""
    source = _ROOT / "src" / "pyeye" / "docs_facts" / "extractors" / f"{extractor}.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not [m for m in imported if m.endswith(("mcp.server", "mcp_surface"))], imported


def test_load_time_facts_are_the_registry_facts() -> None:
    """A slot shows exactly what the docs show: one fact layer (#818 Goal 1)."""
    registry = build(_ROOT)
    for fact_id, item in describe.load_time_facts().items():
        assert registry[fact_id] == item, fact_id


# --- #851: the load-time facts come from code, never from repo files ----------


@pytest.mark.parametrize("extractor", describe.LOAD_TIME_EXTRACTORS)
def test_load_time_extractors_take_no_root(extractor: str) -> None:
    """``extract_code()`` has no root to read files from, by construction."""
    module = importlib.import_module(f"pyeye.docs_facts.extractors.{extractor}")
    assert list(inspect.signature(module.extract_code).parameters) == []


def test_load_time_facts_need_no_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """From an empty directory, as in a wheel install with the server started anywhere."""
    monkeypatch.chdir(tmp_path)
    describe.load_time_facts.cache_clear()
    try:
        facts = describe.load_time_facts()
    finally:
        describe.load_time_facts.cache_clear()
    assert "edges.implemented" in facts
    assert "scopes.options" in facts


def test_the_server_imports_outside_the_repo(tmp_path: Path) -> None:
    """``import pyeye.mcp.server`` from an empty directory, isolated (``-I``) (#851).

    The editable install still maps ``pyeye`` to ``src/``, but nothing relative
    to the repo is reachable: this failed with FileNotFoundError for
    ``tests/conformance/response_linter.py`` before #851. CI also imports a
    built wheel this way (``type-check`` job).
    """
    result = subprocess.run(  # nosec B603 - this interpreter, fixed arguments
        [sys.executable, "-I", "-c", "import pyeye.mcp.server"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
