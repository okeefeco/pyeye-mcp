"""A package added under a non-identifier directory resolves (#814).

Jedi names a file from the first sys_path root that contains it. For a package
added inside the project, that is the project root, so the module part of Jedi's
``full_name`` carries the directories above the package: ``.hidden.upstream.…``,
``my-dir.upstream.…``. The resolver compared requests against that name instead
of pyeye's own (the one file -> module mapper, #714), so ``.hidden/`` and
``my-dir/`` never resolved and ``vendor/`` resolved only through a fallback.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.resolver import Resolved, resolve_handle
from tests.conformance.response_linter import lint_response

LOCATIONS = [".hidden/upstream", "my-dir/upstream", "vendor/upstream"]


def _project(tmp_path: Path, location: str) -> tuple[Path, Path]:
    """A project with ``clonepkg`` added under *location*; ``(project, package root)``."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("", encoding="utf-8")
    root = project / location
    pkg = root / "clonepkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .thing import CloneThing\n", encoding="utf-8")
    (pkg / "thing.py").write_text(
        "class CloneThing:\n    size = 1\n\n    def grow(self) -> int:\n        return self.size\n",
        encoding="utf-8",
    )
    return project, root


@pytest.fixture(params=LOCATIONS)
def analyzer(request: pytest.FixtureRequest, tmp_path: Path) -> JediAnalyzer:
    project, root = _project(tmp_path, request.param)
    analyzer = JediAnalyzer(project.as_posix())
    analyzer.set_additional_paths([root])
    return analyzer


class TestResolver:
    @pytest.mark.parametrize(
        ("handle", "kind"),
        [
            ("clonepkg.thing.CloneThing", "class"),
            ("clonepkg.thing.CloneThing.grow", "method"),
            ("clonepkg.thing.CloneThing.size", "attribute"),
        ],
    )
    def test_definitions_resolve(self, analyzer: JediAnalyzer, handle: str, kind: str) -> None:
        result = resolve_handle(handle, analyzer)

        assert isinstance(result, Resolved), result
        assert result.handle == handle
        assert result.kind == kind
        assert result.scope == "project"

    def test_the_definition_is_placed_by_step_4_itself(self, analyzer: JediAnalyzer) -> None:
        """The anchor is the class's own Name in thing.py, not a fallback's guess."""
        result = resolve_handle("clonepkg.thing.CloneThing", analyzer)

        assert isinstance(result, Resolved)
        assert Path(result.anchor.module_path).name == "thing.py"
        assert result.anchor.name == "CloneThing"


def _tool(name: str, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(mcp.call_tool(name, args))
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("location", LOCATIONS)
def test_the_tools_answer_after_configure_packages(tmp_path: Path, location: str) -> None:
    project, root = _project(tmp_path, location)
    p = project.as_posix()

    configured = _tool("configure_packages", packages=[root.as_posix()], save=False, project_path=p)
    assert json.dumps(configured)

    resolved = _tool("resolve", identifier="clonepkg.thing.CloneThing", project_path=p)
    inspected = _tool("inspect", handle="clonepkg.thing.CloneThing", project_path=p)
    outlined = _tool("outline", handle="clonepkg.thing", project_path=p)
    members = _tool("expand", handle="clonepkg.thing.CloneThing", edge="members", project_path=p)

    for payload, tool in (
        (resolved, "resolve"),
        (inspected, "inspect"),
        (outlined, "outline"),
        (members, "expand"),
    ):
        assert payload["found"] is True, (tool, payload)
        lint_response(payload, tool)
    assert resolved["handle"] == "clonepkg.thing.CloneThing"
    assert inspected["kind"] == "class"
    assert [c["node"]["handle"] for c in outlined["children"]] == ["clonepkg.thing.CloneThing"]
    assert {s["handle"] for s in members["stubs"]} == {
        "clonepkg.thing.CloneThing.size",
        "clonepkg.thing.CloneThing.grow",
    }


@pytest.mark.parametrize("location", LOCATIONS)
def test_the_relative_re_export_resolves_to_the_definition(tmp_path: Path, location: str) -> None:
    """With #857, a relative re-export collapses in every layout; ``.hidden`` too since #858."""
    project, root = _project(tmp_path, location)
    analyzer = JediAnalyzer(project.as_posix())
    analyzer.set_additional_paths([root])

    result = resolve_handle("clonepkg.CloneThing", analyzer)

    assert isinstance(result, Resolved), result
    assert result.handle == "clonepkg.thing.CloneThing"
