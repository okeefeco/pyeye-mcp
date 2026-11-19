"""Tests for :func:`pyeye._jedi_project.make_project` (#722).

The helper builds every ``jedi.Project`` pyeye uses.  It drops Jedi's own
package directory from the environment's base ``sys.path`` and changes nothing
else: order is kept, and Jedi still adds ``smart_sys_path`` (the project root)
and ``added_sys_path`` on top of the base path.
"""

from __future__ import annotations

from pathlib import Path

import jedi
import pytest

from pyeye import _jedi_project
from pyeye._jedi_project import is_jedi_private_path, make_project

_JEDI_DIR = Path(jedi.__file__).resolve().parent


def _base(project: jedi.Project) -> list[str]:
    raw = project._sys_path  # explicit base path (None = Jedi computes it)
    assert raw is not None
    return list(raw)


def test_base_sys_path_is_the_interpreters_stdlib_without_jedis_directory(
    tmp_path: Path,
) -> None:
    """Jedi's own directory (#722) and pyeye's own site-packages (#993) are both dropped."""
    import sys

    project = make_project(tmp_path)
    env_path = [p for p in project.get_environment().get_sys_path() if p]
    assert any(
        Path(p).resolve().is_relative_to(_JEDI_DIR) for p in env_path
    ), "precondition: Jedi leaks its subprocess dir"
    assert any("site-packages" in Path(p).parts for p in env_path), "precondition"
    base = _base(project)

    assert base, "the standard library stays"
    assert not any(Path(p).resolve().is_relative_to(_JEDI_DIR) for p in base)
    assert not any("site-packages" in Path(p).parts for p in base)
    assert all(Path(p).resolve().is_relative_to(Path(sys.base_prefix).resolve()) for p in base)


def test_project_root_and_added_paths_still_apply(tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    (extra / "addedpkg").mkdir(parents=True)
    (extra / "addedpkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "localmod.py").write_text("LOCAL = 2\n", encoding="utf-8")

    project = make_project(root, added_sys_path=[extra.as_posix()])
    assert project.added_sys_path == [extra.as_posix()]
    script = jedi.Script(code="import localmod\nimport addedpkg\n", project=project)
    local = script.goto(1, 9, follow_imports=True)
    added = script.goto(2, 9, follow_imports=True)
    assert local and Path(local[0].module_path).resolve() == (root / "localmod.py").resolve()
    assert added and Path(added[0].module_path).resolve().parent == (extra / "addedpkg").resolve()


def test_is_jedi_private_path() -> None:
    assert is_jedi_private_path(str(_JEDI_DIR / "inference" / "compiled" / "subprocess"))
    assert not is_jedi_private_path(str(_JEDI_DIR.parent))
    assert not is_jedi_private_path("")


def test_configured_package_is_not_shadowed_by_jedis_directory(tmp_path: Path) -> None:
    """A module reachable only through ``added_sys_path`` sits AFTER the base path.

    With Jedi's directory in the base path, ``import functions`` landed on Jedi's
    private ``subprocess/functions.py`` instead of the configured package's.
    """
    extra = tmp_path / "configured"
    extra.mkdir()
    (extra / "functions.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "app.py").write_text("import functions\n", encoding="utf-8")

    project = make_project(root, added_sys_path=[extra.as_posix()])
    script = jedi.Script(path=root / "app.py", project=project)
    (target,) = script.goto(1, 9, follow_imports=True)
    assert Path(target.module_path).resolve() == (extra / "functions.py").resolve()


def test_an_unreadable_interpreter_path_leaves_only_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analysis never fails over the filter, and never falls back to pyeye's own path (#993)."""

    class Unreadable:
        def get_sys_path(self) -> list[str]:
            raise RuntimeError("no environment")

    monkeypatch.setattr(_jedi_project, "own_environment", Unreadable)
    project = make_project(tmp_path, added_sys_path=["/x"], environment_paths=["/venv/site"])
    assert project._sys_path == ["/venv/site"]
    assert project.added_sys_path == ["/x"]


def test_unresolvable_entry_is_not_private() -> None:
    assert not is_jedi_private_path("bad\0path")
