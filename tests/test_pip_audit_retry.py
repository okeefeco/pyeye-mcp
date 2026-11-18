"""The pip-audit hook retries only a network error and stays fail-closed (#894)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts import pip_audit_retry as par

ROOT = Path(__file__).resolve().parent.parent

CLEAN = par.Result(0, "No known vulnerabilities found\n")
VULN = par.Result(1, "Found 2 known vulnerabilities in 1 package\nName Version ID\n")
TIMEOUT = par.Result(
    1,
    "Traceback (most recent call last):\n"
    "requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443): "
    "Read timed out. (read timeout=15)\n",
)
CONNECT = par.Result(1, "urllib3.exceptions.NewConnectionError: Failed to establish\n")
UNKNOWN = par.Result(1, "ERROR: could not resolve the dependency tree\n")


class Fake:
    """A runner that replays *results* and records each call."""

    def __init__(self, *results: par.Result) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> par.Result:
        self.calls.append(list(argv))
        return self.results.pop(0)


def _audit(*results: par.Result) -> tuple[int, Fake, list[float]]:
    fake, slept = Fake(*results), []
    code = par.audit(["--ignore-vuln", "X-1"], run=fake, sleep=slept.append)
    return code, fake, slept


def test_clean_passes_first_time() -> None:
    code, fake, slept = _audit(CLEAN)
    assert (code, len(fake.calls), slept) == (0, 1, [])


def test_a_vulnerability_fails_without_retry() -> None:
    code, fake, _ = _audit(VULN, CLEAN)
    assert (code, len(fake.calls)) == (1, 1)


def test_a_vulnerability_beside_a_network_error_still_fails_without_retry() -> None:
    """The finding wins: a network string in the same output never buys a retry."""
    both = par.Result(1, TIMEOUT.output + VULN.output)
    code, fake, slept = _audit(both, CLEAN)
    assert (code, len(fake.calls), slept) == (1, 1, [])


def test_a_flake_then_clean_passes() -> None:
    code, fake, slept = _audit(TIMEOUT, CONNECT, CLEAN)
    assert (code, len(fake.calls)) == (0, 3)
    assert slept == list(par.BACKOFF)


def test_a_flake_then_a_vulnerability_fails() -> None:
    code, fake, _ = _audit(TIMEOUT, VULN)
    assert (code, len(fake.calls)) == (1, 2)


def test_network_errors_on_every_attempt_fail_closed(capsys: pytest.CaptureFixture[str]) -> None:
    code, fake, _ = _audit(*[TIMEOUT] * par.ATTEMPTS)
    assert (code, len(fake.calls)) == (1, par.ATTEMPTS)
    assert "no audit ran" in capsys.readouterr().err


def test_an_unrecognised_failure_is_not_retried() -> None:
    code, fake, _ = _audit(UNKNOWN, CLEAN)
    assert (code, len(fake.calls)) == (1, 1)


def test_a_failure_with_no_output_fails() -> None:
    assert par.classify(par.Result(2, "")) == "fail"


@pytest.mark.parametrize(
    "line",
    [
        "Found 1 known vulnerability in 1 package",
        "Found 3 known vulnerabilities, ignored 1 in 2 packages",
    ],
)
def test_both_report_wordings_match(line: str) -> None:
    assert par.classify(par.Result(1, line)) == "fail"


def test_the_call_is_uv_frozen_with_the_timeout_and_passed_args() -> None:
    _, fake, _ = _audit(CLEAN)
    assert fake.calls[0] == [
        "uv",
        "run",
        "--frozen",
        "pip-audit",
        "--skip-editable",
        "--timeout",
        str(par.TIMEOUT_SECONDS),
        "--ignore-vuln",
        "X-1",
    ]


def test_the_runner_uses_an_argument_list(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Proc:
        returncode, stdout, stderr = 0, "out\n", "No known vulnerabilities found\n"

    def fake_run(argv: object, **kwargs: object) -> Proc:
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Proc()

    monkeypatch.setattr(par.subprocess, "run", fake_run)
    result = par.run_pip_audit(["uv", "run", "x"])

    assert seen["argv"] == ["uv", "run", "x"] and "shell" not in seen["kwargs"]  # type: ignore[operator]
    assert result == par.Result(0, "out\nNo known vulnerabilities found\n")


def test_the_hook_runs_the_wrapper() -> None:
    text = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    block = text[text.index("- id: pip-audit") :].split("- id:", 2)[1]
    entry = re.search(r"entry:\s*(.+)", block)
    assert entry and entry.group(1).strip() == "uv run --frozen python scripts/pip_audit_retry.py"
