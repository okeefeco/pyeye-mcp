"""Model lookups answer honestly: not found, ambiguous, or the one model (#627 slice B).

``get_model_schema`` and ``trace_model_inheritance`` take a ``model_name``. Before:

- a miss returned ``None`` (schema) or an *empty hierarchy* (trace), which reads as
  "measured, no parents or children";
- two models with the same name silently gave the first one.

Now both tools return one of three shapes, the ones the primitives use:

- **not found**: ``{found: False, model_name, reason: "unresolved", detail}``, the
  shared not-found shape (#626);
- **ambiguous**: ``{found: True, ambiguous: True, candidates: [...]}``, resolve's
  exact shape, each candidate a ``{handle, kind, scope, location}``;
- **found**: the existing answer plus ``found: True`` and the #627 ``handle``.

``model_name`` may also be a handle (canonical or a re-export alias), which is how
a caller picks one of the ambiguous candidates.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

import pyeye.project_manager as project_manager_module
from pyeye.config import ProjectConfig
from pyeye.mcp.server import register_plugin_tools
from pyeye.plugins.pydantic import PydanticPlugin
from pyeye.project_manager import ProjectManager
from pyeye.scope_utils import SmartScopeResolver
from tests.conformance.response_linter import lint_response

LOOKUP_TOOLS = ("get_model_schema", "trace_model_inheritance")

FILES = {
    "accounts/__init__.py": "from accounts.models import User\n",
    "accounts/models.py": """\
from pydantic import BaseModel


class User(BaseModel):
    email: str


# BaseModel listed explicitly: an indirect subclass isn't detected as a model yet
# (#664), and a child must be a detected model to be listed.
class Admin(User, BaseModel):
    level: int
""",
    "billing/__init__.py": "",
    "billing/models.py": """\
from pydantic import BaseModel


class User(BaseModel):
    card: str
""",
    "orders/__init__.py": "",
    "orders/models.py": """\
from pydantic import BaseModel


class Order(BaseModel):
    qty: int
""",
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


@pytest.fixture(autouse=True)
def isolated_manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[ProjectManager]:
    m = ProjectManager(max_projects=10)
    monkeypatch.setattr(project_manager_module, "_project_manager", m)
    yield m
    m.cleanup_all()


def _server(root: Path) -> MCPServer:
    s = MCPServer("lookup")
    register_plugin_tools(
        s, [PydanticPlugin(str(root))], SmartScopeResolver(ProjectConfig(str(root)))
    )
    return s


async def _call(s: MCPServer, tool: str, **args: Any) -> dict[str, Any]:
    result = await s.call_tool(tool, args)
    assert not result.is_error, result.content
    assert len(result.content) == 1
    payload = json.loads(result.content[0].text)
    assert isinstance(payload, dict)
    return payload


class TestNotFound:
    @pytest.mark.parametrize("tool", LOOKUP_TOOLS)
    async def test_miss_is_the_shared_not_found_shape(self, project: Path, tool: str) -> None:
        payload = await _call(_server(project), tool, model_name="Nope", scope="main")

        assert payload["found"] is False
        assert payload["model_name"] == "Nope"
        assert payload["reason"] == "unresolved"
        assert set(payload) == {"found", "model_name", "reason", "detail"}
        lint_response(payload, tool)

    @pytest.mark.parametrize("tool", LOOKUP_TOOLS)
    async def test_unresolvable_handle_is_not_found(self, project: Path, tool: str) -> None:
        payload = await _call(
            _server(project), tool, model_name="accounts.models.Ghost", scope="main"
        )

        assert payload["found"] is False
        assert payload["model_name"] == "accounts.models.Ghost"
        lint_response(payload, tool)


class TestAmbiguous:
    @pytest.mark.parametrize("tool", LOOKUP_TOOLS)
    async def test_same_name_twice_is_ambiguous_like_resolve(
        self, project: Path, tool: str
    ) -> None:
        payload = await _call(_server(project), tool, model_name="User", scope="main")

        assert payload["found"] is True
        assert payload["ambiguous"] is True
        assert set(payload) == {"found", "ambiguous", "candidates"}
        handles = [c["handle"] for c in payload["candidates"]]
        assert handles == ["accounts.models.User", "billing.models.User"]
        for candidate in payload["candidates"]:
            assert set(candidate) == {"handle", "kind", "scope", "location"}
            assert candidate["kind"] == "class"
            assert candidate["scope"] == "project"
            assert {"file", "line_start", "line_end"} <= set(candidate["location"])
        lint_response(payload, tool)


class TestFound:
    @pytest.mark.parametrize(
        ("model_name", "field"),
        [
            ("accounts.models.User", "email"),
            ("billing.models.User", "card"),
            ("accounts.User", "email"),  # re-export alias -> definition site
            ("Order", "qty"),  # a unique bare name still works
        ],
    )
    async def test_schema_by_handle_or_unique_name(
        self, project: Path, model_name: str, field: str
    ) -> None:
        payload = await _call(
            _server(project), "get_model_schema", model_name=model_name, scope="main"
        )

        assert payload["found"] is True
        assert "ambiguous" not in payload
        assert [f["name"] for f in payload["fields"]] == [field]
        assert payload["handle"].endswith(".User") or payload["handle"].endswith(".Order")
        lint_response(payload, "get_model_schema")

    async def test_alias_reports_the_definition_site_handle(self, project: Path) -> None:
        payload = await _call(
            _server(project), "get_model_schema", model_name="accounts.User", scope="main"
        )

        assert payload["handle"] == "accounts.models.User"

    async def test_trace_by_handle_lists_children(self, project: Path) -> None:
        payload = await _call(
            _server(project),
            "trace_model_inheritance",
            model_name="accounts.models.User",
            scope="main",
        )

        assert payload["found"] is True
        assert payload["handle"] == "accounts.models.User"
        assert [c["name"] for c in payload["children"]] == ["Admin"]
        assert payload["children"][0]["handle"] == "accounts.models.Admin"
        lint_response(payload, "trace_model_inheritance")

    async def test_existing_fields_are_unchanged(self, project: Path) -> None:
        plugin = PydanticPlugin(str(project))
        raw = json.loads(json.dumps(await plugin.get_model_schema("Order", scope="main")))

        payload = await _call(
            _server(project), "get_model_schema", model_name="Order", scope="main"
        )

        added = {"found", "handle", "location", "scope", "unresolved"}
        assert {k: v for k, v in payload.items() if k not in added} == raw


class TestEnvelope:
    @pytest.mark.parametrize("model_name", ["Nope", "User", "Order"])
    async def test_envelope_wraps_every_shape(self, project: Path, model_name: str) -> None:
        s = _server(project)
        bare = await _call(s, "get_model_schema", model_name=model_name, scope="main")
        wrapped = await _call(
            s, "get_model_schema", model_name=model_name, scope="main", envelope=True
        )

        assert wrapped["results"] == bare
        assert wrapped["scope"] == "main"
