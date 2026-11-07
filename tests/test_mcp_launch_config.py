"""Regression tests for how the pyeye MCP server is launched (#600).

The repo's ``.mcp.json`` starts the server with ``uv run``.  It used
``--no-sync``, left over from the plugin config (#600): in a new worktree there
is no ``.venv``, so ``uv run`` created an EMPTY one, ``--no-sync`` stopped it
from installing anything, and ``python -m pyeye.mcp`` exited with ``No module
named 'pyeye'`` — Claude Code reported ``CONNECTION_CLOSED`` and the server
stayed down for the whole session.

The rule these tests pin: ``--no-sync`` is safe only where something else fills
the venv first.  The plugin does that (its SessionStart hook runs
``scripts/install_plugin_deps.py`` into ``UV_PROJECT_ENVIRONMENT``); the repo's
``.mcp.json`` has no such step, so it must sync itself — with ``--frozen``,
which installs exactly ``uv.lock`` and never re-resolves (the project's
``uv sync --frozen`` rule; ``--locked`` is CI-only).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 — launches uv/git with fixed argument lists
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_MCP_JSON = _REPO / ".mcp.json"
_PLUGIN_JSON = _REPO / ".claude-plugin" / "plugin.json"
_PLUGIN_HOOKS = _REPO / "hooks" / "hooks.json"


def _server(config: Path) -> dict:
    return json.loads(config.read_text(encoding="utf-8"))["mcpServers"]["pyeye"]


class TestRepoMcpJson:
    def test_runs_pyeye_through_uv(self) -> None:
        server = _server(_MCP_JSON)
        assert server["command"] == "uv"
        assert server["args"][0] == "run"
        assert server["args"][-3:] == ["python", "-m", "pyeye.mcp"]

    def test_targets_the_session_project(self) -> None:
        # Each worktree must run ITS OWN code, so verify-on-a-branch tests the
        # branch, not the main checkout.
        args = _server(_MCP_JSON)["args"]
        assert args[args.index("--project") + 1] == "${CLAUDE_PROJECT_DIR:-.}"

    def test_syncs_frozen_rather_than_no_sync(self) -> None:
        args = _server(_MCP_JSON)["args"]
        assert "--no-sync" not in args, (
            "nothing fills a new worktree's venv before the server starts, so "
            "--no-sync leaves it empty and the server cannot import pyeye (#600)"
        )
        assert "--frozen" in args, "install exactly uv.lock without re-resolving it"
        assert "--locked" not in args, "--locked is for CI only"


class TestPluginNoSyncIsBacked:
    def test_plugin_no_sync_has_a_sync_step(self) -> None:
        # The plugin keeps --no-sync on purpose: guard the conditions that make
        # it safe, so the #600 failure can't reappear there.
        server = _server(_PLUGIN_JSON)
        if "--no-sync" not in server["args"]:
            pytest.skip("plugin syncs itself; nothing to guard")
        assert "--frozen" in server["args"]
        assert server.get("env", {}).get(
            "UV_PROJECT_ENVIRONMENT"
        ), "--no-sync needs a dedicated venv that something else fills"
        hooks = json.loads(_PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"]
        commands = [h["command"] for entry in hooks["SessionStart"] for h in entry["hooks"]]
        assert any(
            "install_plugin_deps.py" in c for c in commands
        ), "--no-sync needs the SessionStart hook that installs the plugin's deps"


@pytest.mark.slow
@pytest.mark.integration
class TestFreshWorktreeStart:
    """Run the real ``.mcp.json`` launch in a brand-new worktree with no venv."""

    @pytest.fixture
    def fresh_worktree(self, tmp_path: Path):
        uv, git = shutil.which("uv"), shutil.which("git")
        if not uv or not git:
            pytest.skip("needs uv and git on PATH")
        if not (_REPO / ".git").exists():
            pytest.skip("needs a git checkout (setuptools-scm reads the version from git)")
        worktree = tmp_path / "wt"
        # Hooks off (an empty hooks dir, portable to Git for Windows): the repo's
        # post-checkout hook can create a .venv, hiding the cold-start case.
        no_hooks = tmp_path / "no-hooks"
        no_hooks.mkdir()
        subprocess.run(  # nosec B603
            [git, "-c", f"core.hooksPath={no_hooks.as_posix()}", "-C", str(_REPO)]
            + ["worktree", "add", "--detach", str(worktree), "HEAD"],
            check=True,
            capture_output=True,
        )
        try:
            assert not (worktree / ".venv").exists()
            yield uv, worktree
        finally:
            # This test's own scratch worktree: remove it, and if git refuses,
            # delete the directory and prune the stale registration.
            removed = subprocess.run(  # nosec B603
                [git, "-C", str(_REPO), "worktree", "remove", str(worktree)],
                capture_output=True,
            )
            if removed.returncode != 0:
                shutil.rmtree(worktree, ignore_errors=True)
                subprocess.run(  # nosec B603
                    [git, "-C", str(_REPO), "worktree", "prune"], capture_output=True
                )

    def test_server_module_imports_on_first_start(self, fresh_worktree) -> None:
        uv, worktree = fresh_worktree
        args = _server(_MCP_JSON)["args"]
        # Same launch arguments, but import the server module instead of
        # starting it (a started server would wait on stdin).
        launch = [a.replace("${CLAUDE_PROJECT_DIR:-.}", str(worktree)) for a in args[:-2]]
        lock_before = (worktree / "uv.lock").read_bytes()
        # As Claude Code launches it: no inherited venv to redirect uv.
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
        }
        result = subprocess.run(  # nosec B603
            [uv, *launch, "-c", "import pyeye.mcp.server; print('import ok')"],
            capture_output=True,
            text=True,
            timeout=240,
            env=env,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "import ok" in result.stdout
        assert (
            worktree / "uv.lock"
        ).read_bytes() == lock_before, "--frozen must not rewrite uv.lock"
