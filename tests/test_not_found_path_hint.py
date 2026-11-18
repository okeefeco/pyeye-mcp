"""A file path given where a handle belongs gets a hint that works (#882).

``outline("src/x.py")`` used to answer "Call resolve('py')": the hint took the
part after the last dot, which for a path is the file suffix. Each test here
takes the call the hint suggests, runs it, and checks that it resolves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from pyeye.mcp.operations import not_found as nf
from pyeye.mcp.server import mcp

_SUGGESTED = re.compile(r"resolve\('([^']*)'\)")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (pkg / "mod.pyi").write_text("X: int\n", encoding="utf-8")
    (pkg / "stub.pyi").write_text("Y: int\n", encoding="utf-8")  # no .py beside it
    return tmp_path


async def _call(tool: str, project: Path, **args: Any) -> dict[str, Any]:
    result = await mcp.call_tool(tool, {**args, "project_path": project.as_posix()})
    assert not result.is_error, result.content
    response: dict[str, Any] = result.structured_content  # type: ignore[assignment]
    return response


async def _follow(detail: str, project: Path) -> dict[str, Any]:
    """Run the resolve() call *detail* suggests."""
    match = _SUGGESTED.search(detail)
    assert match, f"no resolve(...) call in {detail!r}"
    return await _call("resolve", project, identifier=match.group(1))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["outline", "inspect", "expand"])
@pytest.mark.parametrize("spelling", ["pkg/mod.py", "pkg\\mod.py", "pkg/mod.pyi"])
async def test_the_suggested_call_resolves_the_module(
    tool: str, spelling: str, project: Path
) -> None:
    args: dict[str, Any] = {"handle": spelling}
    if tool == "expand":
        args["edge"] = "members"
    miss = await _call(tool, project, **args)

    assert miss["found"] is False and miss["reason"] == "unresolved"
    assert "resolve('py')" not in miss["detail"] and "resolve('pyi')" not in miss["detail"]
    followed = await _follow(miss["detail"], project)
    assert followed["found"] is True and followed["handle"] == "pkg.mod", miss["detail"]


@pytest.mark.asyncio
async def test_resolve_of_a_stub_points_at_its_source(project: Path) -> None:
    miss = await _call("resolve", project, identifier="pkg/mod.pyi")

    assert miss["reason"] == "unresolved"
    followed = await _follow(miss["detail"], project)
    assert followed["found"] is True and followed["handle"] == "pkg.mod"


@pytest.mark.asyncio
async def test_a_stub_with_no_source_gets_an_honest_file_not_found(project: Path) -> None:
    miss = await _call("outline", project, handle="pkg/stub.pyi")

    followed = await _follow(miss["detail"], project)
    assert followed["found"] is False and followed["reason"] == "file_not_found"


@pytest.mark.parametrize(
    ("text", "path"),
    [
        ("src/x.py", "src/x.py"),
        ("src\\x.py", "src/x.py"),
        ("x.py", "x.py"),
        ("pkg/stub.pyi", "pkg/stub.pyi"),
        ("pkg.mod.py_thing", None),
        ("pkg.mod.pyx", None),
        ("pkg.mod.Thing", None),
    ],
)
def test_only_separators_or_a_source_suffix_make_a_path(text: str, path: str | None) -> None:
    assert nf._as_file_path(text) == path


def test_a_dotted_handle_keeps_todays_hint() -> None:
    """A last part that merely starts with ``py`` is a name, not a suffix."""
    response = nf.not_found("pkg.mod.py_thing")
    assert response["detail"] == (
        "Handle 'pkg.mod.py_thing' did not resolve to a symbol. "
        "Call resolve('py_thing') to find its canonical handle."
    )
    resolved = nf.not_found_for("resolve", {"identifier": "pkg.mod.py_thing"})
    assert "call resolve('py_thing') with the bare name" in resolved["detail"]
