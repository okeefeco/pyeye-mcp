"""Contract test: workflow steps invoke uv-installed tools through ``uv run`` (#540).

CI and release jobs install dependencies with ``uv sync --locked`` (#414, #481),
which puts them in the project's ``.venv`` — not on ``PATH``. A bare ``pytest``
/ ``mypy`` / ``bandit`` in a ``run:`` step therefore fails with "command not
found". The release workflow's ``validate`` job kept bare invocations from the
old ``uv pip install --system`` era after #414, and would have failed the next
tag push (v2.0).
"""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Tools that live in the uv-managed venv (dev group), never on the runner PATH.
_VENV_TOOLS = {"pytest", "mypy", "bandit", "ruff", "black", "pip-audit", "coverage"}


def _run_commands():
    """Yield (workflow, job, command line) for every line of every ``run:`` step."""
    for wf in sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                for line in str(step.get("run", "")).splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        yield wf.name, job_name, line


def _invoked_tool(line: str) -> str | None:
    """Return the venv tool a command line invokes bare, if any."""
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError:
        return None
    if not tokens:
        return None
    if tokens[0] in _VENV_TOOLS:
        return tokens[0]
    if tokens[0] in {"python", "python3"} and tokens[1:2] == ["-m"] and len(tokens) > 2:
        module = tokens[2].replace("_", "-")
        return module if module in _VENV_TOOLS else None
    return None


def test_invoked_tool_detection():
    """Guard the detector itself so the contract can't pass vacuously."""
    assert _invoked_tool("pytest --cov=src/pyeye") == "pytest"
    assert _invoked_tool("python -m mypy src/pyeye") == "mypy"
    assert _invoked_tool("python -m pip_audit") == "pip-audit"
    assert _invoked_tool("uv run pytest --cov=src/pyeye") is None
    assert _invoked_tool("python scripts/validate_changelog.py") is None
    assert _invoked_tool('echo "pytest passed"') is None


def test_workflow_tools_run_through_uv():
    """No ``run:`` step may call a venv tool without ``uv run`` (#540)."""
    offenders = [
        f"{wf} [{job}]: {line}"
        for wf, job, line in _run_commands()
        if _invoked_tool(line) is not None
    ]
    assert not offenders, (
        "uv sync installs tools into .venv, not PATH; prefix these with `uv run` "
        f"(#540): {offenders}"
    )
