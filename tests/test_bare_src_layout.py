"""A bare ``JediAnalyzer`` detects a ``src/`` layout without config (#625 slice 3).

Before this change, ``src/`` detection lived only in ``ProjectConfig``. A
``JediAnalyzer`` built without a config had no source roots, so on a src-layout
project it named everything ``src.<pkg>…``. Its tools then disagreed with an
analyzer built through ``ProjectManager.get_analyzer`` (#614's "bare" src_layout
entries). Analyzers built with and without config now share one detection rule,
``project_layout.detect_src_layout``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve
from pyeye.project_layout import detect_src_layout

_FIXTURE = Path(__file__).parent / "fixtures" / "added_sys_path_project"


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestDetectSrcLayout:
    def test_src_with_a_package(self, tmp_path: Path) -> None:
        _write(tmp_path / "src" / "pkg" / "__init__.py")
        assert detect_src_layout(tmp_path) == tmp_path / "src"

    def test_src_without_packages(self, tmp_path: Path) -> None:
        _write(tmp_path / "src" / "loose.py")
        assert detect_src_layout(tmp_path) is None

    def test_no_src(self, tmp_path: Path) -> None:
        _write(tmp_path / "pkg" / "__init__.py")
        assert detect_src_layout(tmp_path) is None

    def test_src_is_a_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "src")
        assert detect_src_layout(tmp_path) is None

    def test_project_config_uses_the_same_rule(self, tmp_path: Path) -> None:
        _write(tmp_path / "src" / "pkg" / "__init__.py")
        config = ProjectConfig(str(tmp_path))
        assert (tmp_path / "src").resolve().as_posix() in config.get_package_paths()


class TestBareAnalyzer:
    def test_bare_analyzer_has_the_src_root(self) -> None:
        analyzer = JediAnalyzer(str(_FIXTURE))
        # In project_path's own (unresolved, #603) spelling, so it matches the
        # files enumerated under project_path.
        src = Path(os.path.abspath(_FIXTURE)) / "src"
        assert analyzer.source_roots == [src]
        assert analyzer.added_sys_path == [src]

    def test_no_src_layout_leaves_roots_empty(self, tmp_path: Path) -> None:
        _write(tmp_path / "pkg" / "__init__.py")
        analyzer = JediAnalyzer(str(tmp_path))
        assert analyzer.source_roots == []
        assert analyzer.added_sys_path == []

    @pytest.mark.parametrize(
        "handle", ["mypackage", "mypackage.module", "mypackage.module.my_function"]
    )
    async def test_bare_resolve_and_inspect_agree_without_src_prefix(self, handle: str) -> None:
        analyzer = JediAnalyzer(str(_FIXTURE))
        resolved = await resolve(handle, analyzer)
        inspected = await inspect(handle, analyzer)
        assert resolved["found"] is True
        assert resolved["handle"] == handle
        assert inspected.get("found", True) is True
        assert inspected["handle"] == handle

    async def test_bare_resolve_file_has_no_src_prefix(self) -> None:
        analyzer = JediAnalyzer(str(_FIXTURE))
        result = await resolve((_FIXTURE / "src" / "mypackage" / "module.py").as_posix(), analyzer)
        assert result["handle"] == "mypackage.module"


class TestSpellingOfTheProjectPath:
    """The src root follows ``project_path``'s spelling, not its resolved form.

    Regression: the first version resolved the src root while ``project_path``
    keeps the caller's spelling (#603). Wherever the two differ, files never
    matched the root and were named ``src.<pkg>…``. On Windows CI that was an
    8.3/long-name or case difference (``resolve("mypackage.module.my_function")``
    returned ``src.mypackage.module.my_function``). A symlinked project path
    reproduces it on any OS that allows symlinks.
    """

    @pytest.fixture
    def linked_fixture(self, tmp_path: Path) -> Path:
        link = tmp_path / "linked_project"
        try:
            link.symlink_to(_FIXTURE.resolve(), target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks are not available here")
        return link

    def test_root_keeps_the_symlink_spelling(self, linked_fixture: Path) -> None:
        analyzer = JediAnalyzer(str(linked_fixture))
        assert analyzer.source_roots == [Path(os.path.abspath(linked_fixture)) / "src"]

    @pytest.mark.parametrize(
        "handle", ["mypackage", "mypackage.module", "mypackage.module.my_function"]
    )
    async def test_handles_have_no_src_prefix_through_a_symlink(
        self, linked_fixture: Path, handle: str
    ) -> None:
        analyzer = JediAnalyzer(str(linked_fixture))
        resolved = await resolve(handle, analyzer)
        assert resolved["found"] is True
        assert resolved["handle"] == handle
