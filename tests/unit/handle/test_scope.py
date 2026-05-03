"""Tests for project-vs-external scope classification.

Covers the five acceptance criteria from the plan:
  (a) Project file path         → scope: "project"
  (b) site-packages path        → scope: "external"
  (c) Stdlib path               → scope: "external"
  (d) Vendored directory inside project (e.g., _vendor/) → "project" by default
  (e) Build artifact path (build/, dist/) → scope: "external"
"""

import sysconfig
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.scope import classify_scope

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "canonicalization_basic"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the canonicalization_basic fixture project."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# (a) Project file path → "project"
# ---------------------------------------------------------------------------


class TestProjectFile:
    """Paths inside the configured project source tree classify as project."""

    def test_file_inside_project_is_project(self, analyzer: JediAnalyzer) -> None:
        """A real Python file inside the fixture package classifies as project."""
        project_file = _FIXTURE / "package" / "_impl" / "config.py"
        result = classify_scope(project_file, analyzer)
        assert result == "project"

    def test_package_init_is_project(self, analyzer: JediAnalyzer) -> None:
        """The package __init__.py classifies as project."""
        init_file = _FIXTURE / "package" / "__init__.py"
        result = classify_scope(init_file, analyzer)
        assert result == "project"

    def test_project_root_file_is_project(self, analyzer: JediAnalyzer) -> None:
        """A hypothetical .py at the project root also classifies as project."""
        # Doesn't need to exist — just a path-classification decision
        hypothetical = _FIXTURE / "setup.py"
        result = classify_scope(hypothetical, analyzer)
        assert result == "project"


# ---------------------------------------------------------------------------
# (b) site-packages path → "external"
# ---------------------------------------------------------------------------


class TestSitePackages:
    """Paths under any site-packages directory classify as external."""

    def test_venv_site_packages_is_external(self, analyzer: JediAnalyzer) -> None:
        """Standard .venv site-packages path is external."""
        path = Path("/home/mark/myproject/.venv/lib/python3.12/site-packages/pydantic/main.py")
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_user_site_packages_is_external(self, analyzer: JediAnalyzer) -> None:
        """User-local site-packages (pip install --user) is external."""
        path = Path("/home/mark/.local/lib/python3.12/site-packages/requests/__init__.py")
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_system_site_packages_is_external(self, analyzer: JediAnalyzer) -> None:
        """System site-packages path is external."""
        path = Path("/usr/lib/python3/dist-packages/numpy/core/numeric.py")
        # dist-packages is also a site-packages variant on Debian/Ubuntu
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_path_with_site_packages_component_is_external(self, analyzer: JediAnalyzer) -> None:
        """Any path containing 'site-packages' as a segment is external."""
        path = Path("/opt/conda/envs/ml/lib/python3.11/site-packages/torch/nn/functional.py")
        result = classify_scope(path, analyzer)
        assert result == "external"


# ---------------------------------------------------------------------------
# (c) Stdlib path → "external"
# ---------------------------------------------------------------------------


class TestStdlib:
    """Paths inside the Python stdlib classify as external."""

    def test_stdlib_path_is_external(self, analyzer: JediAnalyzer) -> None:
        """A file under sysconfig stdlib is external."""
        stdlib_root = Path(sysconfig.get_paths()["stdlib"])
        # Construct a hypothetical path — no real file read needed
        stdlib_path = stdlib_root / "os.py"
        result = classify_scope(stdlib_path, analyzer)
        assert result == "external"

    def test_stdlib_subdir_is_external(self, analyzer: JediAnalyzer) -> None:
        """A file in a stdlib subdirectory is external."""
        stdlib_root = Path(sysconfig.get_paths()["stdlib"])
        stdlib_path = stdlib_root / "email" / "message.py"
        result = classify_scope(stdlib_path, analyzer)
        assert result == "external"


# ---------------------------------------------------------------------------
# (d) Vendored directory inside project → "project" (default)
# ---------------------------------------------------------------------------


class TestVendored:
    """Vendored directories inside the project root default to project scope.

    Per the spec: vendored code lives inside the project root, so it is
    classified as "project" by default.  A future config option could override
    this; that is documented in scope.py but not yet implemented.
    """

    def test_vendor_subdir_is_project_by_default(self, analyzer: JediAnalyzer) -> None:
        """_vendor/ inside the project root classifies as project by default."""
        path = _FIXTURE / "_vendor" / "attrs" / "__init__.py"
        result = classify_scope(path, analyzer)
        assert result == "project"

    def test_third_party_subdir_is_project_by_default(self, analyzer: JediAnalyzer) -> None:
        """third_party/ inside the project root classifies as project by default."""
        path = _FIXTURE / "third_party" / "cachetools.py"
        result = classify_scope(path, analyzer)
        assert result == "project"


# ---------------------------------------------------------------------------
# (e) Build artifact path → "external"
# ---------------------------------------------------------------------------


class TestBuildArtifacts:
    """Build artifact directories inside the project classify as external."""

    def test_build_dir_is_external(self, analyzer: JediAnalyzer) -> None:
        """build/ directory inside the project root is external."""
        path = _FIXTURE / "build" / "lib" / "package" / "config.py"
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_dist_dir_is_external(self, analyzer: JediAnalyzer) -> None:
        """dist/ directory inside the project root is external."""
        path = _FIXTURE / "dist" / "mypackage-1.0-py3-none-any.whl" / "mypackage" / "core.py"
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_tox_dir_is_external(self, analyzer: JediAnalyzer) -> None:
        """.tox/ directory inside the project root is external."""
        path = _FIXTURE / ".tox" / "py312" / "lib" / "python3.12" / "site-packages" / "foo.py"
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_pycache_dir_is_external(self, analyzer: JediAnalyzer) -> None:
        """__pycache__ directory inside the project root is external."""
        path = _FIXTURE / "package" / "__pycache__" / "config.cpython-312.pyc"
        result = classify_scope(path, analyzer)
        assert result == "external"

    def test_egg_info_dir_is_external(self, analyzer: JediAnalyzer) -> None:
        """.egg-info directory inside the project root is external."""
        path = _FIXTURE / "mypackage.egg-info" / "SOURCES.txt"
        result = classify_scope(path, analyzer)
        assert result == "external"


# ---------------------------------------------------------------------------
# String input (accepts str or Path)
# ---------------------------------------------------------------------------


class TestStringInput:
    """classify_scope accepts str paths as well as Path objects."""

    def test_str_project_path_is_project(self, analyzer: JediAnalyzer) -> None:
        """classify_scope works with string paths."""
        project_file = str(_FIXTURE / "package" / "_impl" / "config.py")
        result = classify_scope(project_file, analyzer)
        assert result == "project"

    def test_str_site_packages_is_external(self, analyzer: JediAnalyzer) -> None:
        """classify_scope works with string site-packages path."""
        path = "/home/user/.venv/lib/python3.12/site-packages/flask/__init__.py"
        result = classify_scope(path, analyzer)
        assert result == "external"


# ---------------------------------------------------------------------------
# Source roots and additional paths (covers _project_roots branches)
# ---------------------------------------------------------------------------


class TestAdditionalRoots:
    """source_roots and additional_paths extend the project boundary."""

    def test_source_root_file_is_project(self) -> None:
        """A file under an explicit source root classifies as project."""

        from pyeye.analyzers.jedi_analyzer import JediAnalyzer

        analyzer = JediAnalyzer(str(_FIXTURE))
        # Manually inject a source_root (simulates src-layout config)
        extra_root = _FIXTURE / "src"
        analyzer.source_roots = [extra_root]
        path = extra_root / "somepackage" / "core.py"
        result = classify_scope(path, analyzer)
        assert result == "project"

    def test_additional_path_file_is_project(self) -> None:
        """A file under an additional_path classifies as project."""

        from pyeye.analyzers.jedi_analyzer import JediAnalyzer

        analyzer = JediAnalyzer(str(_FIXTURE))
        sibling_root = _FIXTURE.parent / "sibling_package"
        analyzer.additional_paths = [sibling_root]
        path = sibling_root / "utils.py"
        result = classify_scope(path, analyzer)
        assert result == "project"


# ---------------------------------------------------------------------------
# Default fallback (rule 5): truly unknown path → "external"
# ---------------------------------------------------------------------------


class TestDefaultFallback:
    """Paths that don't match project roots fall through to external."""

    def test_unknown_absolute_path_is_external(self, analyzer: JediAnalyzer) -> None:
        """An absolute path unrelated to the project and not stdlib/site-packages is external."""
        # /tmp is not stdlib, not site-packages, not in the fixture project
        path = Path("/tmp/some_random_script.py")
        result = classify_scope(path, analyzer)
        assert result == "external"
