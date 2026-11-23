#!/usr/bin/env python3
"""Run the pyeye plugin: its venv and its MCP server (#1136).

Standard library only: it runs before pyeye is installed, via::

    uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py" <mode>

Modes:

``launch``
    The MCP server command (``.claude-plugin/plugin.json``).  Makes sure the
    plugin root's venv is synced, then replaces itself with
    ``<venv python> -m pyeye.mcp``.  Syncing here, synchronously, means the
    first session never races the async setup hook (#1136); sync output goes to
    stderr, because stdout is the MCP channel.
``python ARGS...``
    The same sync, then ``<venv python> ARGS...``: how a shipped skill runs a
    pyeye module (``python -m pyeye.decisions ...``) in the plugin's venv.
``setup``
    The async SessionStart hook: the same sync, ahead of the server, plus
    removal of venvs whose plugin root no longer exists.  Exit code 2 rewakes
    Claude with the error.

The venv lives at ``${CLAUDE_PLUGIN_DATA}/venvs/<hash of the plugin root>/.venv``.
Every ``claude --plugin-dir`` session is plugin ``pyeye@inline`` and shares one
``${CLAUDE_PLUGIN_DATA}``, so a single venv there held an editable install of
whichever checkout synced first.  One venv per root keeps each checkout on its
own code.  A slot is stale when its ``uv.lock`` copy differs from the root's or
its python is missing.

An installed plugin runs from Claude Code's cache, a copy with no ``.git``, where
setuptools-scm can't find pyeye's version; ``pretend_version`` supplies one (#1148).
"""

from __future__ import annotations

import filecmp
import hashlib
import os
import re
import shutil
import subprocess  # nosec B404 — runs uv and the venv's python with fixed arguments
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
PRETEND_VERSION_ENV = "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYEYE_MCP"
_RELEASE_HEADING = re.compile(r"^## \[(\d+(?:\.\d+)*)\]", re.MULTILINE)
_SHORT_SHA = re.compile(r"[0-9a-f]{7,40}")


class SetupError(Exception):
    """The plugin venv could not be prepared."""


def _canonical(path: Path) -> str:
    # Stdlib only (pyeye.path_utils isn't installed yet): one key per directory,
    # whatever its spelling.
    return os.path.normcase(os.path.realpath(path))


def slot_dir(root: Path, data: Path) -> Path:
    """The directory holding *root*'s venv and its markers, under *data*."""
    digest = hashlib.sha256(_canonical(root).encode("utf-8")).hexdigest()[:16]
    return data / "venvs" / digest


def venv_python(venv: Path) -> Path:
    """The interpreter inside *venv*."""
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def pretend_version(root: Path) -> str | None:
    """The version to build *root* as when setuptools-scm can't find one (#1148).

    Claude Code runs an installed plugin from a per-version cache copy with no
    ``.git``, and ``_version.py`` is git-ignored, so setuptools-scm has nothing
    to read and the build fails.  A checkout or worktree (any ``.git``) returns
    ``None``: setuptools-scm reads its real version.  Otherwise the version is
    the last release in ``CHANGELOG.md`` plus the cache directory's short sha,
    when its name is one: ``2.2.0+g11473fb4fd21``.
    """
    if (root / ".git").exists():
        return None
    try:
        match = _RELEASE_HEADING.search((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    except OSError:
        match = None
    release = match.group(1) if match else "0"
    local = f"g{root.name}" if _SHORT_SHA.fullmatch(root.name) else "plugin"
    return f"{release}+{local}"


def _is_current(root_lock: Path, slot: Path) -> bool:
    marker = slot / "uv.lock"
    return (
        marker.is_file()
        and venv_python(slot / ".venv").is_file()
        and filecmp.cmp(root_lock, marker, shallow=False)
    )


def ensure(
    root: Path,
    data: Path,
    *,
    run: Callable[..., Any] | None = None,
    out: TextIO | None = None,
) -> Path:
    """Sync *root*'s venv if it is missing or stale; return the venv path.

    ``uv sync --no-dev --frozen`` installs exactly ``uv.lock`` and never
    re-resolves it.  uv locks the environment, so a concurrent launcher and
    setup hook wait for each other.  The marker is written only after a
    successful sync, so a failure is retried next time.
    """
    root_lock = root / "uv.lock"
    if not root_lock.is_file():
        raise SetupError(f"missing lockfile at {root_lock}")
    slot = slot_dir(root, data)
    venv = slot / ".venv"
    if _is_current(root_lock, slot):
        return venv

    slot.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)
    version = pretend_version(root)
    if version and PRETEND_VERSION_ENV not in env:
        env[PRETEND_VERSION_ENV] = version
    cmd = ["uv", "sync", "--no-dev", "--frozen", "--project", str(root)]
    try:
        result = (run or subprocess.run)(
            cmd, env=env, stdout=out if out is not None else sys.stderr, check=False
        )
    except FileNotFoundError as exc:
        raise SetupError(f"'uv' not found on PATH. Install: {UV_INSTALL_URL}") from exc
    if result.returncode != 0:
        raise SetupError(f"uv sync failed (exit {result.returncode})")

    (slot / "root").write_text(str(root), encoding="utf-8")
    shutil.copyfile(root_lock, slot / "uv.lock")
    return venv


def prune(data: Path) -> list[Path]:
    """Remove venv slots whose recorded plugin root no longer exists.

    A slot without a ``root`` record (one mid-sync, or not ours) is left alone.
    """
    venvs = data / "venvs"
    if not venvs.is_dir():
        return []
    removed = []
    for slot in sorted(venvs.iterdir()):
        record = slot / "root"
        if not record.is_file():
            continue
        if Path(record.read_text(encoding="utf-8")).is_dir():
            continue
        shutil.rmtree(slot, ignore_errors=True)
        removed.append(slot)
    return removed


def _exec(argv: list[str]) -> int:
    """Replace this process with *argv* (POSIX); on Windows, run it and wait."""
    if os.name == "nt":
        return subprocess.call(argv)  # nosec B603 — the venv's python, fixed args
    os.execv(argv[0], argv)  # nosec B606 — the venv's python, fixed args
    return 0  # pragma: no cover — execv does not return


def _plugin_env() -> tuple[Path, Path] | None:
    root, data = os.environ.get("CLAUDE_PLUGIN_ROOT"), os.environ.get("CLAUDE_PLUGIN_DATA")
    if not root or not data:
        return None
    return Path(root), Path(data)


_NO_ENV = "CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA must be set"


def _in_venv(args: list[str]) -> int:
    paths = _plugin_env()
    if paths is None:
        print(f"pyeye: {_NO_ENV}", file=sys.stderr)
        return 1
    try:
        venv = ensure(*paths, out=sys.stderr)
    except SetupError as exc:
        print(f"pyeye: {exc}", file=sys.stderr)
        return 1
    return _exec([str(venv_python(venv)), *args])


def _setup() -> int:
    paths = _plugin_env()
    try:
        if paths is None:
            raise SetupError(_NO_ENV)
        ensure(*paths, out=sys.stderr)
    except SetupError as exc:
        # Exit code 2 triggers asyncRewake so Claude sees setup errors.
        print(f"pyeye plugin setup error: {exc}")
        return 2
    prune(paths[1])
    return 0


def main(argv: list[str]) -> int:
    """Dispatch on the mode in ``argv[0]``."""
    mode, rest = (argv[0], argv[1:]) if argv else ("", [])
    if mode == "launch":
        return _in_venv(["-m", "pyeye.mcp", *rest])
    if mode == "python":
        return _in_venv(rest)
    if mode == "setup":
        return _setup()
    print("usage: plugin_runtime.py launch|python ARGS...|setup", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
