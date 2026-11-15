"""Tests for module analysis functionality."""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class TestListPackages:
    """Test the list_packages functionality."""

    def test_list_packages_project_not_found(self):
        """Test error handling for non-existent project.

        The deleted ``list_packages`` tool wrapper used to validate the path
        and raise ``FileAccessError``; that path validation now lives in the
        kept ``JediAnalyzer`` constructor, which raises ``ProjectNotFoundError``
        for a non-existent project. The behavior (error on bad project path) is
        preserved at the construction site.
        """
        from pyeye.exceptions import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError) as exc_info:
            JediAnalyzer("/non/existent/path")
        assert "Project not found" in str(exc_info.value)


class TestJediAnalyzerMethods:
    """Test the JediAnalyzer methods directly."""

    def test_analyzer_initialization(self, tmp_path):
        """Test JediAnalyzer initialization."""
        analyzer = JediAnalyzer(str(tmp_path))
        assert analyzer.project_path == tmp_path

    def test_analyzer_project_not_found(self):
        """Test analyzer with non-existent project."""
        from pyeye.exceptions import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError):
            JediAnalyzer("/non/existent/path")


_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "resolve_project"
_TARGET = "mypackage._core.widgets"
_TARGET_FILE = _FIXTURE / "mypackage" / "_core" / "widgets.py"


class TestFindImporters:
    """Tests for the extracted ``find_importers`` reverse-scan method.

    Uses the committed ``resolve_project`` fixture (a real directory, not a
    tmp dir) so the file-based reverse scan runs against real files rather than
    a synthesised tree.  ``find_importers`` backs the live
    ``expand(handle, edge="imported_by")`` edge.
    """

    @pytest.mark.asyncio
    async def test_find_importers_reports_direct_and_relative_importers(self):
        """Both a direct ``import`` and a relative ``from`` importer are found.

        ``direct_importer`` reaches the target via ``import
        mypackage._core.widgets`` (``ast.Import``); ``rel_importer`` reaches it
        via ``from .widgets import make_widget`` (``ast.ImportFrom`` resolved
        through ``_resolve_relative_import``). Subset assertions keep this
        robust against fixture growth.
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = (await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")).named

        modules = {m for m, _ in pairs}
        # Direct ast.Import importer.
        assert "mypackage._core.direct_importer" in modules
        # Relative ast.ImportFrom importer.
        assert "mypackage._core.rel_importer" in modules
        # Existing absolute from-importers are still present.
        assert "mypackage.usage" in modules

    @pytest.mark.asyncio
    async def test_find_importers_excludes_target_and_is_deduped(self):
        """The target's own file is excluded and modules are deduped."""
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = (await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")).named

        modules = [m for m, _ in pairs]
        # Target's own module never reports itself as an importer.
        assert _TARGET not in modules
        # Deduped by importer module (one entry per module).
        assert len(modules) == len(set(modules))
        # Every pair carries the importer's file path.
        for _module, file_path in pairs:
            assert isinstance(file_path, Path)

    @pytest.mark.asyncio
    async def test_find_importers_reports_non_package_script(self):
        """A standalone script outside the package is still reported.

        ``script_importer.py`` lives at the fixture root, outside
        ``mypackage/``, so its handle is the path-derived ``script_importer``
        (not a package module). The file-based scan must still attribute it,
        proving coverage breadth (tests + standalone scripts).
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = (await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")).named

        modules = {m for m, _ in pairs}
        assert "script_importer" in modules

    @pytest.mark.asyncio
    async def test_find_importers_reports_from_package_import_submodule(self):
        """``from package import submodule`` importers are attributed (#436).

        ``submod_importer`` reaches the target via
        ``from mypackage._core import widgets`` — the submodule idiom whose
        ``from`` clause names the *package* (``mypackage._core``) and whose
        imported name (``widgets``) completes the target's dotted handle. The
        reverse scan must reconstruct ``mypackage._core.widgets`` and attribute
        the importer, matching the forward ``imports`` edge which already
        resolves this idiom.
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = (await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")).named

        modules = {m for m, _ in pairs}
        assert "mypackage._core.submod_importer" in modules

    @pytest.mark.asyncio
    async def test_find_importers_reports_cross_package_submodule_script(self):
        """A cross-package ``from package import submodule`` importer is found.

        ``submod_script_importer`` lives at the fixture root (top-level handle
        ``submod_script_importer``), so it shares no top-level package with the
        target and cannot be admitted by ``shares_package``. Only the
        parent-package textual trigger (``mypackage._core`` appears in source)
        lets the AST check run — exercising the pre-filter half of the #436 fix.
        """
        analyzer = JediAnalyzer(str(_FIXTURE))
        pairs = (await analyzer.find_importers(_TARGET, _TARGET_FILE, scope="all")).named

        modules = {m for m, _ in pairs}
        assert "submod_script_importer" in modules
