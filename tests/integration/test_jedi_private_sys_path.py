"""Regression: Jedi's own subprocess directory is never on pyeye's sys.path (#722).

Jedi reports its inference subprocess's ``sys.path``, whose first entry is
Jedi's private ``jedi/inference/compiled/subprocess`` script directory.  Every
file there (``__init__.py``, ``functions.py``, ``__main__.py``) became an
importable top-level module: ``resolve("functions")`` answered with Jedi's
internals, and, the entry being FIRST in the base path, a same-named module
reachable only through ``added_sys_path`` (a configured package) was shadowed
in goto / infer.
"""

from __future__ import annotations

from pathlib import Path

import jedi
import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import inspect
from pyeye.mcp.operations.resolve import resolve, resolve_at

_JEDI_DIR = Path(jedi.__file__).resolve().parent


def _under_jedi(file: str | None) -> bool:
    if not file:
        return False
    return Path(file).resolve().is_relative_to(_JEDI_DIR)


def _project(root: Path, files: dict[str, str]) -> JediAnalyzer:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return JediAnalyzer(str(root))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["functions", "__init__"])
async def test_jedi_private_module_does_not_resolve(tmp_path: Path, name: str) -> None:
    analyzer = _project(tmp_path, {"pkg/__init__.py": "", "pkg/mod.py": "X = 1\n"})
    resolved = await resolve(name, analyzer)
    assert resolved["found"] is False, resolved
    inspected = await inspect(name, analyzer)
    assert inspected["found"] is False, inspected


@pytest.mark.asyncio
async def test_main_never_resolves_to_jedis_file(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, {"pkg/__init__.py": ""})
    resolved = await resolve("__main__", analyzer)
    if resolved["found"]:
        assert not _under_jedi(resolved.get("location", {}).get("file")), resolved


@pytest.mark.asyncio
async def test_project_module_named_functions_is_the_projects(tmp_path: Path) -> None:
    analyzer = _project(
        tmp_path,
        {
            "functions.py": "def helper():\n    return 1\n",
            "app.py": "import functions\n\nfunctions.helper()\n",
        },
    )
    resolved = await resolve("functions", analyzer)
    assert resolved["found"] is True, resolved
    assert resolved["scope"] == "project"
    assert Path(resolved["location"]["file"]).resolve() == (tmp_path / "functions.py").resolve()

    # goto from the import statement lands in the project, not in Jedi.
    at = await resolve_at((tmp_path / "app.py").as_posix(), 1, 7, analyzer)
    assert at["found"] is True, at
    assert at["handle"] == "functions"
    assert not _under_jedi(at["location"]["file"])

    imports = await expand("app", "imports", analyzer)
    stubs = {s["handle"]: s for s in imports["stubs"]}
    assert stubs["functions"]["scope"] == "project"

    helper = await resolve("functions.helper", analyzer)
    assert helper["found"] is True and helper["kind"] == "function"


@pytest.mark.asyncio
async def test_stdlib_and_site_packages_still_resolve(tmp_path: Path) -> None:
    analyzer = _project(tmp_path, {"pkg/__init__.py": ""})
    for name in ("__future__", "os", "functools", "jedi"):
        resolved = await resolve(name, analyzer)
        assert resolved["found"] is True, (name, resolved)
        assert resolved["scope"] == "external"


@pytest.mark.asyncio
async def test_src_layout_module_named_functions_resolves_to_the_project(tmp_path: Path) -> None:
    """Regression guard: a top-level ``functions`` in a ``src/`` layout is the project's.

    (Jedi's smart path puts ``src/`` ahead of the base path here, so this layout
    was not shadowed even before #722; a configured package outside the root
    was, see ``tests/unit/test_jedi_project.py``.)
    """
    analyzer = _project(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "demo"\n',
            "src/demo/__init__.py": "",
            "src/demo/app.py": "import functions\n\nfunctions.helper()\n",
            "src/functions.py": "def helper():\n    return 1\n",
        },
    )
    assert (tmp_path / "src").as_posix() in analyzer.project.added_sys_path
    resolved = await resolve("functions", analyzer)
    assert resolved["found"] is True, resolved
    assert resolved["scope"] == "project", resolved
    assert Path(resolved["location"]["file"]).resolve() == (tmp_path / "src/functions.py").resolve()
    at = await resolve_at((tmp_path / "src/demo/app.py").as_posix(), 1, 7, analyzer)
    assert at["found"] is True and not _under_jedi(at["location"]["file"]), at
    helper = await resolve("functions.helper", analyzer)
    assert helper["found"] is True and helper["kind"] == "function", helper
