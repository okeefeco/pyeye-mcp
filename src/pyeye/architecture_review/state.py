"""Durable cross-run state for the architecture-review auditor.

This module manages the JSON cache that persists coverage records, prior
findings, and confirmed non-issues across auditor runs.  All functions here
are *pure* except for ``load_state`` / ``save_state`` which perform explicit
file I/O.

Design invariants
-----------------
- **No internal clocks.** All timestamps are caller-supplied strings so that
  tests remain deterministic.
- **No pyeye / MCP calls.** This module operates on plain dicts and strings.
- **Stable non-issue keys.** ``non_issue_key`` is keyed on
  ``sorted(handles) + structural_fact`` — NOT on source-file content —
  so cosmetic edits (whitespace, comments, renaming unrelated symbols) do not
  re-surface dismissed findings.
- **Round-trip identity.** ``load_state(save_state(p, s)); load_state(p) == s``
  for any dict produced by this module.

State shape
-----------
::

    {
        "version": int,
        "coverage": {
            "<module_handle>": {
                "last_audited_at": "<ISO-8601 string>",
                "content_hash": "<caller-computed structural hash>"
            }
        },
        "findings": [<finding dict>, ...],
        "confirmed_non_issues": [
            {
                "handles": ["<handle>", ...],
                "structural_fact": "<fact string>",
                "key": "<non_issue_key output>"
            },
            ...
        ]
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

STATE_VERSION: int = 1
# Current state-file schema version.  Increment when the shape changes in a
# backwards-incompatible way.

# ---------------------------------------------------------------------------
# TypedDict-style aliases (plain dict for now — keeps things simple and
# compatible with JSON round-trips without a custom encoder).
# ---------------------------------------------------------------------------

# CoverageEntry: {"last_audited_at": str, "content_hash": str}
CoverageEntry = dict[str, str]

# NonIssue: {"handles": list[str], "structural_fact": str, "key": str}
NonIssue = dict[str, Any]

# ---------------------------------------------------------------------------
# Empty-state factory
# ---------------------------------------------------------------------------


def _empty_state() -> dict[str, Any]:
    """Return a fresh, valid empty state dict at ``STATE_VERSION``."""
    return {
        "version": STATE_VERSION,
        "coverage": {},
        "findings": [],
        "confirmed_non_issues": [],
    }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_state(path: Path) -> dict[str, Any]:
    """Load the cross-run state from *path*.

    If the file does not exist, return a valid empty state
    (``{"version": STATE_VERSION, "coverage": {}, "findings": [],
    "confirmed_non_issues": []}``).

    Args:
        path: Filesystem path to the JSON state file.  Used only for
            ``read_text``; never stringified into keys.

    Returns:
        The parsed state dict, or an empty state if the file is missing.
    """
    if not path.exists():
        return _empty_state()
    raw = path.read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(raw)
    return result


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist *state* to *path* as formatted JSON.

    The file is written with ``indent=2``, ``sort_keys=True``, and
    ``ensure_ascii=False`` so that diffs are stable and human-readable.

    Args:
        path: Destination path.  Parent directory must exist.
        state: State dict to serialise.  Must be JSON-serialisable.
    """
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Non-issue key
# ---------------------------------------------------------------------------


def non_issue_key(handles: list[str], structural_fact: str) -> str:
    r"""Return a stable, deterministic key for a confirmed non-issue.

    The key is a ``sha256`` hex digest (prefixed with ``"ni:"``) computed over
    a canonical string built from ``sorted(handles)`` joined with ``"|"`` as a
    separator, then ``"\\0"`` (null byte), then ``structural_fact``.

    The key is invariant under:

    - Handle-list ordering (handles are sorted before hashing).
    - Cosmetic source-code edits (whitespace, comments, renaming of *unrelated*
      symbols) that do not change the ``handles`` or ``structural_fact`` strings
      the caller passes.

    The key changes when:

    - ``handles`` differ (different or additional handles).
    - ``structural_fact`` differs (a genuine structural change surfaced by the
      caller/orchestrator).

    This function is **pure** — it reads no files and calls no external APIs.
    Timestamps are not involved.

    Args:
        handles: Canonical handle strings for the code units involved.
        structural_fact: A caller-supplied string describing the structural
            property being evaluated.  The orchestrator is responsible for
            passing the *same* string across cosmetic edits and a *different*
            string when the structure genuinely changes.

    Returns:
        A hex-digest string prefixed with ``"ni:"``.
    """
    canonical = "|".join(sorted(handles)) + "\0" + structural_fact
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "ni:" + digest


# ---------------------------------------------------------------------------
# Codification helpers
# ---------------------------------------------------------------------------


def build_non_issue(finding: dict[str, Any]) -> NonIssue:
    """Build a confirmed-non-issue cache entry from a dismissed finding.

    Returns a NonIssue dict ``{"handles": [...], "structural_fact": str, "key": str}``
    where ``structural_fact`` is the finding's neutral divergence statement (its ``claim``)
    — the Tier-1 relationship the human adjudicated — and ``key`` is
    ``non_issue_key(handles, structural_fact)``. Structural, not content: cosmetic
    source edits that leave the finding's handles + claim intact keep the same key
    (still suppressed); a genuine structural re-divergence changes the claim/handles
    → new key (re-surfaces). See spec §14.

    This function is **pure** — it reads no files and calls no external APIs.
    The input finding is not mutated.

    Args:
        finding: A finding dict with at least ``"handles"`` (list of canonical
            handle strings) and ``"claim"`` (the neutral divergence statement)
            fields.  Other fields (``axis``, ``grade``, ``evidence``,
            ``recommendation``) are ignored.

    Returns:
        A ``NonIssue`` dict ready to append to
        ``state["confirmed_non_issues"]`` and persist with
        :func:`save_state`.
    """
    handles: list[str] = finding["handles"]
    structural_fact: str = finding["claim"]
    key: str = non_issue_key(handles, structural_fact)
    return {
        "handles": handles,
        "structural_fact": structural_fact,
        "key": key,
    }


# ---------------------------------------------------------------------------
# Freshness check
# ---------------------------------------------------------------------------


def is_stale(entry: CoverageEntry, current_hash: str) -> bool:
    """Return ``True`` if the audited unit's structural content has changed.

    Staleness is defined purely as ``entry["content_hash"] != current_hash``.
    The ``last_audited_at`` timestamp is informational only and is not used in
    the comparison.

    This function is **pure** — it reads no files and calls no external APIs.

    Args:
        entry: A ``CoverageEntry`` dict with at least a ``"content_hash"`` key.
        current_hash: The current structural-content hash computed by the caller
            (orchestrator) for the same unit.

    Returns:
        ``True`` when the stored hash differs from *current_hash*, ``False``
        when they match.
    """
    return entry["content_hash"] != current_hash


# ---------------------------------------------------------------------------
# Finding equivalence and merging
# ---------------------------------------------------------------------------


def _normalise_claim(claim: str) -> str:
    """Return a normalised form of *claim* for phrasing-insensitive comparison.

    Normalisation steps:

    1. Strip leading/trailing whitespace.
    2. Collapse runs of internal whitespace to a single space.
    3. Casefold (Unicode case-insensitive).

    Note:
        This is a pragmatic normalisation — it handles common phrasing
        variants but is not a full NLP equivalence.  The spec describes it
        as "phrasing ignored" at the level of whitespace + case.
    """
    stripped = claim.strip()
    collapsed = re.sub(r"\s+", " ", stripped)
    return collapsed.casefold()


def findings_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return ``True`` iff findings *a* and *b* are considered equivalent.

    Two findings are equivalent when they share:

    - Identical **cluster membership**: the *set* of ``handles`` values is the
      same (order-independent).
    - The same **grade** string.
    - The same **norm-claim semantics**: the ``claim`` strings normalise to the
      same value under :func:`_normalise_claim` (strip + collapse whitespace +
      casefold).

    Fields other than ``handles``, ``grade``, and ``claim`` (e.g. ``axis``,
    ``evidence``, ``recommendation``) are intentionally excluded from the
    equivalence check per the spec.

    This predicate is **pure** and is exposed as a public name so that later
    tasks (e.g. Task 2.2) can import and reuse it without re-implementing the
    same normalisation logic.

    Args:
        a: A finding dict with ``"handles"``, ``"grade"``, and ``"claim"`` keys.
        b: Another finding dict.

    Returns:
        ``True`` iff the two findings are equivalent.
    """
    handles_a: set[str] = set(a.get("handles") or [])
    handles_b: set[str] = set(b.get("handles") or [])
    if handles_a != handles_b:
        return False
    if a.get("grade") != b.get("grade"):
        return False
    claim_a = _normalise_claim(a.get("claim") or "")
    claim_b = _normalise_claim(b.get("claim") or "")
    return claim_a == claim_b


def merge_findings(prior: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the union of *prior* and *new*, deduped by finding equivalence.

    The merge is defined as:

    - Start with all of *prior* (order preserved).
    - For each finding in *new*: add it only if no equivalent finding is
      already in the accumulated result.

    Equivalence is determined by :func:`findings_equivalent`.  Neither *prior*
    nor *new* is mutated.

    Note:
        If *prior* itself contains duplicates, they are preserved as-is —
        this function does not de-duplicate *prior* against itself.

    Args:
        prior: Findings from a previous run (or accumulated so far).
        new: Candidate findings from the current run.

    Returns:
        A new list: ``prior`` findings followed by non-equivalent ``new``
        findings.
    """
    result: list[dict[str, Any]] = list(prior)
    for candidate in new:
        if not any(findings_equivalent(candidate, kept) for kept in result):
            result.append(candidate)
    return result
