"""Documented examples are executed, not trusted (#828, design §4, D10, C10).

Every ``json pyeye-example`` block in the doc registry's example-bearing pages
(``docs/api/``, ``docs/reference/``, skills) is called through the real MCP
server against a fixture project:

- the response of a primitive (``resolve``, ``resolve_at``, ``inspect``,
  ``expand``, ``outline``, ``trace``) must pass the conformance linter;
- a shown ``json pyeye-output`` must match the response's structure (C10).

The fixture is copied to a temporary directory and the test runs with that as
its working directory, as a server started in the project would. A copy keeps
sibling auto-discovery away from the other fixtures.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import docs
from pyeye.docs_facts.examples import Example, allows_examples, match_shown, parse_examples
from tests.conformance.response_linter import lint_response

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PRIMITIVES = {"resolve", "resolve_at", "inspect", "expand", "outline", "trace"}
#: At least this many examples must run, or the suite would pass having run none.
MIN_EXAMPLES = 8


def _collect() -> list[tuple[str, Example]]:
    found = []
    for path, entry in docs.registered_files(ROOT):
        if not allows_examples(entry):
            continue
        examples, _ = parse_examples((ROOT / path).read_text(encoding="utf-8"))
        found.extend((path, example) for example in examples)
    return found


EXAMPLES = _collect()


@pytest.fixture(scope="session")
def projects(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Each fixture an example names, copied once to its own directory."""
    copies = {}
    for name in sorted({example.fixture for _, example in EXAMPLES}):
        target = tmp_path_factory.mktemp(f"docs-example-{name}") / "project"
        shutil.copytree(FIXTURES / name, target)
        copies[name] = target
    return copies


def _plugin_server(project: Path) -> Any:
    from mcp.server.mcpserver import MCPServer

    from pyeye.config import ProjectConfig
    from pyeye.mcp import server as srv
    from pyeye.scope_utils import SmartScopeResolver

    server = MCPServer("docs-examples-plugins")
    plugins = [cls(project.as_posix()) for cls in srv._PLUGIN_CLASSES]
    srv.register_plugin_tools(
        server, plugins, SmartScopeResolver(ProjectConfig(project.as_posix()))
    )
    return server


def _call(project: Path, example: Example) -> Any:
    """Call the example's tool through the MCP server; the decoded response."""
    from pyeye.mcp.server import mcp

    async def run() -> Any:
        core = {t.name for t in await mcp.list_tools()}
        server = mcp if example.tool in core else _plugin_server(project)
        names = {t.name for t in await server.list_tools()}
        assert example.tool in names, f"no MCP tool named {example.tool!r}"
        args = {**example.args, "project_path": project.as_posix()}
        return await server.call_tool(example.tool, args)

    result = asyncio.run(run())
    assert not result.is_error, result.content
    response = result.structured_content
    # A tool returning a list is wrapped as {"result": [...]} on the wire.
    if isinstance(response, dict) and set(response) == {"result"}:
        return response["result"]
    return response


def test_examples_exist() -> None:
    """Guard: the parametrised test below must have something to run."""
    assert len(EXAMPLES) >= MIN_EXAMPLES, [f"{p}:{e.line}" for p, e in EXAMPLES]


def test_every_example_tag_parses() -> None:
    """``check`` reports these too; this keeps the run itself honest."""
    problems = [
        f"{path}:{p.line}: {p.message}"
        for path, entry in docs.registered_files(ROOT)
        if allows_examples(entry)
        for p in parse_examples((ROOT / path).read_text(encoding="utf-8"))[1]
    ]

    assert not problems


@pytest.mark.parametrize(
    ("path", "example"), EXAMPLES, ids=[f"{p}:{e.line}:{e.tool}" for p, e in EXAMPLES]
)
def test_example_runs(
    path: str,
    example: Example,
    projects: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = projects[example.fixture]
    monkeypatch.chdir(project)

    response = _call(project, example)

    if example.tool in PRIMITIVES:
        lint_response(response, example.tool)
    if example.shows_output:
        mismatches = match_shown(example.output, response)
        assert not mismatches, f"{path}:{example.line}: " + "; ".join(mismatches)
