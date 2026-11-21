"""``src/`` is a source root when the build backends' default puts the project's own package there (#1078).

``detect_src_layout`` required a REGULAR package (``__init__.py``) in ``src/``.
Poetry's ``src/poetry`` is a PEP 420 namespace (shared with poetry-core), and
Poetry declares no ``packages``: poetry-core's documented default uses the
project's own name at ``<name>`` or ``src/<name>``, as hatchling, uv_build,
pdm-backend and setuptools' src-layout discovery do. So ``src`` wasn't a
source root and every handle read ``src.poetry.…``.

The rule (maintainer's "declared, not guessed", #1035): ``src/`` is a source
root when ``src/<the project's normalised name>`` is a package or a PEP 420
directory. A guess from any other directory under ``src/`` is not made, and an
explicitly declared ``from``/``where`` still wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.project_layout import detect_src_layout, module_name_for_file


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _pep621(name: str) -> str:
    return f'[project]\nname = "{name}"\nversion = "0"\n'


def _names(root: Path, rel: str) -> tuple[str | None, str | None]:
    """The module name of *rel* from an analyzer without config, and with one."""
    bare = JediAnalyzer(root.as_posix())
    configured = JediAnalyzer(root.as_posix(), config=ProjectConfig(root.as_posix()))
    return (
        module_name_for_file(bare, root / rel),
        module_name_for_file(configured, root / rel),
    )


def test_a_namespace_named_like_the_project_makes_src_a_root(tmp_path: Path) -> None:
    """The Poetry shape: no __init__.py, no packages declared, [project].name = poetry."""
    root = _write(
        tmp_path / "poetry-repo",
        {"pyproject.toml": _pep621("poetry"), "src/poetry/console/app.py": "class App: ...\n"},
    )
    assert detect_src_layout(root) == root / "src"
    assert _names(root, "src/poetry/console/app.py") == ("poetry.console.app",) * 2


@pytest.mark.parametrize(
    ("name", "directory"),
    [("My-Package", "my_package"), ("my.package", "my_package"), ("MY_PKG", "my_pkg")],
)
def test_the_name_is_normalised(tmp_path: Path, name: str, directory: str) -> None:
    root = _write(
        tmp_path / "proj",
        {"pyproject.toml": _pep621(name), f"src/{directory}/mod.py": "X = 1\n"},
    )
    assert detect_src_layout(root) == root / "src"


def test_a_poetry_name_counts_too(tmp_path: Path) -> None:
    """Poetry 1.x put the name under [tool.poetry], not [project]."""
    root = _write(
        tmp_path / "proj",
        {
            "pyproject.toml": '[tool.poetry]\nname = "legacy-app"\nversion = "0"\n',
            "src/legacy_app/mod.py": "X = 1\n",
        },
    )
    assert detect_src_layout(root) == root / "src"


def test_mixed_regular_and_namespace(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "proj",
        {
            "pyproject.toml": _pep621("app"),
            "src/app/core.py": "X = 1\n",  # the project's namespace
            "src/helpers/__init__.py": "",  # a regular package beside it
        },
    )
    assert detect_src_layout(root) == root / "src"
    assert _names(root, "src/app/core.py") == ("app.core",) * 2


def test_a_name_that_matches_no_src_dir_changes_nothing(tmp_path: Path) -> None:
    """A src/ of loose script dirs is not guessed into a root (#1035's ruling)."""
    root = _write(
        tmp_path / "proj",
        {"pyproject.toml": _pep621("something-else"), "src/tools/run.py": "X = 1\n"},
    )
    assert detect_src_layout(root) is None
    assert _names(root, "src/tools/run.py") == ("src.tools.run",) * 2


def test_a_stray_dir_named_like_the_project_is_not_enough(tmp_path: Path) -> None:
    """``src/<name>/`` must hold importable content (dir_shallow_qualifies, #444)."""
    root = _write(
        tmp_path / "proj",
        {"pyproject.toml": _pep621("app"), "src/app/README.txt": "data\n"},
    )
    assert detect_src_layout(root) is None


def test_no_pyproject_keeps_the_regular_package_rule(tmp_path: Path) -> None:
    root = _write(tmp_path / "proj", {"src/pkg/__init__.py": "", "src/pkg/m.py": "X = 1\n"})
    assert detect_src_layout(root) == root / "src"


def test_a_declared_from_still_wins(tmp_path: Path) -> None:
    """``from = "lib"`` names the package root: the default for src/ doesn't add a root."""
    root = _write(
        tmp_path / "proj",
        {
            "pyproject.toml": _pep621("app")
            + '[tool.poetry]\npackages = [{ include = "app", from = "lib" }]\n',
            "lib/app/__init__.py": "",
            "lib/app/m.py": "X = 1\n",
            "src/app/other.py": "Y = 1\n",
        },
    )
    names = {Path(p).name for p in ProjectConfig(root.as_posix()).get_package_paths()}
    assert "lib" in names and "src" not in names  # the project root is listed too


def test_declared_only_namespace_already_worked(tmp_path: Path) -> None:
    """Pinned: a declared from = "src" with a namespace was already a root (before #1078)."""
    root = _write(
        tmp_path / "proj",
        {
            "pyproject.toml": _pep621("other")
            + '[tool.poetry]\npackages = [{ include = "ns", from = "src" }]\n',
            "src/ns/m.py": "X = 1\n",
        },
    )
    configured = JediAnalyzer(root.as_posix(), config=ProjectConfig(root.as_posix()))
    assert module_name_for_file(configured, root / "src" / "ns" / "m.py") == "ns.m"


def test_an_unreadable_pyproject_falls_back_to_the_old_rule(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "proj",
        {"pyproject.toml": "[project\nname = ", "src/app/m.py": "X = 1\n"},
    )
    assert detect_src_layout(root) is None
