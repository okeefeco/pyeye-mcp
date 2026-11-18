"""Which CI test legs collect coverage (#892).

The user chose to run Windows 3.11 without coverage: coverage cost that leg
about 28% (settrace), and it is uploaded only from ubuntu 3.11. Every other
leg keeps ``--cov`` and the 85% gate. This reads the ``ci.yml`` pytest command
for every ``test-pr`` and ``test-main`` leg and checks exactly that.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)


def _value(expr: str, matrix: dict[str, Any]) -> Any:
    """Evaluate a GitHub expression built from ==, &&, || and string literals."""
    text = " ".join(expr.split())
    for key, val in sorted(matrix.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(f"matrix.{key}", repr(str(val)))
    text = text.replace("&&", " and ").replace("||", " or ")
    leftover = re.sub(r"'[^']*'|\b(and|or|not)\b|==|!=|[()\s]", "", text)
    assert not leftover, f"unsupported expression in ci.yml: {expr!r} -> {leftover!r}"
    return eval(text, {"__builtins__": {}}, {})  # noqa: S307 - vetted above  # nosec B307


def _pytest_command(job: dict[str, Any], matrix: dict[str, Any]) -> str:
    step = next(s for s in job["steps"] if "pytest" in str(s.get("run", "")))
    return _EXPR.sub(lambda m: str(_value(m.group(1), matrix)), " ".join(step["run"].split()))


def _legs(job: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = job["strategy"]["matrix"]
    if "include" in matrix:
        return list(matrix["include"])
    keys = list(matrix)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*matrix.values())]


_JOBS = yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]
_CASES = [(job_id, leg) for job_id in ("test-pr", "test-main") for leg in _legs(_JOBS[job_id])]


@pytest.mark.parametrize(
    ("job_id", "leg"),
    _CASES,
    ids=[f"{j}-{leg['os']}-{leg['python-version']}" for j, leg in _CASES],
)
def test_only_windows_311_runs_without_coverage(job_id: str, leg: dict[str, Any]) -> None:
    command = _pytest_command(_JOBS[job_id], leg)
    if leg["os"] == "windows-latest" and str(leg["python-version"]) == "3.11":
        assert command == "uv run pytest --no-cov"
    else:
        assert "--cov=src/pyeye" in command
        assert "--cov-fail-under=85" in command
        assert "--no-cov" not in command


def test_the_codecov_leg_keeps_coverage() -> None:
    """Codecov uploads from ubuntu 3.11: that leg must always produce coverage.xml."""
    command = _pytest_command(_JOBS["test-pr"], {"os": "ubuntu-latest", "python-version": "3.11"})
    assert "--cov-report=xml" in command


def test_both_jobs_are_covered() -> None:
    """Guard against the parametrisation silently covering nothing."""
    windows_311 = [
        (j, leg)
        for j, leg in _CASES
        if leg["os"] == "windows-latest" and str(leg["python-version"]) == "3.11"
    ]
    assert {j for j, _ in windows_311} == {"test-pr", "test-main"}
