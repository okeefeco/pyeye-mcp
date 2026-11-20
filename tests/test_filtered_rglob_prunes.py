"""``filtered_rglob`` prunes excluded directories, with the same result as filtering (#738).

It used to walk everything with ``Path.rglob`` (``.venv`` included) and drop
excluded paths afterwards: 0.9 s on the pyeye repo. It now prunes them during
the walk (27 ms). The file set must be identical for every pattern the callers
use: this pins the new walk against the old rule, kept here as the reference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.async_utils import _is_linked_worktree, filtered_rglob
from pyeye.constants import EXCLUDED_DIRS

WORKTREE_GITDIR = "gitdir: /elsewhere/.git/worktrees/feature\n"


def _reference(pattern: str, path: Path) -> list[Path]:
    """The pre-#738 rule: walk everything, then filter (#507, #515, #517)."""
    results = []
    for p in path.rglob(pattern):
        rel_parts = p.relative_to(path).parts
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in rel_parts):
            continue
        parents = [q for q in p.parents if q != path and path in q.parents]
        if any(_is_linked_worktree(q) for q in parents):
            continue
        results.append(p)
    return results


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    # An ancestor named like an excluded dir must not exclude the project (#515).
    root = tmp_path / "build" / "proj"
    files = [
        "app/__init__.py",
        "app/models.py",
        "app/views.py",
        "app/migrations/0001_initial.py",
        "app/templates/index.html",
        "app/static/site.css",
        "deep/a/b/c/models.py",
        ".venv/lib/site-packages/pkg/models.py",
        "app/__pycache__/models.cpython-312.py",
        "thing.egg-info/models.py",
        "build/out/models.py",
        ".claude/worktrees/feature/app/models.py",
        "vendor/library/libapp/models.py",
    ]
    for rel in files:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("X = 1\n")
    (root / ".claude" / "worktrees" / "feature" / ".git").write_text(WORKTREE_GITDIR)
    return root


@pytest.mark.parametrize(
    "pattern", ["*.py", "models.py", "migrations/*.py", "templates", "static", "*.html"]
)
def test_same_paths_as_walk_then_filter(tree: Path, pattern: str) -> None:
    assert sorted(filtered_rglob(pattern, tree)) == sorted(_reference(pattern, tree))


def test_excluded_and_nested_worktree_paths_are_absent(tree: Path) -> None:
    found = {p.relative_to(tree).as_posix() for p in filtered_rglob("models.py", tree)}

    assert found == {"app/models.py", "deep/a/b/c/models.py", "vendor/library/libapp/models.py"}


def test_excluded_directories_are_never_entered(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruned, not filtered: the walk never lists an excluded directory's contents."""
    import os

    listed: list[str] = []
    real_walk = os.walk

    def spying_walk(top: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):  # type: ignore[arg-type]
            listed.append(Path(dirpath).relative_to(tree).as_posix())
            yield dirpath, dirnames, filenames

    monkeypatch.setattr("pyeye.async_utils.os.walk", spying_walk)
    filtered_rglob("*.py", tree)

    # ``.claude/worktrees`` itself is ordinary; the linked worktree under it is pruned.
    pruned = (".venv", ".claude/worktrees/feature", "thing.egg-info", "build")
    assert not [d for d in listed if d.startswith(pruned)]
    assert not [d for d in listed if "__pycache__" in d]


class TestSeveralPatterns:
    """Several patterns are matched in ONE walk (#933): a walk per suffix doubled scan costs."""

    def test_the_result_is_the_union_of_single_pattern_calls(self, tree: Path) -> None:
        (tree / "app" / "declared.pyi").write_text("X: int\n", encoding="utf-8")
        together = filtered_rglob(("*.py", "*.pyi"), tree)
        apart = filtered_rglob("*.py", tree) + filtered_rglob("*.pyi", tree)

        assert sorted(together) == sorted(apart)
        assert any(p.suffix == ".pyi" for p in together)

    def test_the_tree_is_walked_once(self, tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pyeye.async_utils as async_utils

        walks: list[Path] = []
        real = async_utils.pruned_walk

        def counting(path: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            walks.append(path)
            return real(path, *args, **kwargs)

        monkeypatch.setattr(async_utils, "pruned_walk", counting)
        filtered_rglob(("*.py", "*.pyi"), tree)

        assert walks == [tree]
