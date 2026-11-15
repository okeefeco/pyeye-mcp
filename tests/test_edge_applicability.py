"""One edge-applicability table (#626 slice B).

``edges.EDGE_APPLIES_TO`` is the only place that says which kinds an edge
applies to. Before #626 that was decided inline in each resolver, with two
policies: ``imports``/``imported_by`` returned ``None`` (unsupported), while the
other edges returned a measured ``[]`` for a wrong kind. And ``submodules`` ran
for a non-module symbol defined in a package ``__init__``, inventing handles
such as ``pkg.__all__.core`` from the package directory.

These tests pin the table's shape, that no reader or resolver re-derives the
kind gate inline, and the user-facing answer for a wrong kind.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.kinds import KINDS
from pyeye.mcp.operations.edges import (
    _IMPLEMENTED_EDGES,
    EDGE_APPLIES_TO,
    EDGE_RESOLVERS,
    STATUS_NOT_APPLICABLE,
    edge_status,
    not_applicable_detail,
)
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from tests.conformance.response_linter import lint_response

_OPERATIONS = Path(__file__).resolve().parents[1] / "src" / "pyeye" / "mcp" / "operations"
_FIXTURES = Path(__file__).parent / "fixtures"


def test_table_covers_exactly_the_implemented_edges() -> None:
    assert set(EDGE_APPLIES_TO) == set(EDGE_RESOLVERS) == set(_IMPLEMENTED_EDGES)


def test_table_uses_only_the_kind_vocabulary() -> None:
    for edge, kinds in EDGE_APPLIES_TO.items():
        assert kinds, edge
        assert kinds <= KINDS, (edge, kinds - KINDS)


def test_the_table() -> None:
    """The decided applicability, written out so a change is deliberate."""
    assert {
        "members": {"class", "module"},
        "callees": {"function", "method"},
        "imported_by": {"module"},
        "imports": {"module"},
        "subclasses": {"class"},
        "superclasses": {"class"},
        "submodules": {"module"},
        "enclosing_scope": KINDS - {"module"},
        "re_exports": KINDS - {"module"},  # a module is re-exported as itself (#393)
    } == EDGE_APPLIES_TO


def test_not_applicable_is_not_an_edge_status() -> None:
    """It depends on the handle, so edge_status (edge-only) never returns it."""
    for edge in [*EDGE_APPLIES_TO, "callers", "nonsense"]:
        assert edge_status(edge) != STATUS_NOT_APPLICABLE


def test_detail_names_the_kind_and_the_applicable_kinds() -> None:
    detail = not_applicable_detail("imports", "class")
    assert "class handle" in detail and "module" in detail


def _calls_normalise_kind(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.name}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"normalise_kind", "normalise_kind_from_name"}
    ]


def test_no_inline_kind_gates_in_edges_or_expand() -> None:
    """Kind is derived once, in ``edges.edge_kind``; nobody re-derives it.

    The 7 inline ``normalise_kind(getattr(name, "type", None))`` copies in
    edges.py and the 2 in expand.py were the drift #626 removed.
    """
    edges_calls = _calls_normalise_kind(_OPERATIONS / "edges.py")
    assert len(edges_calls) == 1, f"edges.py: only edge_kind() derives the kind: {edges_calls}"
    assert _calls_normalise_kind(_OPERATIONS / "expand.py") == []
    assert _calls_normalise_kind(_OPERATIONS / "trace.py") == []


@pytest.fixture(scope="module")
def resolve_project() -> JediAnalyzer:
    return JediAnalyzer(str(_FIXTURES / "resolve_project"))


@pytest.mark.parametrize(
    ("handle", "edge", "kind"),
    [
        ("mypackage._core.widgets.make_widget", "members", "function"),
        ("mypackage._core.widgets.Widget", "callees", "class"),
        ("mypackage._core.widgets.Widget", "imports", "class"),
        ("mypackage._core.widgets.make_widget", "imported_by", "function"),
        ("mypackage._core.widgets", "subclasses", "module"),
        ("mypackage._core.widgets.make_widget", "superclasses", "function"),
        ("mypackage._core.widgets", "enclosing_scope", "module"),
        ("mypackage._core.widgets.Widget", "submodules", "class"),
    ],
)
async def test_every_wrong_kind_is_not_applicable(
    resolve_project: JediAnalyzer, handle: str, edge: str, kind: str
) -> None:
    result = await expand(handle, edge, resolve_project)
    assert result["found"] is True
    assert result["unsupported"] is True
    assert result["reason"] == "not_applicable"
    assert result["detail"] == not_applicable_detail(edge, kind)
    assert "stubs" not in result
    lint_response(result, "expand")


async def test_submodules_never_invents_handles_from_an_init_symbol(
    resolve_project: JediAnalyzer,
) -> None:
    """``pkg.__all__`` lives in ``pkg/__init__.py``; it is not the package.

    Before #626, ``expand("mypackage.__all__", "submodules")`` enumerated the
    package directory and returned ``mypackage.__all__._core`` and friends,
    handles that resolve to nothing.
    """
    result = await expand("mypackage.__all__", "submodules", resolve_project)
    assert result["reason"] == "not_applicable"
    assert "stubs" not in result

    package = await expand("mypackage", "submodules", resolve_project)
    assert any(stub["handle"] == "mypackage._core" for stub in package["stubs"])


async def test_inspect_counts_only_applicable_edges(resolve_project: JediAnalyzer) -> None:
    function = await inspect("mypackage._core.widgets.make_widget", resolve_project)
    assert function["edge_counts"] == {}
    cls = await inspect("mypackage._core.widgets.Widget", resolve_project)
    assert set(cls["edge_counts"]) == {"members", "superclasses"}
