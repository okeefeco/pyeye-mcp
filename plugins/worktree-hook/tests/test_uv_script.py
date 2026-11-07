"""Tests for how the hooks get their Python and dependencies (#608).

The hooks used to run as bare ``python3``, so they inherited whatever happened to
be installed. That broke in several ways. macOS's built-in ``python3`` (3.9) can't
import the scripts. ``python3`` is often missing on Windows. And without PyYAML
the config fell back to a hand-written parser that silently dropped every branch
type, which disabled the nested naming model.

Now each script declares its needs in a PEP 723 header, and ``hooks.json`` runs it
with ``uv run --script``. uv provides a matching interpreter and a cached
environment holding the declared dependencies.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
HOOKS_JSON = PLUGIN_DIR / "hooks" / "hooks.json"
SCRIPTS = {"WorktreeCreate": "worktree_create.py", "WorktreeRemove": "worktree_remove.py"}


def _pep723(script: str) -> str:
    text = (PLUGIN_DIR / script).read_text()
    block = re.search(r"^# /// script\n(.*?)^# ///$", text, re.MULTILINE | re.DOTALL)
    assert block, f"{script} has no PEP 723 '# /// script' block"
    return block.group(1)


def _hook_commands() -> dict[str, str]:
    config = json.loads(HOOKS_JSON.read_text())
    return {
        event: hook["command"]
        for event, groups in config["hooks"].items()
        for group in groups
        for hook in group["hooks"]
    }


@pytest.mark.parametrize("script", sorted(SCRIPTS.values()))
def test_script_declares_requires_python(script: str) -> None:
    """uv picks an interpreter the scripts can run on (they use 3.10 syntax)."""
    assert '# requires-python = ">=3.10"' in _pep723(script)


def test_create_declares_pyyaml() -> None:
    """The config is YAML; PyYAML is a declared dependency, not an optional extra."""
    assert re.search(r'^# dependencies = \["pyyaml>=6"\]$', _pep723("worktree_create.py"), re.M)


def test_hooks_json_runs_each_script_with_uv_run_script() -> None:
    """Every hook goes through ``uv run --script``, never a bare interpreter."""
    commands = _hook_commands()
    assert set(commands) == set(SCRIPTS)
    for event, script in SCRIPTS.items():
        assert commands[event] == f'uv run --quiet --script "${{CLAUDE_PLUGIN_ROOT}}/{script}"'


# ---------------------------------------------------------------------------
# End to end through the real hooks.json commands
# ---------------------------------------------------------------------------


def _run_hook(
    event: str, payload: dict[str, str], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    """Run ``hooks.json``'s command for ``event`` the way Claude Code does."""
    command = _hook_commands()[event].replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_DIR.as_posix())
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))  # logs stay out of ~/.claude
    env.pop("VIRTUAL_ENV", None)  # prove uv's own environment is used, not the test venv
    return subprocess.run(
        shlex.split(command),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=600,
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_hooks_create_nested_worktree_and_remove_it_via_uv(
    repo: Path,
    tmp_path: Path,
    run_git: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Create nests ``feat-608-x`` as ``feat/608-x`` (needs the YAML config), then remove."""
    created = _run_hook(
        "WorktreeCreate",
        {"hook_event_name": "WorktreeCreate", "name": "feat-608-uv", "cwd": str(repo)},
        tmp_path,
    )
    assert created.returncode == 0, created.stderr
    lines = created.stdout.splitlines()
    assert len(lines) == 1, f"stdout must be only the worktree path: {created.stdout!r}"
    worktree = Path(lines[0])
    expected = repo / ".claude" / "worktrees" / "feat" / "608-uv"
    assert worktree.resolve() == expected.resolve()
    assert run_git(repo, "branch", "--list", "feat/608-uv").stdout.strip()

    removed = _run_hook(
        "WorktreeRemove",
        {"hook_event_name": "WorktreeRemove", "worktree_path": str(worktree)},
        tmp_path,
    )
    assert removed.returncode == 0, removed.stderr
    assert not worktree.exists()
    assert run_git(repo, "branch", "--list", "feat/608-uv").stdout.strip() == ""
