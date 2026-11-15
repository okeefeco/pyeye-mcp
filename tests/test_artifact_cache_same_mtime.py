"""A rewrite that keeps the mtime must not be served from the old parse (#731).

``file_artifact_cache`` keyed every entry on ``(path, mtime_ns)``. Two writes
inside the filesystem's mtime resolution (2 s on FAT/exFAT, coarse on some
network and VM shares) kept the key, so the stale AST / ``jedi.Script`` was
served, silently. The key now includes ``st_size`` from the same ``os.stat``.
"""

from __future__ import annotations

import os
from pathlib import Path

import jedi

from pyeye.file_artifact_cache import FileArtifactCache


def _rewrite_keeping_mtime(path: Path, text: str) -> None:
    before = path.stat()
    path.write_text(text)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_mtime_ns == before.st_mtime_ns


def test_ast_is_reparsed_when_the_size_changes_within_one_mtime(tmp_path: Path) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text("class Old:\n    pass\n")
    cache = FileArtifactCache(ast_max_entries=10)
    assert [n.name for n in cache.get_ast(mod).body] == ["Old"]

    _rewrite_keeping_mtime(mod, "class New:\n    pass\n\n\nclass Extra:\n    pass\n")

    assert [n.name for n in cache.get_ast(mod).body] == ["New", "Extra"]


def test_script_is_rebuilt_when_the_size_changes_within_one_mtime(tmp_path: Path) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text("class Old:\n    pass\n")
    cache = FileArtifactCache(ast_max_entries=10)
    project = jedi.Project(tmp_path)
    assert [n.name for n in cache.get_script(mod, project).get_names()] == ["Old"]

    _rewrite_keeping_mtime(mod, "class New:\n    pass\n\n\nclass Extra:\n    pass\n")

    assert [n.name for n in cache.get_script(mod, project).get_names()] == ["New", "Extra"]


def test_unchanged_file_is_still_a_hit(tmp_path: Path) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text("X = 1\n")
    cache = FileArtifactCache(ast_max_entries=10)

    first = cache.get_ast(mod)

    assert cache.get_ast(mod) is first
    assert cache.stats()["hits"] == 1
