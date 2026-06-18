"""Tests for the WorktreeRemove hook (worktree_remove.py).

The hook is fired by Claude Code's ``ExitWorktree``/cleanup flow for worktrees
this plugin created out-of-band. The harness delegates teardown entirely to the
hook (verified empirically — see issue #375), so the hook is responsible for the
actual ``git worktree remove`` and branch deletion.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from types import ModuleType

import pytest


def test_branch_for_worktree_returns_checked_out_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """It reports the branch a worktree has checked out."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/375-x", str(worktree))

    assert wtr.branch_for_worktree(repo, worktree) == "feat/375-x"


def test_branch_for_worktree_none_for_unregistered_path(
    wtr: ModuleType,
    repo: Path,
    tmp_path: Path,
) -> None:
    """It returns None when the path is not a registered worktree."""
    assert wtr.branch_for_worktree(repo, tmp_path / "does-not-exist") is None


def test_remove_worktree_removes_directory_and_registration(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """It deletes the worktree directory and deregisters it from git."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/r", str(worktree))
    assert worktree.exists()

    assert wtr.remove_worktree(repo, worktree) is True
    assert not worktree.exists()
    assert wtr.branch_for_worktree(repo, worktree) is None


def test_remove_worktree_force_removes_dirty_worktree(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """It removes a worktree even with uncommitted changes (consent given)."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/dirty", str(worktree))
    (worktree / "scratch.txt").write_text("uncommitted\n")  # would block plain remove

    assert wtr.remove_worktree(repo, worktree) is True
    assert not worktree.exists()


def test_delete_branch_deletes_merged_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
) -> None:
    """It deletes a branch that holds no unmerged commits."""
    run_git(repo, "branch", "feat/merged")  # points at main HEAD → fully merged

    assert wtr.delete_branch(repo, "feat/merged") is True
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/merged") is False


def test_delete_branch_refuses_unmerged_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """It refuses to delete a branch with unmerged commits, preserving the work."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/unmerged", str(worktree))
    (worktree / "wip.txt").write_text("work in progress\n")
    run_git(worktree, "add", ".")
    run_git(worktree, "commit", "-m", "wip")
    run_git(repo, "worktree", "remove", "--force", str(worktree))

    assert wtr.delete_branch(repo, "feat/unmerged") is False
    # The branch (and its unmerged commit) must survive.
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/unmerged") is True


def test_process_removal_removes_worktree_and_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """End to end: a clean hook-created worktree is fully torn down."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/375-done", str(worktree))

    assert wtr.process_removal(str(worktree)) == 0
    assert not worktree.exists()
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/375-done") is False


def test_process_removal_preserves_unmerged_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """The worktree is removed but a branch with unmerged work is kept."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/wip", str(worktree))
    (worktree / "wip.txt").write_text("unmerged\n")
    run_git(worktree, "add", ".")
    run_git(worktree, "commit", "-m", "wip")

    assert wtr.process_removal(str(worktree)) == 0
    assert not worktree.exists()
    # Work preserved: branch (and its commit) still exists.
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/wip") is True


def test_process_removal_idempotent_when_already_removed(
    wtr: ModuleType,
    tmp_path: Path,
) -> None:
    """A path that is not a worktree (e.g. already removed) is a no-op, not a crash."""
    assert wtr.process_removal(str(tmp_path / "never-existed")) == 0


def test_read_input_extracts_worktree_path(
    wtr: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It parses the WorktreeRemove JSON payload from stdin."""
    payload = {"hook_event_name": "WorktreeRemove", "worktree_path": "/x/y"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    assert wtr.read_input() == payload


def test_main_end_to_end(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() reads stdin and tears the worktree down, returning 0."""
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/main-e2e", str(worktree))
    payload = {"hook_event_name": "WorktreeRemove", "worktree_path": str(worktree)}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(wtr, "setup_logging", lambda: None)  # keep tests hermetic

    assert wtr.main() == 0
    assert not worktree.exists()
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/main-e2e") is False


def test_main_returns_error_when_worktree_path_missing(
    wtr: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() returns non-zero on a payload with no worktree_path."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "WorktreeRemove"})))
    monkeypatch.setattr(wtr, "setup_logging", lambda: None)

    assert wtr.main() == 1


def _git_ok(
    run_git: Callable[..., CompletedProcess[str]],
    repo: Path,
    *args: str,
) -> bool:
    """Return whether a git command succeeds (rc == 0), without raising."""
    import subprocess

    try:
        run_git(repo, *args)
        return True
    except subprocess.CalledProcessError:
        return False
