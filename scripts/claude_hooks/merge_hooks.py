#!/usr/bin/env python3
"""Merge pyeye's monitoring hooks into a Claude Code settings file (#981).

``setup_mcp_monitoring.sh`` used to replace the whole ``hooks`` key of
``~/.claude/settings.json``, or the whole file without ``jq``, so the user's own
hooks were lost on every run. This keeps everything that isn't pyeye's: other
settings, other events, other matchers, and other commands in a matcher pyeye
also uses. It replaces only pyeye's own hook commands, so a re-run, or a run
from a repository that has moved, leaves exactly one copy.

Usage: merge_hooks.py SETTINGS_JSON HOOKS_JSON REPO_ROOT
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# A command is pyeye's if it runs one of this directory's scripts, or (before
# #970) wrote straight into pyeye's monitoring directory.
_PYEYE_MARKERS = ("/scripts/claude_hooks/", ".claude/mcp_monitoring/")

_USAGE = "usage: merge_hooks.py SETTINGS_JSON HOOKS_JSON REPO_ROOT"


def is_pyeye_command(command: str) -> bool:
    """Is *command* one of the hooks pyeye's setup installs?"""
    return any(marker in command for marker in _PYEYE_MARKERS)


def merge_hooks(settings: dict[str, Any], pyeye_hooks: dict[str, Any]) -> dict[str, Any]:
    """*settings* with pyeye's hooks replaced by *pyeye_hooks* and everything else kept."""
    merged = dict(settings)
    hooks: dict[str, list[dict[str, Any]]] = {}
    for event, entries in (settings.get("hooks") or {}).items():
        kept = []
        for entry in entries:
            commands = [
                h for h in entry.get("hooks", []) if not is_pyeye_command(h.get("command", ""))
            ]
            if commands:
                kept.append({**entry, "hooks": commands})
        if kept:
            hooks[event] = kept
    for event, entries in pyeye_hooks.items():
        hooks.setdefault(event, []).extend(entries)
    merged["hooks"] = hooks
    return merged


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write *data* whole: a temporary file in the same directory, then a replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    """Merge into SETTINGS_JSON; leave it untouched and exit 1 if it can't be read."""
    if len(argv) != 3:
        print(_USAGE, file=sys.stderr)
        return 2
    settings_path, hooks_path, repo_root = Path(argv[0]), Path(argv[1]), argv[2]
    pyeye_hooks = json.loads(
        hooks_path.read_text(encoding="utf-8").replace("~/GitHub/pyeye-mcp", repo_root)
    )["hooks"]
    settings: dict[str, Any] = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as e:
            print(f"{settings_path} is not valid JSON ({e}); left unchanged.", file=sys.stderr)
            return 1
        if not isinstance(settings, dict):
            print(f"{settings_path} is not a JSON object; left unchanged.", file=sys.stderr)
            return 1
    _write_json(settings_path, merge_hooks(settings, pyeye_hooks))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
