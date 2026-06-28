"""Reproduction gate for the architecture-review auditor (spec §10).

This module implements the *confirmation loop* that promotes a would-be-confident
finding only when it reproduces stably across N independent re-runs of the auditor
over the same scope.

Design
------
**Grade rewrite, no side boolean.**
    The gate expresses its verdict by setting ``grade`` to ``"ambiguous"`` on
    unstable candidates; there is no separate ``confirmed`` flag.  Downstream
    confidence-splitting keys entirely on the post-gate grade value.

**Equivalence reused from state.**
    :func:`~pyeye.architecture_review.state.findings_equivalent` from
    :mod:`pyeye.architecture_review.state` is the single predicate used here —
    the same predicate :func:`~pyeye.architecture_review.state.merge_findings`
    uses — so the definition of "same finding" is never split across modules.

**Pure and injectable.**
    All I/O and dispatch is delegated to the caller-supplied ``redispatch_fn``
    parameter; this module performs no pyeye / MCP / file I/O itself.  This
    makes the gate deterministically testable with mocked dispatch functions.

**Candidates only (cost control).**
    Only findings with ``grade == "deterministic_single"`` are re-dispatched.
    ``mechanical_fact``, ``ambiguous``, and ``no_signal`` findings pass through
    unchanged without any calls to ``redispatch_fn``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyeye.architecture_review.state import findings_equivalent

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

DEFAULT_GATE_RUNS: int = (
    3  # Provisional N (spec §10: 2–3 runs); a config default, not a magic constant.
)

_CANDIDATE_GRADE: str = "deterministic_single"
_DOWNGRADE_GRADE: str = "ambiguous"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_reproduction_gate(
    findings: list[dict[str, Any]],
    redispatch_fn: Callable[[dict[str, Any], int], list[dict[str, Any]]],
    runs: int = DEFAULT_GATE_RUNS,
    equivalent: Callable[[dict[str, Any], dict[str, Any]], bool] = findings_equivalent,
) -> list[dict[str, Any]]:
    """Apply the spec §10 reproduction gate to *findings*.

    For each finding with ``grade == "deterministic_single"``, the gate
    re-dispatches the auditor ``runs`` times over that candidate's scope.  The
    candidate keeps its ``deterministic_single`` grade only if an equivalent
    finding (per *equivalent*) appears in *every* re-run.  If any run lacks an
    equivalent, the grade is rewritten to ``"ambiguous"``.

    Non-candidate findings (``grade`` in ``{"ambiguous", "mechanical_fact",
    "no_signal"}``) are passed through unchanged without any call to
    *redispatch_fn*.

    The returned list preserves the order of *findings* and has the same length.
    Input dicts are never mutated in place; a new dict copy is returned for any
    finding whose grade is rewritten.

    Args:
        findings: The full list of findings from the first auditor pass.
        redispatch_fn: Callable with signature ``(candidate, run_index) ->
            list[dict]``.  Called ``runs`` times per candidate, with
            ``run_index`` in ``range(runs)``.  Each call should return the
            findings from one fresh auditor re-run over the candidate's scope.
            Must be injected by the caller; this function performs no real I/O.
        runs: Number of independent re-runs per candidate.  Must be ``>= 1``.
            Defaults to :data:`DEFAULT_GATE_RUNS`.
        equivalent: Binary predicate ``(a, b) -> bool`` used to test whether a
            re-run finding matches the candidate.  Defaults to
            :func:`~pyeye.architecture_review.state.findings_equivalent` — the
            same predicate :func:`~pyeye.architecture_review.state.merge_findings`
            uses, keyed on handle-set + grade + normalised claim.

    Returns:
        A new list of findings, same order and length as *findings*, with
        ``grade`` rewritten to ``"ambiguous"`` for any unstable candidate.
        Non-candidates are the same objects as in *findings* (not copied).

    Raises:
        ValueError: If *runs* is less than 1.  A gate with zero runs cannot
            confirm anything.
    """
    if runs < 1:
        raise ValueError(f"runs must be >= 1, got {runs!r}")

    result: list[dict[str, Any]] = []
    for finding in findings:
        if finding.get("grade") != _CANDIDATE_GRADE:
            # Non-candidate: pass through unchanged, never call redispatch_fn
            result.append(finding)
            continue

        # Candidate: re-dispatch N times and check for equivalence in every run.
        # Short-circuit on the first non-reproducing run — §10 is cost-controlled
        # and the orchestrator wires in a real, expensive auditor dispatch here.
        stable = True
        for i in range(runs):
            run_findings = redispatch_fn(finding, i)
            if not any(equivalent(finding, other) for other in run_findings):
                stable = False
                break

        if stable:
            result.append(finding)
        else:
            # Return a new dict with grade changed; preserve all other keys
            result.append({**finding, "grade": _DOWNGRADE_GRADE})

    return result
