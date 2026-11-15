"""Regression: inspect / outline / expand / trace share one resolver (#623 slice 2).

Before slice 2, inspect and outline echoed a re-export alias input while expand
and trace echoed the canonical handle, and inspect couldn't find an external
module such as ``logging`` at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.outline import outline
from pyeye.mcp.operations.trace import trace
from tests.conformance.response_linter import lint_response

_ALIAS = "pkg.Thing"
_CANONICAL = "pkg._impl.Thing"


@pytest.fixture
def project(tmp_path: Path) -> JediAnalyzer:
    files = {
        "pkg/__init__.py": "from pkg._impl import Thing\n",
        "pkg/_impl.py": "class Thing:\n    def method(self) -> int:\n        return 1\n",
    }
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(tmp_path))


@pytest.mark.parametrize("handle", [_ALIAS, _CANONICAL])
async def test_every_tool_echoes_the_canonical_handle(project: JediAnalyzer, handle: str) -> None:
    node = await inspect(handle, project)
    tree = await outline(handle, project)
    edge = await expand(handle, "members", project)
    graph = await trace(handle, ["members"], project, max_depth=1)
    lint_response(node, "inspect")
    lint_response(tree, "outline")
    lint_response(edge, "expand")
    lint_response(graph, "trace")

    assert node["handle"] == _CANONICAL  # inspect echoed the alias before #623
    assert tree["node"]["handle"] == _CANONICAL  # so did outline
    assert edge["source"] == _CANONICAL
    assert _CANONICAL in graph["nodes"]
    assert node["kind"] == tree["node"]["kind"] == "class"


async def test_alias_and_canonical_describe_the_same_definition(project: JediAnalyzer) -> None:
    alias_node = await inspect(_ALIAS, project)
    canon_node = await inspect(_CANONICAL, project)
    assert alias_node == canon_node


@pytest.mark.parametrize("module", ["logging", "os", "typing"])
async def test_inspect_finds_an_external_module(project: JediAnalyzer, module: str) -> None:
    """inspect, outline and expand find stdlib modules (#602 part a, inspect side)."""
    node = await inspect(module, project)
    lint_response(node, "inspect")
    assert (node["found"], node["handle"], node["kind"], node["scope"]) == (
        True,
        module,
        "module",
        "external",
    )
    members = await expand(module, "members", project)
    lint_response(members, "expand")
    assert members["found"] is True
    # count == expand for the measured edge (#599 invariant).
    if "members" in node["edge_counts"]:
        assert node["edge_counts"]["members"] == len(members["stubs"])


async def test_unresolvable_handle_echoes_the_input(project: JediAnalyzer) -> None:
    """On not-found every tool echoes the input (#545); only success is canonical."""
    bogus = "pkg.Nope"
    node = await inspect(bogus, project)
    tree = await outline(bogus, project)
    assert node["found"] is False and node["handle"] == bogus
    assert tree["found"] is False and tree["handle"] == bogus
