"""Tests for :func:`pyeye._jedi_project.make_project` (#722).

The helper builds every ``jedi.Project`` pyeye uses.  It drops Jedi's own
package directory from the environment's base ``sys.path`` and changes nothing
else: order is kept, and Jedi still adds ``smart_sys_path`` (the project root)
and ``added_sys_path`` on top of the base path.
"""

from __future__ import annotations

from pathlib import Path

import jedi

from pyeye._jedi_project import is_jedi_private_path, make_project

_JEDI_DIR = Path(jedi.__file__).resolve().parent


def _base(project: jedi.Project) -> list[str]:
    raw = project._sys_path  # explicit base path (None = Jedi computes it)
    assert raw is not None
    return list(raw)


def test_base_sys_path_drops_only_jedis_own_directory(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    env_path = [p for p in project.get_environment().get_sys_path() if p]
    expected = [p for p in env_path if not Path(p).resolve().is_relative_to(_JEDI_DIR)]
    assert len(expected) < len(env_path), "precondition: Jedi leaks its subprocess dir"
    assert _base(project) == expected


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
