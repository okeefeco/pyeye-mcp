"""setup_mcp_monitoring.sh merges pyeye's hooks into the user's settings (#981).

It used to replace the whole ``hooks`` key of ``~/.claude/settings.json``, or,
without ``jq``, the whole file, so every hook the user already had was lost on
each run, and #968/#974 tell users to re-run it. ``merge_hooks.py`` now
replaces only pyeye's own hook commands and keeps everything else.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - runs the repo's own scripts
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "scripts" / "claude_hooks"
sys.path.insert(0, str(HOOKS))

from merge_hooks import is_pyeye_command, merge_hooks  # noqa: E402

_USER_BASH = {"type": "command", "command": "~/bin/audit-bash.sh"}
_USER_STOP = {"hooks": [{"type": "command", "command": "notify-send done"}]}


def _pyeye_hooks(repo: str = "/repo") -> dict:
    text = (HOOKS / "hooks.json").read_text(encoding="utf-8").replace("~/GitHub/pyeye-mcp", repo)
    return json.loads(text)["hooks"]


def _user_settings() -> dict:
    return {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            # The user's own Bash hook, in the same matcher pyeye also uses
            "PreToolUse": [{"matcher": "Bash", "hooks": [dict(_USER_BASH)]}],
            "Stop": [_USER_STOP],
        },
    }


def _commands(settings: dict) -> list[tuple[str, str | None, str]]:
    return [
        (event, entry.get("matcher"), hook["command"])
        for event, entries in settings["hooks"].items()
        for entry in entries
        for hook in entry["hooks"]
    ]


def test_the_users_hooks_and_settings_survive() -> None:
    merged = merge_hooks(_user_settings(), _pyeye_hooks())
    assert merged["model"] == "opus" and merged["permissions"] == {"allow": ["Bash(ls:*)"]}
    commands = _commands(merged)
    assert ("PreToolUse", "Bash", "~/bin/audit-bash.sh") in commands
    assert ("Stop", None, "notify-send done") in commands
    pyeye = [c for c in commands if is_pyeye_command(c[2])]
    assert len(pyeye) == sum(len(e["hooks"]) for es in _pyeye_hooks().values() for e in es)


def test_a_rerun_changes_nothing() -> None:
    once = merge_hooks(_user_settings(), _pyeye_hooks())
    twice = merge_hooks(json.loads(json.dumps(once)), _pyeye_hooks())
    assert twice == once


def test_a_moved_repo_replaces_the_old_paths_instead_of_adding_copies() -> None:
    old = merge_hooks(_user_settings(), _pyeye_hooks("/old/clone"))
    new = merge_hooks(old, _pyeye_hooks("/new/clone"))
    pyeye = [c for c in _commands(new) if is_pyeye_command(c[2])]
    assert pyeye and all("/new/clone/" in c[2] for c in pyeye)
    assert ("PreToolUse", "Bash", "~/bin/audit-bash.sh") in _commands(new)


def test_the_pre_970_inline_grep_hook_is_recognised_as_pyeyes() -> None:
    legacy = 'echo "$(date +%Y-%m-%d_%H:%M:%S),grep_tool,direct" >> ~/.claude/mcp_monitoring/grep_usage.csv'
    settings = {
        "hooks": {
            "PreToolUse": [{"matcher": "Grep", "hooks": [{"type": "command", "command": legacy}]}]
        }
    }
    merged = merge_hooks(settings, _pyeye_hooks())
    assert legacy not in [c[2] for c in _commands(merged)]
    assert not is_pyeye_command("~/bin/audit-bash.sh")


def test_settings_without_hooks_get_pyeyes() -> None:
    merged = merge_hooks({"model": "opus"}, _pyeye_hooks())
    assert merged["model"] == "opus"
    assert set(merged["hooks"]) == set(_pyeye_hooks())


# --- the setup script, end to end in a temporary HOME -------------------------


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    return home


def _setup(home: Path, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    if path is not None:
        env["PATH"] = path
    return subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        ["bash", str(HOOKS / "setup_mcp_monitoring.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


@pytest.mark.skipif(os.name == "nt", reason="the setup script is bash")
def test_setup_keeps_the_users_hooks_across_runs(home: Path) -> None:
    settings_file = home / ".claude" / "settings.json"
    settings_file.write_text(json.dumps(_user_settings()), encoding="utf-8")

    for _ in range(2):
        result = _setup(home)
        assert result.returncode == 0, result.stdout + result.stderr

    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    commands = _commands(settings)
    assert ("PreToolUse", "Bash", "~/bin/audit-bash.sh") in commands
    assert ("Stop", None, "notify-send done") in commands
    assert any(c[2].endswith("track_grep_tool.py") for c in commands)
    assert len(commands) == len(set(commands))  # no duplicates after a re-run
    assert list((home / ".claude").glob("settings.json.backup-*"))  # backup kept


@pytest.mark.skipif(os.name == "nt", reason="the setup script is bash")
def test_setup_works_without_jq(home: Path, tmp_path: Path) -> None:
    """jq used to be the only merge; without it the whole file was replaced."""
    settings_file = home / ".claude" / "settings.json"
    settings_file.write_text(json.dumps(_user_settings()), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in (
        "python3",
        "bash",
        "date",
        "cp",
        "mkdir",
        "chmod",
        "sed",
        "dirname",
        "basename",
        "head",
        "cat",
        "mv",
        "rm",
    ):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    assert shutil.which("jq", path=str(bin_dir)) is None

    result = _setup(home, path=str(bin_dir))
    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    assert ("PreToolUse", "Bash", "~/bin/audit-bash.sh") in _commands(settings)


@pytest.mark.skipif(os.name == "nt", reason="the setup script is bash")
def test_unreadable_settings_are_left_alone(home: Path) -> None:
    settings_file = home / ".claude" / "settings.json"
    settings_file.write_text("{ not json", encoding="utf-8")
    result = _setup(home)
    assert result.returncode != 0
    assert settings_file.read_text(encoding="utf-8") == "{ not json"
    assert "not valid JSON" in result.stdout + result.stderr
