"""Expected handles and scope across every primitive, in a multi-repo namespace (#667).

The scenario (``tests/fixtures/scenarios/multirepo_namespace``, see its README)
is three sibling repos contributing to one PEP 420 namespace, ``corp``, wired
into a main project from OUTSIDE its root by ``.pyeye.json``. ``corp.core``
(a ``src/`` layout) and ``corp.web`` come in through ``namespaces``;
``corp.tools`` through ``packages``. The main project's root is itself a
package (``app``).

These tests pin expected VALUES (handle, kind, scope), not just agreement
between tools. Configured namespaces and packages are scope ``project`` (#623
decision 7).

Guards three fixes this scenario found or pinned: #653 (inspect/outline/
expand/trace couldn't find symbols in a namespace repo outside the project
root; fixed by #623 slice 3), #668 (namespace paths kept ``..``, so namespace
files got invalid module names: imported_by dropped importers and a cross-repo
name collision resolved silently to one candidate; fixed by normalising config
paths, #676) and #669 (the subclasses edge scanned the main project only).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.resolve import resolve, resolve_at
from pyeye.mcp.operations.trace import trace
from pyeye.project_manager import ProjectManager

SCENARIO = Path(__file__).parents[1] / "fixtures" / "scenarios" / "multirepo_namespace"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A private copy of the whole scenario: .pyeye.json's ../ paths stay valid."""
    root = tmp_path_factory.mktemp("scenario").resolve() / SCENARIO.name
    shutil.copytree(SCENARIO, root)
    yield root


@pytest.fixture(scope="module")
def analyzer(workspace: Path) -> JediAnalyzer:
    """The main project's analyzer, configured from its .pyeye.json."""
    return ProjectManager().get_analyzer(str(workspace / "app"))


def _handles(result: dict[str, Any]) -> list[str]:
    return [stub["handle"] for stub in result.get("stubs") or []]


def _scopes(result: dict[str, Any]) -> dict[str, str]:
    return {stub["handle"]: stub.get("scope") for stub in result.get("stubs") or []}


# ---------------------------------------------------------------------------
# Symbols: every primitive reports the expected handle, kind and scope
# ---------------------------------------------------------------------------

#: identifier -> (canonical handle, kind). All are scope "project".
_SYMBOLS = {
    "corp": ("corp", "module"),
    "corp.core": ("corp.core", "module"),
    "corp.core.models": ("corp.core.models", "module"),
    "corp.core.models.Base": ("corp.core.models.Base", "class"),
    "corp.core.models.make": ("corp.core.models.make", "function"),
    "corp.tools.Base": ("corp.core.models.Base", "class"),  # re-export collapses
    "corp.tools.widgets.Widget": ("corp.tools.widgets.Widget", "class"),
    "corp.tools.widgets.Widget.to_json": ("corp.tools.widgets.Widget.to_json", "method"),
    "corp.tools.sub.helper": ("corp.tools.sub.helper", "module"),
    "corp.tools.sub.helper.shout": ("corp.tools.sub.helper.shout", "function"),
    "corp.web.views.render": ("corp.web.views.render", "function"),
    "corp.web.views.lazy_shout": ("corp.web.views.lazy_shout", "function"),
    "app.main.run": ("app.main.run", "function"),
}


@pytest.mark.parametrize(
    ("identifier", "handle", "kind"),
    [pytest.param(ident, *expected, id=ident) for ident, expected in _SYMBOLS.items()],
)
async def test_every_primitive_reports_the_expected_handle(
    analyzer: JediAnalyzer, identifier: str, handle: str, kind: str
) -> None:
    expected = {"handle": handle, "kind": kind, "scope": "project"}

    r = await resolve(identifier, analyzer)
    assert {k: r.get(k) for k in expected} == expected, f"resolve: {r}"

    i = await inspect(identifier, analyzer)
    assert {k: i.get(k) for k in expected} == expected, f"inspect: {i}"

    o = await outline(identifier, analyzer, max_depth=0)
    node = o.get("node") or {}
    assert {k: node.get(k) for k in expected} == expected, f"outline: {o}"

    e = await expand(identifier, "members", analyzer)
    assert e.get("found") and e.get("source") == handle, f"expand: {e}"

    t = await trace(identifier, ["members"], analyzer, max_depth=0)
    assert t["unresolved_roots"] == [], f"trace: {t}"
    assert t["nodes"][handle]["scope"] == "project"


#: (fixture-relative file, 1-based line, 0-based column) of a definition name
_POSITIONS = [
    pytest.param(
        "corp-core/src/corp/core/models.py",
        8,
        6,
        "corp.core.models.Base",
        id="src-layout-repo",
    ),
    pytest.param(
        "corp-tools/corp/tools/widgets.py", 14, 6, "corp.tools.widgets.Widget", id="packages-repo"
    ),
    pytest.param("corp-tools/corp/tools/sub/helper.py", 6, 4, "corp.tools.sub.helper.shout"),
    pytest.param("corp-web/corp/web/views.py", 16, 4, "corp.web.views.render", id="flat-repo"),
]


@pytest.mark.parametrize(("rel", "line", "column", "handle"), _POSITIONS)
async def test_resolve_at_in_each_repo(
    analyzer: JediAnalyzer, workspace: Path, rel: str, line: int, column: int, handle: str
) -> None:
    result = await resolve_at(str(workspace / rel), line, column, analyzer)
    assert (result.get("handle"), result.get("scope")) == (handle, "project"), result


async def test_cross_repo_name_collision_is_ambiguous(analyzer: JediAnalyzer) -> None:
    """``Shared`` is defined in two repos; resolve must not pick one silently."""
    result = await resolve("Shared", analyzer)
    assert result.get("ambiguous") is True, result
    assert {c["handle"] for c in result["candidates"]} == {
        "corp.core.models.Shared",
        "corp.tools.widgets.Shared",
    }


async def test_unique_bare_name_resolves_across_repos(analyzer: JediAnalyzer) -> None:
    result = await resolve("Widget", analyzer)
    assert (result.get("handle"), result.get("scope")) == ("corp.tools.widgets.Widget", "project")


@pytest.mark.parametrize(
    ("module", "stdlib"),
    [
        ("corp.core.models", "logging"),
        ("corp.tools.widgets", "json"),
        ("corp.tools.sub.helper", "textwrap"),
        ("corp.web.views", "pathlib"),
        ("app.main", "sys"),
    ],
)
async def test_each_repos_stdlib_import_stays_external(
    analyzer: JediAnalyzer, module: str, stdlib: str
) -> None:
    """Configuring a namespace mustn't pull the stdlib into project scope."""
    scopes = _scopes(await expand(module, "imports", analyzer))
    assert scopes.get(stdlib) == "external", scopes


# ---------------------------------------------------------------------------
# Edges across repos
# ---------------------------------------------------------------------------


async def test_namespace_submodules_span_all_three_repos(analyzer: JediAnalyzer) -> None:
    result = await expand("corp", "submodules", analyzer)
    assert set(_handles(result)) == {"corp.core", "corp.tools", "corp.web"}


async def test_namespace_submodules_are_all_project(analyzer: JediAnalyzer) -> None:
    result = await expand("corp", "submodules", analyzer)
    assert set(_scopes(result).values()) == {"project"}, _scopes(result)


async def test_cross_repo_superclass_is_project(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.tools.widgets.Widget", "superclasses", analyzer)
    assert _scopes(result) == {"corp.core.models.Base": "project"}


async def test_cross_repo_subclass(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.core.models.Base", "subclasses", analyzer)
    assert "corp.tools.widgets.Widget" in _handles(result)


async def test_calls_into_two_other_repos(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.web.views.render", "callees", analyzer)
    callees = set(_handles(result))
    assert {"corp.core.models.make", "corp.tools.sub.helper.shout"} <= callees, callees
    assert any(
        h.startswith(("corp.tools.widgets.Widget", "corp.core.models.Base")) for h in callees
    )


async def test_imported_by_spans_repos(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.core.models", "imported_by", analyzer)
    assert {"app.main", "corp.tools", "corp.tools.widgets", "corp.web.views"} <= set(
        _handles(result)
    )


async def test_type_checking_import_reaches_another_repo(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.tools.widgets", "imports", analyzer)
    assert "corp.web.views.Page" in _handles(result)
    assert "corp.core.models.Base" in _handles(result)


async def test_imports_of_namespace_symbols_are_project(analyzer: JediAnalyzer) -> None:
    result = await expand("app.main", "imports", analyzer)
    scopes = _scopes(result)
    assert {h: s for h, s in scopes.items() if h.startswith("corp.")} == {
        "corp.core.models.Base": "project",
        "corp.core.models.make": "project",
        "corp.tools.widgets.Widget": "project",
        "corp.web.views.render": "project",
    }
    assert scopes["sys"] == "external"


async def test_aliased_and_lazy_imports(analyzer: JediAnalyzer) -> None:
    """``import corp.tools.sub.helper as helper_alias`` is a module import;
    the lazy ``from corp.tools.sub import helper`` inside a function is not
    (#360), but it still makes corp.web.views a dependent (#619)."""
    imports = _handles(await expand("corp.web.views", "imports", analyzer))
    assert "corp.tools.sub.helper" in imports
    importers = _handles(await expand("corp.tools.sub.helper", "imported_by", analyzer))
    assert "corp.web.views" in importers


async def test_nested_module_members(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.tools.sub.helper", "members", analyzer)
    assert _handles(result) == ["corp.tools.sub.helper.shout"]


async def test_enclosing_scope_in_a_namespace_repo(analyzer: JediAnalyzer) -> None:
    result = await expand("corp.tools.widgets.Widget.to_json", "enclosing_scope", analyzer)
    assert _handles(result) == ["corp.tools.widgets.Widget"]


async def test_trace_import_closure_reaches_every_repo(analyzer: JediAnalyzer) -> None:
    result = await trace(
        "app.main",
        ["imports"],
        analyzer,
        max_depth=2,
        max_nodes=100,
        stop_when={"exclude_external": True},
    )
    assert result["unresolved_roots"] == []
    reached = set(result["nodes"])
    assert {
        "corp.core.models.Base",
        "corp.core.models.make",
        "corp.tools.widgets.Widget",
        "corp.web.views.render",
    } <= reached, reached
