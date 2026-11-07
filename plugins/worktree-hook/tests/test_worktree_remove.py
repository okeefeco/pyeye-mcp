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


# ---------------------------------------------------------------------------
# Squash-merge detection (#607)
#
# Under squash merge a merged branch's commits never reach main, so the safe
# ``git branch -d`` always refuses. The hook recognises a squash merge when the
# branch's combined change has the same patch-id as one commit on the default
# branch, and only then deletes with ``-D``. Anything else is kept.
# ---------------------------------------------------------------------------


def _commit_file(
    run_git: Callable[..., CompletedProcess[str]], where: Path, name: str, text: str, msg: str
) -> None:
    (where / name).write_text(text)
    run_git(where, "add", name)
    run_git(where, "commit", "-m", msg)


def _squash_merge(run_git: Callable[..., CompletedProcess[str]], repo: Path, branch: str) -> None:
    """Squash-merge ``branch`` into ``main`` the way GitHub does (one new commit)."""
    run_git(repo, "merge", "--squash", branch)
    run_git(repo, "commit", "-m", f"squash {branch}")


def _feature_branch_with_two_commits(
    run_git: Callable[..., CompletedProcess[str]], repo: Path, tmp_path: Path, branch: str
) -> Path:
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", branch, str(worktree))
    _commit_file(run_git, worktree, "a.txt", "one\n", "first")
    _commit_file(run_git, worktree, "b.txt", "two\n", "second")
    return worktree


def test_delete_branch_deletes_squash_merged_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """A multi-commit branch squash-merged into main is recognised and deleted."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-squashed")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    _squash_merge(run_git, repo, "feat/607-squashed")

    assert wtr.delete_branch(repo, "feat/607-squashed") is True
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/607-squashed") is False


def test_delete_branch_squash_detected_after_main_moved_on(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Detection still works when unrelated commits landed on main after the squash."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-later")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    _squash_merge(run_git, repo, "feat/607-later")
    _commit_file(run_git, repo, "other.txt", "unrelated\n", "someone else's PR")

    assert wtr.delete_branch(repo, "feat/607-later") is True


def test_delete_branch_keeps_branch_with_commits_after_squash(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Work committed after the squash merge is unmerged, so the branch is kept."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-more")
    _squash_merge(run_git, repo, "feat/607-more")
    _commit_file(run_git, worktree, "c.txt", "follow-up\n", "not merged yet")
    run_git(repo, "worktree", "remove", "--force", str(worktree))

    assert wtr.delete_branch(repo, "feat/607-more") is False
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/607-more") is True


def test_delete_branch_keeps_branch_when_squash_content_differs(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """If the change was altered while merging, there is no exact match: keep it."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-edited")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    run_git(repo, "merge", "--squash", "feat/607-edited")
    (repo / "b.txt").write_text("two, edited during merge\n")
    run_git(repo, "add", "b.txt")
    run_git(repo, "commit", "-m", "squash with edits")

    assert wtr.delete_branch(repo, "feat/607-edited") is False


def test_delete_branch_keeps_unmerged_branch_even_with_no_main(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """With no default branch to compare against, unmerged work is kept."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-orphan")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    run_git(repo, "checkout", "-q", "-b", "trunk")
    run_git(repo, "branch", "-D", "main")

    assert wtr.delete_branch(repo, "feat/607-orphan") is False


def test_default_branch_refs_prefers_origin_head(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
) -> None:
    """origin/HEAD's target is checked first, then local main."""
    run_git(repo, "update-ref", "refs/remotes/origin/trunk", "main")
    run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")

    assert wtr.default_branch_refs(repo) == ["refs/remotes/origin/trunk", "refs/heads/main"]


def test_delete_branch_squash_detected_via_origin_head_only(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """A squash that exists only on the remote default branch (local main stale) is found."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-remote")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    stale_main = run_git(repo, "rev-parse", "main").stdout.strip()
    _squash_merge(run_git, repo, "feat/607-remote")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "main")
    run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    run_git(repo, "reset", "-q", "--hard", stale_main)  # local main never pulled

    assert wtr.delete_branch(repo, "feat/607-remote") is True


def test_delete_branch_merge_commit_on_remote_with_stale_local_main(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """A merge-commit merge that only the remote default branch has is recognised.

    ``git branch -d`` checks against HEAD, which here is a stale local main.
    """
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-mc")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    stale_main = run_git(repo, "rev-parse", "main").stdout.strip()
    run_git(repo, "merge", "--no-ff", "-m", "Merge pull request #1", "feat/607-mc")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "main")
    run_git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    run_git(repo, "reset", "-q", "--hard", stale_main)

    assert wtr.delete_branch(repo, "feat/607-mc") is True


def test_delete_branch_merge_commit_when_main_checkout_on_other_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Merged into main, but the main checkout's HEAD is elsewhere: still deleted."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-head")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    run_git(repo, "merge", "--no-ff", "-m", "merge", "feat/607-head")
    run_git(repo, "checkout", "-q", "-b", "unrelated", "HEAD~1")

    assert wtr.delete_branch(repo, "feat/607-head") is True


def test_delete_branch_rebase_merged_multi_commit_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """A rebase merge copies each commit onto main; all equivalents present → deleted."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-rebased")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    _commit_file(run_git, repo, "other.txt", "moved on\n", "main moved on")  # forces new SHAs
    run_git(repo, "cherry-pick", "main..feat/607-rebased")

    assert wtr.delete_branch(repo, "feat/607-rebased") is True


def test_delete_branch_keeps_partially_rebased_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Only some commits have equivalents on main: the rest are unmerged, so keep it."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-partial")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    _commit_file(run_git, repo, "other.txt", "moved on\n", "main moved on")
    first = run_git(repo, "rev-parse", "feat/607-partial~1").stdout.strip()
    run_git(repo, "cherry-pick", first)

    assert wtr.delete_branch(repo, "feat/607-partial") is False


def test_delete_branch_squash_detected_on_master_default(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """Generic plugin: a repo whose default branch is ``master`` works too."""
    run_git(repo, "branch", "-m", "main", "master")
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/607-master", str(worktree))
    _commit_file(run_git, worktree, "a.txt", "one\n", "first")
    _commit_file(run_git, worktree, "b.txt", "two\n", "second")
    run_git(repo, "worktree", "remove", "--force", str(worktree))
    run_git(repo, "merge", "--squash", "feat/607-master")
    run_git(repo, "commit", "-m", "squash")

    assert wtr.default_branch_refs(repo) == ["refs/heads/master"]
    assert wtr.delete_branch(repo, "feat/607-master") is True


def test_process_removal_deletes_squash_merged_branch(
    wtr: ModuleType,
    repo: Path,
    run_git: Callable[..., CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    """End to end: tearing down a squash-merged worktree also removes its branch."""
    worktree = _feature_branch_with_two_commits(run_git, repo, tmp_path, "feat/607-e2e")
    _squash_merge(run_git, repo, "feat/607-e2e")

    assert wtr.process_removal(str(worktree)) == 0
    assert not worktree.exists()
    assert _git_ok(run_git, repo, "rev-parse", "--verify", "refs/heads/feat/607-e2e") is False


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
