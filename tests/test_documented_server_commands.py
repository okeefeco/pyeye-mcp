"""Documented commands that start the server must point at things that exist (#553).

The docs had drifted to `uv run mcp dev src/pyeye/server.py` and
`uv run python .../src/pyeye/server.py`, but that file doesn't exist. The server
module is `src/pyeye/mcp/server.py`, and running it as a script fails anyway
(relative imports). They also had `uv run pyeye`, but the console script is
`pyeye-mcp`, and `claude mcp add` forms that aren't valid syntax. The supported
ways to start pyeye are `python -m pyeye.mcp` and the `pyeye-mcp` script.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# User- and contributor-facing docs that give run/setup commands.
_DOCS = sorted(
    [
        _ROOT / "README.md",
        _ROOT / "DOCUMENTATION.md",
        _ROOT / "CONTRIBUTING.md",
        *(_ROOT / "docs").glob("*.md"),
        *(_ROOT / "docs" / "source").glob("*.rst"),
        *(_ROOT / ".claude" / "instructions").glob("*.md"),
    ]
)
# Historical records: they describe the past, not how to run pyeye today.
_HISTORICAL = {"COVERAGE.md", "METRICS_BASELINE.md"}


def _lines():
    for path in _DOCS:
        if path.name in _HISTORICAL:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield f"{path.relative_to(_ROOT).as_posix()}:{n}", line


def test_no_command_runs_the_server_as_a_file():
    # The old path doesn't exist at all; the real module can be *named* (e.g. as a
    # file to edit) but not *run* as a script.
    pattern = r"src/pyeye/server\.py|python\s+\S*src/pyeye/mcp/server\.py"
    offenders = [loc for loc, line in _lines() if re.search(pattern, line)]
    assert not offenders, f"use `python -m pyeye.mcp` instead of a file path: {offenders}"


def test_no_mcp_dev_command():
    """`mcp dev` can't load the server module (relative imports); use the Inspector via npx."""
    offenders = [loc for loc, line in _lines() if re.search(r"\bmcp dev\b", line)]
    assert not offenders, offenders


def test_console_scripts_named_in_docs_exist():
    scripts = set(tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]["scripts"])
    named = {
        (loc, m.group(1))
        for loc, line in _lines()
        for m in re.finditer(r"\buv (?:--directory \S+ )?run (pyeye[\w-]*)\b", line)
    }
    missing = sorted(f"{loc}: {name}" for loc, name in named if name not in scripts)
    assert not missing, f"no such console script (have {sorted(scripts)}): {missing}"


@pytest.mark.parametrize("bad", ["claude mcp add /", '--command "', '--directory "/path/to/your'])
def test_no_invalid_claude_mcp_add_forms(bad):
    offenders = [loc for loc, line in _lines() if bad in line]
    assert not offenders, offenders
