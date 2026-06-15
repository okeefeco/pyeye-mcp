#!/usr/bin/env python3
"""WorktreeRemove hook for Claude Code.

Companion to ``worktree_create.py``. Claude Code's ``ExitWorktree``/cleanup flow
fires a ``WorktreeRemove`` hook for worktrees this plugin created out-of-band and
delegates teardown *entirely* to the hook — the harness itself removes nothing
(verified empirically; see issue #375). Without this hook the worktree directory,
its ``git worktree`` registration, and its branch are all left behind.

Input (JSON via stdin):
    session_id: str - Current session identifier
    cwd: str - Current working directory
    hook_event_name: str - Always "WorktreeRemove"
    worktree_path: str - Absolute path to the worktree being removed

Behaviour:
    1. Resolve the main repo root from the worktree path.
    2. Determine the worktree's branch *before* removal (removal invalidates it).
    3. ``git worktree remove --force`` the worktree directory.
    4. ``git branch -d`` the branch — the *safe* delete: if the branch holds
       unmerged commits git refuses, and we leave it in place rather than
       destroy work. The user can ``git branch -D`` deliberately.

Output:
    All logging goes to stderr and a log file (never stdout). Per Claude Code's
    contract a WorktreeRemove hook cannot block removal, so the exit code is
    advisory; we return 0 on success and 1 only on an internal error.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

LOG_FILE = Path.home() / ".claude" / "logs" / "worktree-remove.log"

logger = logging.getLogger("worktree-remove")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command, logging the invocation and result."""
    cmd = ["git", *args]
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd or ".")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    if result.returncode != 0:
        logger.debug("git stderr: %s", result.stderr.strip())
    return result


def find_main_repo_root(cwd: str) -> Path | None:
    """Find the main git repo root, even if cwd is inside a worktree.

    Uses git's common-dir to resolve back to the main repo when invoked from
    within a worktree (which is exactly the case at removal time). Returns None
    if ``cwd`` no longer exists (e.g. the worktree was already removed), so the
    caller can treat that as a no-op rather than crashing.
    """
    if not Path(cwd).is_dir():
        logger.info("Path does not exist, cannot resolve repo: %s", cwd)
        return None

    result = git("rev-parse", "--show-toplevel", cwd=cwd)
    if result.returncode != 0:
        return None
    toplevel = Path(result.stdout.strip())

    git_dir = git("rev-parse", "--git-dir", cwd=cwd)
    common_dir = git("rev-parse", "--git-common-dir", cwd=cwd)

    if git_dir.returncode == 0 and common_dir.returncode == 0:
        git_dir_path = Path(git_dir.stdout.strip()).resolve()
        common_dir_path = Path(common_dir.stdout.strip()).resolve()
        if git_dir_path != common_dir_path:
            main_root = common_dir_path.parent
            logger.info(
                "CWD is inside a worktree (%s), resolved main repo: %s",
                toplevel,
                main_root,
            )
            return main_root

    return toplevel


def branch_for_worktree(repo_root: Path, worktree_path: Path) -> str | None:
    """Return the branch checked out in ``worktree_path``, or None.

    Parses ``git worktree list --porcelain`` and matches on the *resolved* path
    so symlinked temp dirs (e.g. macOS ``/var`` -> ``/private/var``) compare
    equal. Returns None for an unregistered path or a detached HEAD.
    """
    target = Path(worktree_path).resolve()
    result = git("worktree", "list", "--porcelain", cwd=str(repo_root))
    if result.returncode != 0:
        return None

    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[len("worktree ") :]).resolve()
        elif line.startswith("branch refs/heads/") and current_path is not None:
            if current_path == target:
                return line[len("branch refs/heads/") :]
    return None


def remove_worktree(repo_root: Path, worktree_path: Path) -> bool:
    """Remove the worktree directory and deregister it from git.

    Uses ``--force`` because by the time this hook fires the harness has already
    obtained the user's consent to remove (Claude Code only dispatches
    WorktreeRemove once removal is proceeding), so uncommitted changes in the
    worktree should not block teardown. Returns True on success.
    """
    result = git("worktree", "remove", "--force", str(worktree_path), cwd=str(repo_root))
    if result.returncode != 0:
        logger.error("Failed to remove worktree %s: %s", worktree_path, result.stderr.strip())
        return False
    logger.info("Removed worktree: %s", worktree_path)
    return True


def delete_branch(repo_root: Path, branch: str) -> bool:
    """Delete ``branch`` with the *safe* ``git branch -d``.

    A plain ``-d`` refuses to drop a branch that holds commits not merged into
    its upstream/HEAD. We deliberately do NOT fall back to ``-D``: if the branch
    still has unmerged work we leave it in place and let the user remove it
    deliberately, rather than silently destroying commits. Returns True only if
    the branch was actually deleted.
    """
    result = git("branch", "-d", branch, cwd=str(repo_root))
    if result.returncode != 0:
        logger.warning(
            "Kept branch %r (likely unmerged commits); not deleting: %s",
            branch,
            result.stderr.strip(),
        )
        return False
    logger.info("Deleted branch: %s", branch)
    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def process_removal(worktree_path_str: str) -> int:
    """Tear down the worktree at ``worktree_path_str`` and its branch.

    Idempotent: if the path is not a live worktree (e.g. already removed) this
    is a no-op. The branch is resolved *before* removal because removal
    invalidates the worktree's git metadata. Always returns 0 — per Claude
    Code's contract a WorktreeRemove hook cannot block removal, so failures are
    logged rather than surfaced as a blocking error.
    """
    worktree_path = Path(worktree_path_str)

    repo_root = find_main_repo_root(worktree_path_str)
    if repo_root is None:
        logger.info(
            "No git repo resolvable from %s (already removed?); nothing to do",
            worktree_path,
        )
        return 0

    branch = branch_for_worktree(repo_root, worktree_path)
    logger.info("Removing worktree %s (branch=%s)", worktree_path, branch)

    remove_worktree(repo_root, worktree_path)
    if branch:
        delete_branch(repo_root, branch)

    return 0


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    """Configure logging to file and stderr (never stdout)."""
    logger.setLevel(logging.DEBUG)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


def read_input() -> dict:
    """Read JSON input from stdin."""
    raw = sys.stdin.read()
    logger.debug("Raw input: %s", raw)
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Remove the worktree described by the JSON request on stdin."""
    setup_logging()
    logger.info("WorktreeRemove hook invoked")

    try:
        data = read_input()
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read input: %s", e)
        return 1

    worktree_path = data.get("worktree_path", "")
    session_id = data.get("session_id", "")
    logger.info("worktree_path=%s session_id=%s", worktree_path, session_id)

    if not worktree_path:
        logger.error("No worktree_path provided")
        return 1

    return process_removal(worktree_path)


if __name__ == "__main__":
    sys.exit(main())
