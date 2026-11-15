"""Paths go back to the agent in the spelling it used for the project (#717, #603).

An agent working in a symlinked checkout (``~/code`` -> ``/Volumes/...``)
compares returned paths with its own and with its sandbox's allowed
directories, so the real path is no use to it. Two places used to lose the
spelling: ``PathValidator.validate_path`` resolved every absolute argument, and
Jedi reports files resolved. The validator now keeps the caller's spelling, and
the MCP layer re-spells in-project paths under the given ``project_path``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pyeye.path_utils import absolute_path, respell_paths, respell_under
from pyeye.validation import PathValidator

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="creating symlinks needs privileges on Windows"
)


@pytest.fixture
def linked(tmp_path: Path) -> tuple[Path, Path]:
    real = tmp_path / "real" / "proj"
    (real / "pkg").mkdir(parents=True)
    (real / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (real / "pkg" / "core.py").write_text("class C:\n    pass\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    return real, link


def test_absolute_path_keeps_the_spelling(linked: tuple[Path, Path]) -> None:
    real, link = linked
    assert absolute_path(link) == link
    assert absolute_path(link / "pkg" / ".." / "pkg") == link / "pkg"
    assert absolute_path(link).resolve() == real.resolve()


def test_respell_under_puts_a_resolved_file_under_the_given_root(linked: tuple[Path, Path]) -> None:
    real, link = linked
    resolved_file = (real / "pkg" / "core.py").resolve().as_posix()
    assert respell_under(resolved_file, [link]) == (link / "pkg" / "core.py").as_posix()


def test_respell_under_leaves_outside_files_alone(
    linked: tuple[Path, Path], tmp_path: Path
) -> None:
    _, link = linked
    outside = (tmp_path / "elsewhere" / "x.py").as_posix()
    assert respell_under(outside, [link]) == outside


def test_respell_paths_walks_files_and_importer_lists(linked: tuple[Path, Path]) -> None:
    real, link = linked
    f = (real / "pkg" / "core.py").resolve().as_posix()
    data = {
        "location": {"file": f, "line_start": 1},
        "stubs": [{"location": {"file": f}}],
        "unresolved_importers": [f],
        "handle": "pkg.core.C",
        "detail": f,  # prose is not a path key: left alone
    }
    out = respell_paths(data, [link])
    want = (link / "pkg" / "core.py").as_posix()
    assert out["location"]["file"] == want
    assert out["stubs"][0]["location"]["file"] == want
    assert out["unresolved_importers"] == [want]
    assert out["handle"] == "pkg.core.C" and out["detail"] == f
    assert data["location"]["file"] == f  # the input is not mutated


def test_validate_path_keeps_a_symlinked_spelling(linked: tuple[Path, Path]) -> None:
    _, link = linked
    assert PathValidator.validate_path(link.as_posix()) == link


def test_validate_path_still_rejects_by_the_resolved_form(tmp_path: Path) -> None:
    """The security checks still see where a link really points."""
    from pyeye.exceptions import ValidationError

    if not Path("/etc/passwd").exists():
        pytest.skip("needs /etc/passwd")
    sneaky = tmp_path / "sneaky"
    sneaky.symlink_to("/etc", target_is_directory=True)
    with pytest.raises(ValidationError):
        PathValidator.validate_path((sneaky / "passwd").as_posix())


@pytest.mark.asyncio
async def test_mcp_tools_answer_in_the_callers_spelling(linked: tuple[Path, Path]) -> None:
    from pyeye.mcp import server

    _, link = linked
    project = link.as_posix()
    want = (link / "pkg" / "core.py").as_posix()

    resolved = await server.resolve("pkg.core.C", project_path=project)
    inspected = await server.inspect("pkg.core.C", project_path=project)
    members = await server.expand("pkg.core", "members", project_path=project)
    tree = await server.outline("pkg.core", project_path=project)
    at = await server.resolve_at(want, 1, 6, project_path=project)

    assert resolved["location"]["file"] == want
    assert inspected["location"]["file"] == want
    assert [s["handle"] for s in members["stubs"]] == ["pkg.core.C"]  # stubs carry no file
    assert tree["node"]["handle"] == "pkg.core"  # outline nodes are stubs: no file
    assert at.get("found") is True and at["location"]["file"] == want
