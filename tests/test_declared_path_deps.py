"""Sibling packages come only from what the project declares (#1035).

The user's ruling (A+): the guess-from-neighbouring-directories discovery is
removed. It added every directory beside the project with a top-level ``.py``
or a ``setup.py`` (562 roots on a shared ``/tmp``), and it missed the modern
``pyproject.toml`` repos it was meant for. Packages beside the project now come
from declared or standard Python mechanisms, read statically:

- path dependencies in the project's ``pyproject.toml``: ``[tool.uv.sources]``
  ``path`` entries, ``[tool.uv.workspace]`` members, Poetry ``path``
  dependencies, and PEP 621 / PEP 735 ``name @ file:`` direct references (with
  PDM's ``${PROJECT_ROOT}`` and Hatch's ``{root:uri}`` expanded);
- the project's environment (#993), unchanged;
- pyeye's own config, unchanged.

Each declared directory's import root is its ``src/`` when it has a src
layout, else the directory. Each goes through the same path checks as any
configured package, is reported in ``discovered``, and is never saved.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


def _configure(proj: Path, **args: Any) -> dict[str, Any]:
    from pyeye.mcp.server import mcp

    result = asyncio.run(
        mcp.call_tool("configure_packages", {**args, "project_path": proj.as_posix()})
    )
    assert not result.is_error, result.content
    payload = result.structured_content
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def _lib(root: Path, name: str, *, src: bool = False) -> Path:
    """A sibling repository holding package *name*, flat or ``src/``-laid-out."""
    base = root / name / "src" if src else root / name
    (base / name).mkdir(parents=True)
    (base / name / "__init__.py").write_text("", encoding="utf-8")
    return root / name


@pytest.fixture
def parent(tmp_path: Path) -> Path:
    """A project beside unrelated directories that the old guess picked up."""
    root = tmp_path / "parent"
    (root / "proj" / "app").mkdir(parents=True)
    (root / "proj" / "app" / "__init__.py").write_text("import mylib\n", encoding="utf-8")
    (root / "unrelated1").mkdir()
    (root / "unrelated1" / "script.py").write_text("x = 1\n", encoding="utf-8")
    (root / "unrelated2").mkdir()
    (root / "unrelated2" / "setup.py").write_text("", encoding="utf-8")
    return root


def _pyproject(proj: Path, text: str) -> None:
    (proj / "pyproject.toml").write_text(text, encoding="utf-8")


def _declared(response: dict[str, Any]) -> list[tuple[str, str]]:
    return [(d["path"], d["reason"]) for d in response["discovered"]]


class TestNoGuessing:
    def test_undeclared_neighbours_are_not_packages(self, parent: Path) -> None:
        response = _configure(parent / "proj")

        assert response["packages"] == [(parent / "proj").resolve().as_posix()]
        assert response["discovered"] == []


class TestUv:
    def test_a_path_source(self, parent: Path) -> None:
        lib = _lib(parent, "mylib")
        _pyproject(parent / "proj", '[tool.uv.sources]\nmylib = { path = "../mylib" }\n')

        response = _configure(parent / "proj")

        assert _declared(response) == [(lib.resolve().as_posix(), "uv_source")]
        assert lib.resolve().as_posix() in response["packages"]

    def test_an_editable_src_layout_source_uses_its_src(self, parent: Path) -> None:
        lib = _lib(parent, "mylib", src=True)
        _pyproject(
            parent / "proj",
            '[tool.uv.sources]\nmylib = { path = "../mylib", editable = true }\n',
        )

        assert _declared(_configure(parent / "proj")) == [
            ((lib / "src").resolve().as_posix(), "uv_source")
        ]

    def test_a_list_of_sources_with_markers(self, parent: Path) -> None:
        a, b = _lib(parent, "liba"), _lib(parent, "libb")
        _pyproject(
            parent / "proj",
            "[tool.uv.sources]\nlib = [\n"
            '  { path = "../liba", marker = "sys_platform == \'linux\'" },\n'
            '  { path = "../libb", marker = "sys_platform != \'linux\'" },\n'
            "]\n"
            'other = { index = "pytorch" }\n',
        )

        assert sorted(_declared(_configure(parent / "proj"))) == sorted(
            [(a.resolve().as_posix(), "uv_source"), (b.resolve().as_posix(), "uv_source")]
        )

    def test_workspace_members(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        one, two = _lib(root / "packages", "one", src=True), _lib(root / "packages", "two")
        _lib(root / "packages", "skipme")
        (root / "app").mkdir(parents=True)
        _pyproject(
            root,
            '[tool.uv.workspace]\nmembers = ["packages/*"]\nexclude = ["packages/skipme"]\n',
        )

        assert sorted(_declared(_configure(root))) == sorted(
            [
                ((one / "src").resolve().as_posix(), "uv_workspace"),
                (two.resolve().as_posix(), "uv_workspace"),
            ]
        )

    def test_a_glob_member_cannot_escape_the_workspace(self, parent: Path) -> None:
        """A pattern that climbs out matches nothing; a literal path is a declaration."""
        shared = _lib(parent, "shared")
        _pyproject(
            parent / "proj",
            '[tool.uv.workspace]\nmembers = ["../*", "../shared"]\n',
        )

        assert _declared(_configure(parent / "proj")) == [
            (shared.resolve().as_posix(), "uv_workspace")
        ]

    def test_a_glob_member_symlinked_out_of_the_workspace_is_dropped(self, tmp_path: Path) -> None:
        import sys

        if sys.platform == "win32":
            pytest.skip("creating symlinks needs privileges on Windows")
        root = tmp_path / "ws"
        inside = _lib(root / "packages", "inside")
        outside = _lib(tmp_path / "elsewhere", "outside")
        (root / "packages" / "linked").symlink_to(outside, target_is_directory=True)
        _pyproject(root, '[tool.uv.workspace]\nmembers = ["packages/*"]\n')

        assert _declared(_configure(root)) == [(inside.resolve().as_posix(), "uv_workspace")]


class TestPoetry:
    def test_path_dependencies_in_main_and_groups(self, parent: Path) -> None:
        a, b, c = _lib(parent, "liba"), _lib(parent, "libb", src=True), _lib(parent, "libc")
        _pyproject(
            parent / "proj",
            "[tool.poetry.dependencies]\n"
            'python = "^3.11"\n'
            'liba = { path = "../liba", develop = true }\n'
            "[tool.poetry.group.dev.dependencies]\n"
            'libb = { path = "../libb" }\n'
            "[tool.poetry.dev-dependencies]\n"
            'libc = { path = "../libc" }\n',
        )

        assert sorted(_declared(_configure(parent / "proj"))) == sorted(
            [
                (a.resolve().as_posix(), "poetry_path"),
                ((b / "src").resolve().as_posix(), "poetry_path"),
                (c.resolve().as_posix(), "poetry_path"),
            ]
        )


class TestPep621:
    def test_file_urls_in_every_dependency_table(self, parent: Path) -> None:
        a, b, c = _lib(parent, "liba"), _lib(parent, "libb"), _lib(parent, "libc")
        _pyproject(
            parent / "proj",
            "[project]\n"
            'name = "proj"\n'
            f'dependencies = ["requests>=2", "liba @ {a.resolve().as_uri()}"]\n'
            "[project.optional-dependencies]\n"
            f'extra = ["libb @ {b.resolve().as_uri()}"]\n'
            "[dependency-groups]\n"
            f'dev = ["libc @ {c.resolve().as_uri()}", {{ include-group = "extra" }}]\n',
        )

        assert sorted(_declared(_configure(parent / "proj"))) == sorted(
            [(p.resolve().as_posix(), "pep621_file_url") for p in (a, b, c)]
        )

    @pytest.mark.parametrize(
        "url",
        ["file:///${PROJECT_ROOT}/../mylib", "{root:uri}/../mylib"],
        ids=["pdm", "hatch"],
    )
    def test_the_project_root_placeholders_are_expanded(self, parent: Path, url: str) -> None:
        lib = _lib(parent, "mylib")
        _pyproject(parent / "proj", f'[project]\nname = "proj"\ndependencies = ["mylib @ {url}"]\n')

        assert _declared(_configure(parent / "proj")) == [
            (lib.resolve().as_posix(), "pep621_file_url")
        ]

    def test_an_unknown_placeholder_skips_the_entry(self, parent: Path) -> None:
        _lib(parent, "mylib")
        _pyproject(
            parent / "proj",
            '[project]\nname = "proj"\ndependencies = ["mylib @ file:///${HOME}/../mylib"]\n',
        )

        assert _configure(parent / "proj")["discovered"] == []

    def test_an_archive_or_a_missing_directory_is_skipped(self, parent: Path) -> None:
        wheel = parent / "dist" / "mylib-1.0-py3-none-any.whl"
        wheel.parent.mkdir()
        wheel.write_bytes(b"")
        _pyproject(
            parent / "proj",
            '[project]\nname = "proj"\ndependencies = [\n'
            f'  "mylib @ {wheel.as_uri()}",\n'
            f'  "gone @ {(parent / "gone").as_uri()}",\n'
            "]\n",
        )

        assert _configure(parent / "proj")["discovered"] == []


class TestFileUrls:
    """``file:`` URLs are parsed as plain strings, with no URL library (SECURITY.md)."""

    @pytest.mark.parametrize(
        ("url", "path"),
        [
            ("file:///srv/lib", "/srv/lib"),
            ("file://localhost/srv/lib", "/srv/lib"),
            ("file:////srv/lib", "/srv/lib"),
            ("file:../lib", "../lib"),
            ("file:///srv/my%20lib/caf%C3%A9", "/srv/my lib/café"),
        ],
    )
    def test_local_forms(self, url: str, path: str) -> None:
        from pyeye.declared_deps import _file_url_to_path

        assert _file_url_to_path(url) == path

    def test_another_host_is_not_local(self) -> None:
        from pyeye.declared_deps import _file_url_to_path

        assert _file_url_to_path("file://fileserver/share/lib") is None

    def test_no_networking_module_is_imported(self) -> None:
        import ast

        import pyeye.declared_deps as module

        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"urllib", "http", "socket", "requests"}


class TestIgnoredInputs:
    """Malformed or non-local declarations add nothing and never fail a call."""

    def test_a_malformed_pyproject(self, parent: Path) -> None:
        _pyproject(parent / "proj", "[tool.uv.sources\nmylib = {\n")

        assert _configure(parent / "proj")["discovered"] == []

    def test_unusable_workspace_members(self, parent: Path) -> None:
        _lib(parent / "proj" / "packages", "ok")
        _pyproject(
            parent / "proj",
            '[tool.uv.workspace]\nmembers = [1, "/abs/*", "packages/*"]\n',
        )

        assert [r for _, r in _declared(_configure(parent / "proj"))] == ["uv_workspace"]

    def test_requirements_that_are_not_local_directories(self, parent: Path) -> None:
        _pyproject(
            parent / "proj",
            '[project]\nname = "proj"\ndependencies = [\n'
            '  "requests>=2",\n'
            '  "lib @ git+https://example.invalid/lib.git",\n'
            '  "lib2 @ file://fileserver/share/lib2",\n'
            "]\n",
        )

        assert _configure(parent / "proj")["discovered"] == []


class TestAlwaysDeclared:
    def test_read_beside_an_explicit_pyeye_config(self, parent: Path, tmp_path: Path) -> None:
        """Declared dependencies are the project's own facts: config doesn't hide them."""
        lib = _lib(parent, "mylib")
        other = tmp_path / "other"
        other.mkdir()
        proj = parent / "proj"
        _pyproject(proj, '[tool.uv.sources]\nmylib = { path = "../mylib" }\n')
        (proj / ".pyeye.json").write_text(
            json.dumps({"packages": [other.as_posix()]}), encoding="utf-8"
        )

        response = _configure(proj)

        assert {lib.resolve().as_posix(), other.resolve().as_posix()} <= set(response["packages"])
        assert _declared(response) == [(lib.resolve().as_posix(), "uv_source")]

    def test_never_saved(self, parent: Path, tmp_path: Path) -> None:
        _lib(parent, "mylib")
        other = tmp_path / "other"
        other.mkdir()
        proj = parent / "proj"
        _pyproject(proj, '[tool.uv.sources]\nmylib = { path = "../mylib" }\n')

        _configure(proj, packages=[other.as_posix()], save=True)

        assert json.loads((proj / ".pyeye.json").read_text()) == {"packages": [other.as_posix()]}


class TestPathChecks:
    def test_a_restricted_declared_path_is_refused_and_reported(self, parent: Path) -> None:
        import sys

        if sys.platform == "win32":
            pytest.skip("the deny-list names POSIX system directories")
        _pyproject(parent / "proj", '[tool.uv.sources]\nevil = { path = "/etc" }\n')

        response = _configure(parent / "proj")

        assert "/etc" not in response["packages"]
        assert response["discovered"] == []
        assert [r["path"] for r in response["rejected_paths"]] == ["/etc"]

    def test_a_refused_path_is_reported_as_declared(self, parent: Path) -> None:
        """rejected_paths shows the entry as written, not its resolved form (#717).

        On macOS /etc itself is a symlink to /private/etc; a symlink into /etc
        reproduces that on every POSIX platform.
        """
        import sys

        if sys.platform == "win32":
            pytest.skip("the deny-list names POSIX system directories")
        (parent / "etc-link").symlink_to("/etc", target_is_directory=True)
        _pyproject(parent / "proj", '[tool.uv.sources]\nevil = { path = "../etc-link" }\n')

        response = _configure(parent / "proj")

        assert [r["path"] for r in response["rejected_paths"]] == [(parent / "etc-link").as_posix()]
        assert response["discovered"] == []


class TestNotFoundHint:
    @pytest.mark.asyncio
    async def test_an_unresolved_top_level_import_suggests_declaring_it(self, parent: Path) -> None:
        from pyeye.mcp.server import mcp

        result = await mcp.call_tool(
            "resolve", {"identifier": "mylib.helpers", "project_path": (parent / "proj").as_posix()}
        )
        miss = result.structured_content

        assert miss["found"] is False
        assert "path dependency" in miss["detail"] and "configure_packages" in miss["detail"]
