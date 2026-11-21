"""A module named like its own namespace doesn't hide the namespace (#1079).

Poetry's ``src/poetry/`` is a PEP 420 namespace (no ``__init__.py``) holding a
module named after it, ``src/poetry/poetry.py``. Jedi's "smart" sys path walks
up from the file it analyses, skipping directories with an ``__init__.py``,
and appends the first one without: here ``src/poetry``. On that path ``import
poetry`` finds ``src/poetry/poetry.py``, a regular module, which beats the
namespace package in ``src`` (PEP 420), so no ``poetry.*`` import resolved from
a file inside the namespace: ``imports``, ``callees`` and ``superclasses`` came
back empty.

``_jedi_project.make_project`` now builds a Project that drops such a walk entry:
a directory strictly inside one of the project's import roots (``src``, a
configured package) is part of a package, never an import root of its own.
Flat layouts, whose root is the project itself, keep Jedi's walk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import jedi
import pytest

from pyeye import _jedi_project
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig
from pyeye.mcp.operations.expand import expand

FILES = {
    "src/pkg/pkg.py": "class Pkg:\n    pass\n",  # named like its namespace: the shadow
    "src/pkg/a/__init__.py": "",
    "src/pkg/a/x.py": (
        "from pkg.b.y import Base, f\n\n\n"
        "class Child(Base):\n    pass\n\n\n"
        "def g():\n    return f()\n"
    ),
    "src/pkg/b/__init__.py": "",
    "src/pkg/b/y.py": "class Base:\n    pass\n\n\ndef f():\n    return 1\n",
}


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.fixture(params=["configured", "declared"])
def shadowed(request: pytest.FixtureRequest, tmp_path: Path) -> JediAnalyzer:
    """The layout two ways: ``packages: ["src"]``, or no config and the project's declared name.

    The second is #1078's rule: ``src/`` is a source root when it holds the
    package ``pyproject.toml`` names, here a namespace (``src/pkg``, no
    ``__init__.py``), as Poetry's is.
    """
    _write(tmp_path, FILES)
    if request.param == "configured":
        config_file = tmp_path / ".pyeye.json"
        config_file.write_text(json.dumps({"packages": ["src"]}), encoding="utf-8")
        return JediAnalyzer(tmp_path.as_posix(), config=ProjectConfig(tmp_path.as_posix()))
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pkg"\nversion = "0"\n', encoding="utf-8"
    )
    return JediAnalyzer(tmp_path.as_posix())


def _handles(result: dict[str, Any]) -> list[str]:
    return [s["handle"] for s in result.get("stubs") or []]


class TestImportsAcrossTheNamespace:
    async def test_imports(self, shadowed: JediAnalyzer) -> None:
        result = await expand("pkg.a.x", "imports", shadowed)
        assert sorted(_handles(result)) == ["pkg.b.y.Base", "pkg.b.y.f"]
        assert result["unresolved_imports"] == []

    async def test_callees(self, shadowed: JediAnalyzer) -> None:
        result = await expand("pkg.a.x.g", "callees", shadowed)
        assert _handles(result) == ["pkg.b.y.f"]
        assert result["unresolved_call_sites"] == 0

    async def test_superclasses(self, shadowed: JediAnalyzer) -> None:
        result = await expand("pkg.a.x.Child", "superclasses", shadowed)
        assert _handles(result) == ["pkg.b.y.Base"]


async def test_a_flat_layout_keeps_jedis_walk(tmp_path: Path) -> None:
    """A loose script imports its sibling through the walk's entry for its folder."""
    _write(
        tmp_path,
        {
            "scripts/run.py": "from helper import assist\n\n\ndef main():\n    return assist()\n",
            "scripts/helper.py": "def assist():\n    return 1\n",
        },
    )
    analyzer = JediAnalyzer(tmp_path.as_posix())
    result = await expand("scripts.run.main", "callees", analyzer)
    assert len(_handles(result)) == 1
    assert _handles(result)[0].endswith("helper.assist")
    assert result["unresolved_call_sites"] == 0


class TestTheJediHook:
    """``jedi.Project._get_sys_path`` is private: pin it, as #1048 pins its hook."""

    def test_the_hook_exists_and_is_overridden(self, tmp_path: Path) -> None:
        assert callable(getattr(jedi.Project, "_get_sys_path", None))
        project = _jedi_project.make_project(
            tmp_path, added_sys_path=[(tmp_path / "src").as_posix()]
        )
        assert getattr(project._get_sys_path, "__pyeye_import_roots__", False)

    def test_inner_walk_entries_are_dropped_and_explicit_ones_kept(self, tmp_path: Path) -> None:
        _write(tmp_path, FILES)
        src = (tmp_path / "src").resolve()
        nested = src / "pkg" / "b"  # a configured root inside another root: explicit, kept
        project = _jedi_project.make_project(
            tmp_path.resolve(), added_sys_path=[src.as_posix(), nested.as_posix()]
        )
        script = jedi.Script(path=src / "pkg/a/x.py", project=project)
        paths = [Path(p).as_posix() for p in script._inference_state.get_sys_path()]
        assert (src / "pkg").as_posix() not in paths  # the walk's shadowing entry
        assert src.as_posix() in paths
        assert nested.as_posix() in paths
        assert tmp_path.resolve().as_posix() in paths  # the project root

    def test_a_missing_hook_falls_back_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(_jedi_project, "_HAS_SYS_PATH_HOOK", False)
        with caplog.at_level(logging.WARNING, logger="pyeye._jedi_project"):
            project = _jedi_project.make_project(tmp_path, added_sys_path=[tmp_path.as_posix()])
        assert not getattr(project._get_sys_path, "__pyeye_import_roots__", False)
        assert "#1079" in caplog.text
