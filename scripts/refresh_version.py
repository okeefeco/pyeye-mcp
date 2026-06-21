#!/usr/bin/env python3
"""Refresh the ``setuptools_scm``-generated version file after a git state change.

Wired as a pre-commit ``post-merge`` / ``post-checkout`` hook (#462). The version
file (``[tool.setuptools_scm].version_file`` → ``src/pyeye/_version.py``) is
gitignored and only written at install/build time, so in a local dev env the
self-reported version (``pyeye.__version__`` → ``pyeye://about``) drifts after a
plain ``git pull`` or branch switch. This rewrites it from the current git
state.

Failure-tolerant by design: nothing here is allowed to block a pull or checkout,
so every path returns 0.
"""

from __future__ import annotations

import os
import subprocess
import sys


def should_run() -> bool:
    """Return whether to regen, honoring pre-commit's post-checkout guard.

    pre-commit consumes git's positional args and re-exports the post-checkout
    flag as ``PRE_COMMIT_CHECKOUT_TYPE`` (``"1"`` = branch checkout,
    ``"0"`` = file checkout). On a file checkout the tree's git description is
    unchanged, so regenerating is pointless — skip it. When the variable is
    absent (e.g. a ``post-merge`` invocation) we default to running.
    """
    return os.environ.get("PRE_COMMIT_CHECKOUT_TYPE") != "0"


def main() -> int:
    """Regen the version file when the guard allows it; never raise."""
    if not should_run():
        return 0
    try:
        subprocess.run(
            [sys.executable, "-m", "setuptools_scm", "--force-write-version-files"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001 - a refresh failure must never block git
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
