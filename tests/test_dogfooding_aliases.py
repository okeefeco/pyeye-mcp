"""The dogfooding and hooks alias sets don't collide, and work from any directory (#982).

``scripts/setup_aliases.sh`` (the dogfooding session CLI) and
``scripts/claude_hooks/setup_mcp_monitoring.sh`` (the hooks analytics) both
defined ``mcp-report``, for different tools, so whichever was sourced last won.
The dogfooding aliases are now ``dogfood-*``. They also used a relative
``scripts/dogfooding_metrics.py``, so they worked only from the repo root.
"""

from __future__ import annotations

import os
import re
import subprocess  # nosec B404 - runs the repo's own script
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOGFOOD = ROOT / "scripts" / "setup_aliases.sh"
HOOKS = ROOT / "scripts" / "claude_hooks" / "setup_mcp_monitoring.sh"
_ALIAS = re.compile(r"^\s*alias ([\w-]+)=", re.MULTILINE)


def _aliases(path: Path) -> set[str]:
    return set(_ALIAS.findall(path.read_text(encoding="utf-8"))) - {"grep", "cd"}


def test_the_two_alias_sets_are_disjoint() -> None:
    dogfood, hooks = _aliases(DOGFOOD), _aliases(HOOKS)
    assert dogfood and hooks
    assert not dogfood & hooks, sorted(dogfood & hooks)


def test_the_dogfooding_aliases_are_named_dogfood() -> None:
    assert _aliases(DOGFOOD) == {
        "dogfood-start",
        "dogfood-end",
        "dogfood-report",
        "dogfood-saved",
        "dogfood-bug",
    }


@pytest.mark.skipif(os.name == "nt", reason="the setup script is bash")
def test_the_installed_aliases_name_this_checkout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        ["bash", str(DOGFOOD)],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rc = (home / ".bashrc").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "dogfooding_metrics.py").as_posix()
    report = next(line for line in rc.splitlines() if line.startswith("alias dogfood-report="))
    assert f'--project "{ROOT.as_posix()}"' in report
    assert f'python "{script}" report' in report
    assert "alias mcp-" not in rc
    assert "Renamed from mcp-start" in result.stdout  # the notice for muscle memory


@pytest.mark.skipif(os.name == "nt", reason="the setup script is bash")
def test_an_old_alias_block_is_told_about_the_rename(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text(
        "# Dogfooding Metrics Aliases - Added by then\n"
        "alias mcp-start='uv run --frozen python scripts/dogfooding_metrics.py start'\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # nosec B603 - fixed argv, the repo's own script
        ["bash", str(DOGFOOD)],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "dogfood-*" in result.stdout
