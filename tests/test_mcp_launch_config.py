"""Regression tests for how the pyeye MCP server is launched (#600, #1136).

#600: the server was started with ``uv run --no-sync`` against an empty venv, so
``python -m pyeye.mcp`` exited with ``No module named 'pyeye'`` and Claude Code
showed ``CONNECTION_CLOSED`` for the whole session.  The rule still holds:
nothing may start the server against a venv that nobody filled.

#1136: the plugin is also the development setup (``claude --plugin-dir
<worktree>``).

- The repo-root ``.mcp.json`` is gone: Claude Code took it as the marker of the
  plugin's top and launched the dev config instead of the plugin's.
- The plugin's venv is keyed on the plugin ROOT, not on
  ``${CLAUDE_PLUGIN_DATA}`` alone: every ``--plugin-dir`` session is
  ``pyeye@inline`` and shares one data dir, so one ``.venv`` there ran whichever
  checkout synced first.
- The launcher syncs that venv synchronously when it is missing or stale, so
  the first session doesn't race the async setup hook.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 — launches uv/git with fixed argument lists
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_JSON = _REPO / ".claude-plugin" / "plugin.json"
_PLUGIN_HOOKS = _REPO / "hooks" / "hooks.json"
_RUNTIME = "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py"


def _server() -> dict:
    return json.loads(_PLUGIN_JSON.read_text(encoding="utf-8"))["mcpServers"]["pyeye"]


def _session_start_commands() -> list[str]:
    hooks = json.loads(_PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"]
    return [h["command"] for entry in hooks["SessionStart"] for h in entry["hooks"]]


def test_repo_has_no_mcp_json() -> None:
    # With .mcp.json at the root, `claude --plugin-dir <checkout>` launched the
    # dev config from the session's cwd and never connected (#1136).
    assert not (
        _REPO / ".mcp.json"
    ).exists(), "the plugin defines the server; a root .mcp.json hijacks --plugin-dir dev mode"


class TestPluginServer:
    def test_launches_through_the_runtime_script(self) -> None:
        server = _server()
        assert server["command"] == "uv"
        assert server["args"][:3] == ["run", "--no-project", "python"]
        assert server["args"][3:] == [_RUNTIME, "launch"]

    def test_has_no_shared_venv(self) -> None:
        # A fixed UV_PROJECT_ENVIRONMENT is shared by every --plugin-dir checkout.
        assert "UV_PROJECT_ENVIRONMENT" not in _server().get("env", {})
        assert "--no-sync" not in _server()["args"], "#600: nothing fills it first"


class TestSessionStartHooks:
    def test_setup_syncs_through_the_same_runtime(self) -> None:
        commands = _session_start_commands()
        setup = [c for c in commands if c.endswith(" setup")]
        assert setup == [f'uv run --no-project python "{_RUNTIME}" setup']

    def test_guard_runs_synchronously(self) -> None:
        hooks = json.loads(_PLUGIN_HOOKS.read_text(encoding="utf-8"))["hooks"]
        [guard] = [
            h
            for entry in hooks["SessionStart"]
            for h in entry["hooks"]
            if h["command"].endswith(" guard")
        ]
        assert guard["command"] == f'uv run --no-project python "{_RUNTIME}" guard'
        assert not guard.get("async") and not guard.get(
            "asyncRewake"
        ), "its message must reach the session at start"

    def test_old_setup_script_is_gone(self) -> None:
        assert not any("install_plugin_deps" in c for c in _session_start_commands())
        assert not (_REPO / "scripts" / "install_plugin_deps.py").exists()


def test_shipped_skills_run_pyeye_through_the_runtime() -> None:
    # The old shared venv is gone; a skill that ran pyeye there would break.
    for skill in sorted((_REPO / "skills").glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        assert "CLAUDE_PLUGIN_DATA}/.venv" not in text, skill.as_posix()
        if "python -m pyeye." in text and "CLAUDE_PLUGIN_ROOT" in text:
            assert f'"{_RUNTIME}" \\\n  python -m pyeye.' in text, skill.as_posix()


# --- integration: a real sync into fresh worktrees ---------------------------


def _clean_env(data: Path, root: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")
    }
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    return env


@pytest.mark.slow
@pytest.mark.integration
class TestFreshWorktrees:
    """Run the real runtime against brand-new worktrees with no venv."""

    @pytest.fixture
    def make_worktree(self, tmp_path: Path):
        uv, git = shutil.which("uv"), shutil.which("git")
        if not uv or not git:
            pytest.skip("needs uv and git on PATH")
        if not (_REPO / ".git").exists():
            pytest.skip("needs a git checkout (setuptools-scm reads the version from git)")
        # Hooks off (an empty hooks dir, portable to Git for Windows): the repo's
        # post-checkout hook can create a .venv, hiding the cold-start case.
        no_hooks = tmp_path / "no-hooks"
        no_hooks.mkdir()
        made: list[Path] = []

        def make(name: str) -> Path:
            worktree = tmp_path / name
            subprocess.run(  # nosec B603
                [git, "-c", f"core.hooksPath={no_hooks.as_posix()}", "-C", str(_REPO)]
                + ["worktree", "add", "--detach", str(worktree), "HEAD"],
                check=True,
                capture_output=True,
            )
            made.append(worktree)
            # The runtime is the working tree's, which may be uncommitted.
            shutil.copy2(_REPO / "scripts" / "plugin_runtime.py", worktree / "scripts")
            assert not (worktree / ".venv").exists()
            return worktree

        yield uv, make
        for worktree in made:
            # This test's own scratch worktrees: remove them, and if git refuses,
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

    def _setup(self, uv: str, root: Path, data: Path) -> None:
        result = subprocess.run(  # nosec B603
            [uv, "run", "--no-project", "python", str(root / "scripts" / "plugin_runtime.py")]
            + ["setup"],
            capture_output=True,
            text=True,
            timeout=300,
            env=_clean_env(data, root),
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-2000:]

    def _imported_from(self, uv: str, data: Path, root: Path) -> Path:
        # Through the runtime's `python` mode, as a shipped skill runs pyeye.
        result = subprocess.run(  # nosec B603
            [uv, "run", "--no-project", "python", str(root / "scripts" / "plugin_runtime.py")]
            + ["python", "-c", "import pyeye.mcp.server, pyeye; print(pyeye.__file__)"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(data),
            env=_clean_env(data, root),
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return Path(result.stdout.strip())

    def test_two_checkouts_each_import_their_own_code(self, make_worktree, tmp_path) -> None:
        uv, make = make_worktree
        data = tmp_path / "plugin-data"  # ONE data dir, as pyeye@inline has
        a, b = make("wt-a"), make("wt-b")
        lock_before = (a / "uv.lock").read_bytes()
        self._setup(uv, a, data)
        self._setup(uv, b, data)
        assert self._imported_from(uv, data, a).is_relative_to(a / "src")
        assert self._imported_from(uv, data, b).is_relative_to(b / "src")
        assert (a / "uv.lock").read_bytes() == lock_before, "--frozen must not rewrite uv.lock"
        assert not (a / ".venv").exists(), "the checkout's own dev venv is never touched"
