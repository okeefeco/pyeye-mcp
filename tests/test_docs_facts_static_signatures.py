"""Signatures, decorators and returns read from pyeye's source (#1098 PR B, ruling C19).

The MCP tool surface was read from the live registration. These tests cover the
static reader that replaces it, and the server declaration it reads (the
parameters every plugin tool gains), which must match what the server builds.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from pyeye.docs_facts import static_signatures as sig
from pyeye.docs_facts.facts import ExtractionError

ROOT = Path(__file__).resolve().parents[1]


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / "src" / "pyeye" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


TOOLS = '''
from typing import Any, Literal, Optional
from .types import Scope

ADMIN = (metrics, diagnostics)


@mcp.tool()
@other
async def resolve(identifier: str, project_path: str = ".", max_candidates: int | None = 50):
    """Resolve."""


@mcp.tool()
async def expand(handle: str, edge: str, scope: Scope = "main", data: dict[str, Any] | None = None,
                 *, flag: bool = False, mode: Literal["a", "b"] = "a") -> dict:
    ...


def helper(x: int) -> int: ...


class Plugin:
    def name(self) -> str:
        return "Thing"

    def register_tools(self) -> dict:
        return {"find_things": self.find, "list_things": self.listing}

    async def find(self, scope: Scope = "main", limit: Optional[int] = None) -> list:
        ...

    def listing(self, scope: Scope = "all", names: list[str] | None = None) -> list:
        ...
'''
TYPES = "Scope = str | list[str]\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _repo(tmp_path, {"__init__.py": "", "tools.py": TOOLS, "types.py": TYPES})


class TestSignature:
    def test_reads_parameters_in_order_with_defaults(self, repo: Path) -> None:
        params = sig.signature(repo, "pyeye.tools", "resolve")

        assert [(p.name, p.required, p.default) for p in params] == [
            ("identifier", True, None),
            ("project_path", False, "."),
            ("max_candidates", False, 50),
        ]

    def test_keyword_only_parameters_follow(self, repo: Path) -> None:
        names = [p.name for p in sig.signature(repo, "pyeye.tools", "expand")]

        assert names == ["handle", "edge", "scope", "data", "flag", "mode"]

    def test_a_method_drops_self(self, repo: Path) -> None:
        params = sig.signature(repo, "pyeye.tools", "Plugin.find")

        assert [p.name for p in params] == ["scope", "limit"]

    def test_a_missing_function_says_so(self, repo: Path) -> None:
        with pytest.raises(ExtractionError, match="no function"):
            sig.signature(repo, "pyeye.tools", "missing")

    def test_a_default_it_would_have_to_run_is_refused(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "def f(x: int = compute()): ...\n"})

        with pytest.raises(ExtractionError, match="m.py:1"):
            sig.signature(root, "pyeye.m", "f")


class TestTypeStrings:
    @pytest.mark.parametrize(
        ("function", "expected"),
        [
            ("resolve", ["str", "str", "int | None"]),
            ("expand", ["str", "str", "str | list[str]", "dict | None", "bool", "str"]),
        ],
    )
    def test_renders_like_the_schema(self, repo: Path, function: str, expected: list[str]) -> None:
        params = sig.signature(repo, "pyeye.tools", function)

        assert [sig.type_string(repo, "pyeye.tools", p.annotation) for p in params] == expected

    def test_optional_and_nested_generics(self, repo: Path) -> None:
        params = sig.signature(repo, "pyeye.tools", "Plugin.listing")
        rendered = [sig.type_string(repo, "pyeye.tools", p.annotation) for p in params]

        assert rendered == ["str | list[str]", "list[str] | None"]
        optional = sig.signature(repo, "pyeye.tools", "Plugin.find")[1].annotation
        assert sig.type_string(repo, "pyeye.tools", optional) == "int | None"

    def test_an_alias_is_followed_into_its_module(self, repo: Path) -> None:
        scope = sig.signature(repo, "pyeye.tools", "expand")[2].annotation

        assert sig.type_string(repo, "pyeye.tools", scope) == "str | list[str]"

    def test_an_unknown_type_is_refused(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "def f(x: Mystery): ...\n"})
        annotation = sig.signature(root, "pyeye.m", "f")[0].annotation

        with pytest.raises(ExtractionError, match="Mystery"):
            sig.type_string(root, "pyeye.m", annotation)


class TestModuleReads:
    def test_decorated_functions(self, repo: Path) -> None:
        assert sig.decorated(repo, "pyeye.tools", "mcp.tool()") == ["resolve", "expand"]

    def test_tuple_names(self, repo: Path) -> None:
        assert sig.tuple_names(repo, "pyeye.tools", "ADMIN") == ["metrics", "diagnostics"]

    def test_a_literal_return(self, repo: Path) -> None:
        assert sig.returned_literal(repo, "pyeye.tools", "Plugin.name") == "Thing"

    def test_a_returned_dict_of_methods(self, repo: Path) -> None:
        assert sig.returned_method_dict(repo, "pyeye.tools", "Plugin.register_tools") == [
            ("find_things", "find"),
            ("list_things", "listing"),
        ]

    def test_where_a_name_was_imported_from(self, repo: Path) -> None:
        assert sig.imported_from(repo, "pyeye.tools", "Scope") == ("pyeye.types", "Scope")

    def test_a_return_that_isnt_a_literal_is_refused(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"m.py": "class C:\n    def name(self):\n        return make()\n"})

        with pytest.raises(ExtractionError, match="m.py:3"):
            sig.returned_literal(root, "pyeye.m", "C.name")


class TestThePluginToolDeclaration:
    """The parameters every plugin tool gains are DECLARED, so they can be read statically."""

    def test_the_declaration_reads_statically(self) -> None:
        extras = sig.declared_params(ROOT, "pyeye.mcp.server", "PLUGIN_TOOL_EXTRA_PARAMS")

        assert [
            (name, sig.type_string(ROOT, "pyeye.mcp.server", ann), default)
            for name, ann, default in extras
        ] == [
            ("envelope", "bool", False),
            ("project_path", "str | None", None),
        ]

    def test_the_server_builds_its_wrapper_from_the_declaration(self) -> None:
        """The runtime wrapper's appended parameters are exactly the declared ones."""
        from pyeye.mcp import server as srv
        from pyeye.plugins.pydantic import PydanticPlugin
        from pyeye.scope_utils import SmartScopeResolver

        plugin = PydanticPlugin(".")
        wrapped = srv._plugin_tool(
            "find_pydantic_models", plugin.find_models, plugin, SmartScopeResolver()
        )
        params = list(inspect.signature(wrapped).parameters.values())
        declared = [name for name, _, _ in srv.PLUGIN_TOOL_EXTRA_PARAMS]

        assert [p.name for p in params[-len(declared) :]] == declared
        assert [p.default for p in params[-len(declared) :]] == [
            default for _, _, default in srv.PLUGIN_TOOL_EXTRA_PARAMS
        ]
        scope = next(p for p in params if p.name == "scope")
        assert scope.default is None
