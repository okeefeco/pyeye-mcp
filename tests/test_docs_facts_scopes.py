"""The ``scope`` extractor and the one scope grammar, :data:`SCOPE_FORMS` (#827).

Each fact is checked against the code read another way: the grammar against
the branches of :func:`resolve_scope_paths` (by AST) and against real calls, and
the default policy against :meth:`SmartScopeResolver.plugin_tool_default`.
"""

from __future__ import annotations

import ast
import inspect
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pyeye.docs_facts.extractors import scopes
from pyeye.docs_facts.facts import Fact, View
from pyeye.scope_utils import (
    PLUGIN_FALLBACK_SCOPE,
    SCOPE_FORMS,
    ScopeLayout,
    SmartScopeResolver,
    resolve_scope_paths,
)


def _branches() -> tuple[set[str], set[str]]:
    """The exact names and the prefixes ``resolve_scope_paths`` dispatches on."""
    tree = ast.parse(inspect.getsource(resolve_scope_paths))
    exact, prefixes = set(), set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "s"
            and isinstance(node.ops[0], ast.Eq)
            and isinstance(node.comparators[0], ast.Constant)
        ):
            exact.add(node.comparators[0].value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and isinstance(node.args[0], ast.Constant)
        ):
            prefixes.add(node.args[0].value)
    return exact, prefixes


def test_the_grammar_is_exactly_what_resolve_scope_paths_dispatches_on() -> None:
    exact, prefixes = _branches()
    assert {f.syntax for f in SCOPE_FORMS if f.prefix is None} == exact
    assert {f.prefix for f in SCOPE_FORMS if f.prefix is not None} == prefixes


@pytest.fixture
def layout(tmp_path: Path) -> ScopeLayout:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    ns = tmp_path / "ns"
    (ns / "acme").mkdir(parents=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    return ScopeLayout(
        project_path=tmp_path,
        packages=(pkg,),
        namespace_paths={"acme": (ns,)},
        standalone_paths=(scripts,),
    )


def _example(syntax: str, layout: ScopeLayout) -> str:
    """A concrete scope for *syntax*, filling its ``<...>`` part from *layout*."""
    if syntax == "namespace:<name>":
        return "namespace:acme"
    if syntax == "package:<path>":
        return f"package:{layout.packages[0].as_posix()}"
    assert "<" not in syntax, f"no example for {syntax!r}; add one"
    return syntax


@pytest.mark.parametrize("form", SCOPE_FORMS, ids=lambda f: f.name)
def test_every_form_resolves_without_a_warning(
    form, layout: ScopeLayout, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="pyeye.scope_utils"):
        paths = resolve_scope_paths(_example(form.syntax, layout), layout)
    assert paths, form.syntax
    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_a_form_outside_the_grammar_warns(
    layout: ScopeLayout, caplog: pytest.LogCaptureFixture
) -> None:
    """The check above would pass vacuously if unknown forms were silent."""
    with caplog.at_level(logging.WARNING, logger="pyeye.scope_utils"):
        assert resolve_scope_paths("namespaces", layout) == set()
    assert "Unknown scope specification" in caplog.text


def test_all_is_the_union_of_the_other_unparameterised_forms(layout: ScopeLayout) -> None:
    """What ``all``'s meaning says: main, every package and namespace, and standalone."""
    union = set()
    for scope in ("main", "packages", "standalone", "namespace:acme"):
        union |= resolve_scope_paths(scope, layout)
    assert resolve_scope_paths("all", layout) == union


def _resolver(config: dict) -> SmartScopeResolver:
    project_config = MagicMock()
    project_config.config = config
    return SmartScopeResolver(project_config)


def test_the_default_policy_is_what_plugin_tools_do() -> None:
    """``scope.default.plugin``: methods entry, else global, else the fallback (#559)."""
    tool = "find_pydantic_models"
    assert SmartScopeResolver().plugin_tool_default(tool) == PLUGIN_FALLBACK_SCOPE
    assert _resolver({"scope_defaults": {"global": "all"}}).plugin_tool_default(tool) == "all"
    both = {"scope_defaults": {"global": "all", "methods": {tool: "packages"}}}
    assert _resolver(both).plugin_tool_default(tool) == "packages"
    assert scopes.DEFAULT_ORDER == ("scope_defaults.methods.<tool name>", "scope_defaults.global")


def test_the_facts() -> None:
    items = {item.id: item for item in scopes.extract(Path("."))}
    forms = [f"scope.option.{form.name}" for form in SCOPE_FORMS]
    assert set(items) == {*forms, "scopes.options", "scopes.table", "scope.default.plugin"}
    main = items["scope.option.main"]
    assert isinstance(main, Fact)
    assert main.value == {"syntax": "main", "meaning": "the main project"}
    assert main.markdown == "`main`: the main project"
    options = items["scopes.options"]
    assert isinstance(options, View)
    assert options.members == tuple(forms)
    assert options.markdown.startswith("`main`, `packages`, ")
    default = items["scope.default.plugin"]
    assert isinstance(default, Fact)
    assert default.value == {"order": list(scopes.DEFAULT_ORDER), "fallback": "main"}
    assert default.markdown == (
        "`scope_defaults.methods.<tool name>`, else `scope_defaults.global`, else `main`"
    )
