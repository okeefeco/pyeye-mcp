"""Test fixtures for the worktree-hook plugin.

This suite is intentionally separate from the main ``pyeye`` test suite: the
plugin is a standalone set of hook scripts shipped under ``CLAUDE_PLUGIN_ROOT``,
not part of the ``pyeye`` package. Run it with::

    uv run pytest plugins/worktree-hook/tests --no-cov

The hook scripts are loaded by file path (they are not importable modules), and
the fixtures build real throwaway git repositories so the tests exercise actual
``git worktree`` behaviour rather than mocks.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_hook(name: str) -> ModuleType:
    """Load a sibling hook script (e.g. ``worktree_remove``) by file path."""
    path = PLUGIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wtr() -> ModuleType:
    """The ``worktree_remove`` hook module under test."""
    return _load_hook("worktree_remove")


@pytest.fixture
def wtc() -> ModuleType:
    """The ``worktree_create`` hook module under test."""
    return _load_hook("worktree_create")


@pytest.fixture
def run_git() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run a git command in a repo, raising on failure (test setup helper)."""

    def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )

    return _run


@pytest.fixture
def repo(tmp_path: Path, run_git: Callable[..., subprocess.CompletedProcess[str]]) -> Path:
    """A fresh git repo on ``main`` with a single initial commit."""
    root = tmp_path / "main"
    root.mkdir()
    run_git(root, "init", "-b", "main")
    run_git(root, "config", "user.email", "test@example.com")
    run_git(root, "config", "user.name", "Test User")
    (root / "README.md").write_text("init\n")
    run_git(root, "add", ".")
    run_git(root, "commit", "-m", "init")
    return root
