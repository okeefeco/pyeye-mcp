#!/usr/bin/env python3
"""Run pip-audit, retrying only a positively identified network error (#894).

The pre-commit ``pip-audit`` hook reads pypi.org with no retry, so a single
slow read (``ReadTimeout``) failed the required ``pre-commit`` check exactly as
a real vulnerability does, and dropped PRs from the merge queue.

This wrapper keeps the gate **fail-closed**:

- exit 0: the audit ran and found nothing, so pass;
- a vulnerability report ("Found N known vulnerabilit…"): fail at once, with no
  retry, even if a network error also appears in the output. That match only
  ever decides "don't retry", never "pass";
- a network error that is positively identified (:data:`NETWORK_ERROR`): retry,
  up to :data:`ATTEMPTS` runs with :data:`BACKOFF` between them, then fail;
- anything else: fail, with no retry. An unrecognised failure is never absorbed.

It runs ``uv run --frozen pip-audit --skip-editable`` as an argument list (no
shell), so the audited environment is the one the hook audited before. Extra
arguments, such as a future ``--ignore-vuln <ID>``, are passed through.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - runs uv with a fixed argument list, no shell
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: The pip-audit call; the audited environment is uv's, as the hook's was.
COMMAND: tuple[str, ...] = ("uv", "run", "--frozen", "pip-audit", "--skip-editable")
#: pip-audit's socket timeout, in seconds (its default is 15).
TIMEOUT_SECONDS = 30
#: Total runs before a network error is reported as a failure.
ATTEMPTS = 3
#: Seconds to wait before each retry.
BACKOFF: tuple[int, ...] = (10, 30)

#: pip-audit's summary when it finds something (``_cli.py``).
VULNERABILITY_REPORT = re.compile(r"\bFound \d+ known vulnerabilit(?:y|ies)\b")
#: The network errors a retry may absorb: requests' and urllib3's timeout and
#: connection exception names, as they appear in pip-audit's traceback.
NETWORK_ERROR = re.compile(
    r"\b(?:requests\.exceptions\.(?:ReadTimeout|ConnectTimeout|ConnectionError)"
    r"|urllib3\.exceptions\.(?:ReadTimeoutError|ConnectTimeoutError"
    r"|NewConnectionError|MaxRetryError))\b"
)


@dataclass(frozen=True)
class Result:
    """One pip-audit run."""

    returncode: int
    output: str


Runner = Callable[[Sequence[str]], Result]


def classify(result: Result) -> str:
    """``"pass"``, ``"retry"`` or ``"fail"`` for one run (fail-closed)."""
    if result.returncode == 0:
        return "pass"
    if VULNERABILITY_REPORT.search(result.output):
        return "fail"  # a real finding: never retried, whatever else is printed
    if NETWORK_ERROR.search(result.output):
        return "retry"
    return "fail"


def run_pip_audit(argv: Sequence[str]) -> Result:
    """Run *argv*, echoing its output, and return the exit code and the output."""
    proc = subprocess.run(  # nosec B603 - an argument list, no shell
        list(argv), capture_output=True, text=True, check=False
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return Result(proc.returncode, proc.stdout + proc.stderr)


def audit(
    extra: Sequence[str] = (),
    run: Runner = run_pip_audit,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the audit with retries; return the exit code for pre-commit."""
    argv = [*COMMAND, "--timeout", str(TIMEOUT_SECONDS), *extra]
    for attempt in range(1, ATTEMPTS + 1):
        verdict = classify(run(argv))
        if verdict == "pass":
            return 0
        if verdict == "fail":
            return 1
        if attempt < ATTEMPTS:
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            print(
                f"pip-audit: network error reaching the vulnerability service; "
                f"retrying in {wait}s ({attempt}/{ATTEMPTS})",
                file=sys.stderr,
            )
            sleep(wait)
    print(
        f"pip-audit: the vulnerability service was unreachable in {ATTEMPTS} attempts; "
        "failing, because no audit ran",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1:]))
