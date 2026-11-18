"""Every invocation of the dogfooding metrics script goes through ``uv run`` (#879).

``scripts/dogfooding_metrics.py`` imports ``click`` and ``pyeye``, which exist
only in the project's uv environment. A bare ``python`` fails outside an
activated venv, and the aliases' ``2>/dev/null || true`` hid the failure, so
grep tracking and auto-start silently did nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Every file that tells a shell or a reader to run the metrics script.
_FILES = [
    "scripts/setup_dogfooding.sh",
    "scripts/setup_aliases.sh",
    "scripts/grep_tracker.sh",
    "scripts/mcp_wrapper.sh",
    "docs/DOGFOODING_INTEGRATION.md",
    "docs/DOGFOODING_SETUP.md",
    "docs/METRICS_BASELINE.md",
    "scripts/claude_hooks/README.md",
]

# A python interpreter running the metrics script, directly or via a variable.
_RUN = re.compile(
    r"(?<![\w/.-])python3?\s+[^|;&]*?(dogfooding_metrics\.py|\$DOGFOODING_SCRIPT|\$\{DOGFOODING_SCRIPT\})"
)
_UV = re.compile(r"\buv run --frozen(\s+--project\s+\S+)?\s+$")


def _invocations(text: str) -> list[tuple[int, str, bool]]:
    """``(line number, line, via uv)`` for each interpreter running the script."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _RUN.finditer(line):
            found.append((number, line.strip(), bool(_UV.search(line[: match.start()]))))
    return found


@pytest.mark.parametrize("name", _FILES)
def test_the_metrics_script_runs_through_uv(name: str) -> None:
    bare = [
        f"{name}:{n}: {line}"
        for n, line, via_uv in _invocations((_ROOT / name).read_text(encoding="utf-8"))
        if not via_uv
    ]
    assert not bare, "bare python runs the metrics script:\n" + "\n".join(bare)


def test_every_file_that_runs_the_script_is_checked() -> None:
    """A new file that runs the script must join ``_FILES`` (the list can't rot)."""
    runners = set()
    for path in [*_ROOT.glob("scripts/**/*.sh"), *_ROOT.glob("scripts/**/*.md")]:
        if _invocations(path.read_text(encoding="utf-8")):
            runners.add(path.relative_to(_ROOT).as_posix())
    for path in _ROOT.glob("docs/*.md"):
        if _invocations(path.read_text(encoding="utf-8")):
            runners.add(path.relative_to(_ROOT).as_posix())
    assert runners <= set(_FILES), sorted(runners - set(_FILES))


def test_the_matcher_tells_bare_from_uv() -> None:
    sample = (
        "python scripts/dogfooding_metrics.py start\n"
        "uv run --frozen python scripts/dogfooding_metrics.py end\n"
        'uv run --frozen --project "$ROOT" python "$DOGFOODING_SCRIPT" grep\n'
        'python3 "$DOGFOODING_SCRIPT" grep\n'
        'python $(dirname "$0")/dogfooding_metrics.py mcp "$1"\n'
    )
    assert [via for _, _, via in _invocations(sample)] == [False, True, True, False, False]


def test_setup_checks_for_uv_not_a_bare_python() -> None:
    text = (_ROOT / "scripts/setup_dogfooding.sh").read_text(encoding="utf-8")
    assert "command -v uv" in text
    assert "command -v python3" not in text


def test_sync_is_gone_from_the_cli_and_the_docs() -> None:
    """``sync`` always recorded 0 MCP calls and was dropped (#879); nothing may point at it."""
    import click.testing

    import scripts.dogfooding_metrics as dm

    assert "sync" not in dm.cli.commands
    result = click.testing.CliRunner().invoke(dm.cli, ["sync"])
    assert result.exit_code != 0
    assert not hasattr(dm.DogfoodingMetrics, "sync_mcp_metrics")
    still_told = [
        f"{name}:{n}"
        for name in _FILES
        for n, line in enumerate((_ROOT / name).read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"dogfooding_metrics\.py\s+sync\b", line)
    ]
    assert not still_told, still_told
