"""One interactive code search is counted once, not twice (#1020).

``setup_dogfooding.sh`` installed two grep counters that stacked: the
``grep`` shell alias (``tracked_grep``, from ``setup_aliases.sh``) counted every
grep in the project, then ran ``command grep``, which still searches PATH and so
reached the ``~/.local/bin`` wrapper (``grep_tracker.sh``), which counted it
again. The wrappers are now the only counter.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs the repo's own scripts
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the setup scripts are bash")


def _run(argv: list[str], env: dict[str, str], cwd: Path = ROOT) -> None:
    result = subprocess.run(  # nosec B603 - fixed argv, the repo's own scripts
        argv, capture_output=True, text=True, env=env, cwd=cwd, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def shell(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A temp HOME with both counters installed, and a fake ``uv`` that logs its calls."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("", encoding="utf-8")
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    log = tmp_path / "uv.log"
    uv = fake_bin / "uv"
    uv.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> "{log.as_posix()}"\n', encoding="utf-8")
    uv.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "TERM": "dumb",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    _run(["bash", str(SCRIPTS / "setup_aliases.sh")], env)
    _run(["bash", str(SCRIPTS / "setup_grep_tracking.sh")], env)
    return env, log


def _counted(log: Path) -> int:
    if not log.exists():
        return 0
    return sum("dogfooding_metrics.py grep" in line for line in log.read_text().splitlines())


def test_one_interactive_code_search_is_counted_once(shell: tuple[dict[str, str], Path]) -> None:
    env, log = shell
    # An interactive shell reads ~/.bashrc: the aliases and the PATH line.
    _run(["bash", "-i", "-c", "grep -r zzz_no_such_text scripts/grep_tracker.sh; true"], env)
    assert _counted(log) == 1


def test_a_non_code_search_is_not_counted(shell: tuple[dict[str, str], Path]) -> None:
    env, log = shell
    _run(["bash", "-i", "-c", "grep zzz_no_such_text README.md; true"], env)
    assert _counted(log) == 0
