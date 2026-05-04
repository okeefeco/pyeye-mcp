#!/usr/bin/env python3
"""Install pyeye plugin runtime dependencies into the per-user data dir.

Compares ``${CLAUDE_PLUGIN_ROOT}/uv.lock`` against ``${CLAUDE_PLUGIN_DATA}/uv.lock``.
If they match, exit silently. Otherwise, run ``uv sync --no-dev --frozen``
against the plugin checkout, with the venv directed to
``${CLAUDE_PLUGIN_DATA}/.venv``, then copy the lockfile into the data dir
as the last-installed marker.

Invoked from ``hooks/hooks.json`` via::

    uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/install_plugin_deps.py"
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"


def _fail(msg: str, code: int = 1) -> int:
    print(f"pyeye plugin: {msg}", file=sys.stderr)
    return code


def main() -> int:
    """Sync the plugin venv if the lockfile changed; no-op otherwise."""
    root_str = os.environ.get("CLAUDE_PLUGIN_ROOT")
    data_str = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not root_str or not data_str:
        return _fail("CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA must be set")

    root = Path(root_str)
    data = Path(data_str)
    root_lock = root / "uv.lock"
    data_lock = data / "uv.lock"

    if not root_lock.is_file():
        return _fail(f"missing lockfile at {root_lock}")

    if data_lock.is_file() and filecmp.cmp(root_lock, data_lock, shallow=False):
        return 0

    data.mkdir(parents=True, exist_ok=True)
    venv = data / ".venv"

    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)

    cmd = ["uv", "sync", "--no-dev", "--frozen", "--project", str(root)]
    try:
        result = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        return _fail(f"'uv' not found on PATH. Install: {UV_INSTALL_URL}", code=127)

    if result.returncode != 0:
        return _fail(f"uv sync failed (exit {result.returncode})", code=result.returncode)

    shutil.copyfile(root_lock, data_lock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
