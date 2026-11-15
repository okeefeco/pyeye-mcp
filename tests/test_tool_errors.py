"""One error channel for MCP calls that can't run (#626 slice C).

A lookup that ran answers with a response (found / not-found / unsupported).
A call that couldn't run (a bad argument, a missing project) is an MCP tool
error that tells the agent what to fix. A genuine pyeye bug stays a loud crash.

Before #626 slice C, a caller error reached the SDK as an unexpected
exception: the client got only ``"Error executing tool <name>"`` (the SDK keeps
a crash's text on the server), and the server logged a traceback for a typo.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from pyeye.exceptions import (
    AnalysisError,
    ConfigurationError,
    FileAccessError,
    ProjectNotFoundError,
    ValidationError,
)
from pyeye.mcp.tool_errors import CALLER_ERRORS, WRAPPED_ATTR, tool_error_message, tool_errors

server = importlib.import_module("pyeye.mcp.server")

#: Tools that never touch the analyzers and validate nothing.
NOT_WRAPPED = frozenset({"get_performance_metrics", "get_connection_diagnostics"})


# ---------------------------------------------------------------------------
# The decorator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        ValidationError("Invalid line number: must be positive", parameter="line", value="0"),
        ProjectNotFoundError("/no/such/project"),
        ConfigurationError("Bad config"),
        FileAccessError("Cannot read", file_path="x.py", operation="read"),
    ],
    ids=lambda e: type(e).__name__,
)
async def test_caller_errors_become_tool_errors_with_their_message(error: Exception) -> None:
    @tool_errors
    async def tool() -> None:
        raise error

    with pytest.raises(ToolError) as excinfo:
        await tool()
    assert not isinstance(excinfo.value, UnexpectedToolError)
    assert str(excinfo.value) == tool_error_message(error)
    assert str(excinfo.value).startswith(f"{type(error).__name__}: ")
    assert excinfo.value.__cause__ is error


def test_message_names_the_parameter() -> None:
    error = ValidationError("Invalid line number", parameter="line", value="0")
    assert (
        tool_error_message(error)
        == "ValidationError: Invalid line number (parameter=line, value=0)"
    )


@pytest.mark.parametrize("error", [RuntimeError("bug"), AnalysisError("internal")])
async def test_other_exceptions_pass_through_unchanged(error: Exception) -> None:
    @tool_errors
    async def tool() -> None:
        raise error

    with pytest.raises(type(error)) as excinfo:
        await tool()
    assert excinfo.value is error


def test_sync_tools_are_wrapped_too() -> None:
    @tool_errors
    def tool(x: int) -> int:
        if x < 0:
            raise ValidationError("negative", parameter="x", value=str(x))
        return x

    assert tool(2) == 2
    with pytest.raises(ToolError, match=r"^ValidationError: negative"):
        tool(-1)


def test_signature_and_marker_are_kept() -> None:
    async def tool(handle: str, project_path: str = ".") -> dict[str, Any]:  # noqa: ARG001
        """Doc."""
        return {}

    wrapped = tool_errors(tool)
    assert inspect.signature(wrapped) == inspect.signature(tool)
    assert wrapped.__doc__ == "Doc."
    assert getattr(wrapped, WRAPPED_ATTR) is True
    assert inspect.iscoroutinefunction(wrapped)


def test_caller_errors_are_the_documented_set() -> None:
    assert set(CALLER_ERRORS) == {
        ValidationError,
        ProjectNotFoundError,
        ConfigurationError,
        FileAccessError,
    }


# ---------------------------------------------------------------------------
# Wiring: every analyzer tool is wrapped, outermost
# ---------------------------------------------------------------------------


def _is_wrapped(fn: Any) -> bool:
    while fn is not None:
        if getattr(fn, WRAPPED_ATTR, False):
            return True
        fn = getattr(fn, "__wrapped__", None)
    return False


def test_every_registered_tool_reports_caller_errors() -> None:
    tools = server.mcp._tool_manager._tools
    unwrapped = sorted(
        name for name, tool in tools.items() if name not in NOT_WRAPPED and not _is_wrapped(tool.fn)
    )
    assert not unwrapped, (
        f"MCP tools without @tool_errors: {unwrapped}. Add @tool_errors (from "
        "pyeye.mcp.tool_errors) directly under @mcp.tool(), outermost, so a bad argument "
        "or a missing project reaches the client as a tool error that says what to fix, "
        "not as an unexpected crash (#626)."
    )


def test_tool_errors_is_outermost_on_core_tools() -> None:
    """Outside @validate_mcp_inputs, so argument validation is caught too."""
    for name in ("resolve", "resolve_at", "inspect", "outline", "expand", "trace"):
        fn = server.mcp._tool_manager._tools[name].fn
        assert getattr(fn, WRAPPED_ATTR, False), f"{name}: tool_errors is not the outermost wrapper"


async def test_plugin_tools_are_wrapped_outermost() -> None:
    from mcp.server.mcpserver import MCPServer

    class FakePlugin:
        def name(self) -> str:
            return "fake"

        def register_tools(self) -> dict[str, Any]:
            async def find_things(scope: str = "main") -> dict[str, Any]:  # noqa: ARG001
                raise ConfigurationError("plugin config is unusable")

            return {"find_things": find_things}

        def describe_scope(self, scope: str) -> dict[str, Any]:  # noqa: ARG002
            return {}

    fresh = MCPServer("test")
    server.register_plugin_tools(fresh, [FakePlugin()])  # type: ignore[list-item]
    tool = fresh._tool_manager._tools["find_things"]
    assert getattr(tool.fn, WRAPPED_ATTR, False)
    with pytest.raises(ToolError, match="^Error executing tool find_things: ConfigurationError"):
        await fresh.call_tool("find_things", {"scope": "all"})


# ---------------------------------------------------------------------------
# Through the real MCP path
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text("class Thing:\n    pass\n", encoding="utf-8")
    return tmp_path


async def _call(name: str, arguments: dict[str, Any]) -> Exception:
    with pytest.raises(ToolError) as excinfo:
        await server.mcp.call_tool(name, arguments)
    return excinfo.value


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("resolve_at", {"file": "pkg/mod.py", "line": 0, "column": 0}, "parameter=line"),
        ("resolve_at", {"file": "pkg/mod.py", "line": 1, "column": -1}, "parameter=column"),
    ],
)
async def test_an_invalid_argument_is_a_tool_error_naming_it(
    project: Path, name: str, arguments: dict[str, Any], expected: str
) -> None:
    error = await _call(name, {**arguments, "project_path": project.as_posix()})
    assert not isinstance(error, UnexpectedToolError)
    assert "ValidationError: " in str(error)
    assert expected in str(error)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("resolve", {"identifier": "pkg.mod.Thing"}),
        ("resolve_at", {"file": "pkg/mod.py", "line": 1, "column": 6}),
        ("inspect", {"handle": "pkg.mod.Thing"}),
        ("outline", {"handle": "pkg"}),
        ("expand", {"handle": "pkg.mod", "edge": "members"}),
        ("trace", {"start": "pkg.mod", "follow": ["members"]}),
    ],
)
async def test_a_missing_project_is_a_tool_error(
    tmp_path: Path, name: str, arguments: dict[str, Any]
) -> None:
    missing = (tmp_path / "does-not-exist").as_posix()
    error = await _call(name, {**arguments, "project_path": missing})
    assert not isinstance(error, UnexpectedToolError)
    assert "ProjectNotFoundError: Project not found" in str(error)


async def test_a_genuine_bug_is_still_a_crash(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(identifier: str, analyzer: Any) -> dict[str, Any]:  # noqa: ARG001
        raise RuntimeError("a real pyeye bug")

    monkeypatch.setattr(server, "_resolve_impl", broken)
    with pytest.raises(UnexpectedToolError) as excinfo:
        await server.mcp.call_tool(
            "resolve", {"identifier": "x", "project_path": project.as_posix()}
        )
    # The SDK keeps a crash's text on the server.
    assert "a real pyeye bug" not in str(excinfo.value)


async def test_a_lookup_miss_is_still_a_response(project: Path) -> None:
    result = await server.mcp.call_tool(
        "resolve", {"identifier": "pkg.mod.Nope", "project_path": project.as_posix()}
    )
    assert result.is_error is False
