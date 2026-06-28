"""Tests for architecture_review.state — cross-run durable state.

Covers:
- load_state / save_state round-trip identity
- load_state on a missing file yields a valid empty state
- non_issue_key stability: cosmetic edits keep the same key; structural changes
  produce a new key
- is_stale: false right after audit, true after content-hash change
- merge_findings: dedupes equivalent findings, unions non-equivalent ones
- findings_equivalent is importable and correct as a standalone predicate
- build_non_issue: produces a well-formed NonIssue entry, reusing non_issue_key
"""

import json
from pathlib import Path

from pyeye.architecture_review.state import (
    STATE_VERSION,
    build_non_issue,
    findings_equivalent,
    is_stale,
    load_state,
    merge_findings,
    non_issue_key,
    save_state,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_finding(
    handles: list[str],
    grade: str = "ambiguous",
    claim: str = "Some claim",
    axis: str = "layering",
) -> dict:
    return {
        "handles": handles,
        "grade": grade,
        "claim": claim,
        "axis": axis,
    }


# ---------------------------------------------------------------------------
# load_state / save_state
# ---------------------------------------------------------------------------


class TestLoadSaveRoundTrip:
    """Round-trip identity: save then load yields the same dict."""

    def test_round_trip_empty_state(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "state.json")
        p = tmp_path / "saved.json"
        save_state(p, state)
        reloaded = load_state(p)
        assert reloaded == state

    def test_round_trip_populated_state(self, tmp_path: Path) -> None:
        state = {
            "version": STATE_VERSION,
            "coverage": {
                "pyeye.server": {
                    "last_audited_at": "2026-06-28T10:00:00Z",
                    "content_hash": "abc123",
                }
            },
            "findings": [_make_finding(["pyeye.server:run"], grade="deterministic_single")],
            "confirmed_non_issues": [
                {
                    "handles": ["pyeye.cache:Cache"],
                    "structural_fact": "Cache.__init__ uses injected clock",
                    "key": "ni:deadbeef",
                }
            ],
        }
        p = tmp_path / "state.json"
        save_state(p, state)
        reloaded = load_state(p)
        assert reloaded == state

    def test_save_produces_valid_json(self, tmp_path: Path) -> None:
        """save_state must write valid JSON that json.loads can parse."""
        state = load_state(tmp_path / "missing.json")
        p = tmp_path / "out.json"
        save_state(p, state)
        raw = p.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed == state

    def test_save_uses_indent_2(self, tmp_path: Path) -> None:
        """save_state must use indent=2 for stable diffs."""
        state = load_state(tmp_path / "missing.json")
        p = tmp_path / "out.json"
        save_state(p, state)
        raw = p.read_text(encoding="utf-8")
        # indent=2 means lines start with two spaces (not one tab)
        assert "  " in raw  # at least some indentation present

    def test_save_sort_keys(self, tmp_path: Path) -> None:
        """save_state must sort keys for stable diffs."""
        state = {
            "version": STATE_VERSION,
            "z_key": 1,
            "a_key": 2,
            "coverage": {},
            "findings": [],
            "confirmed_non_issues": [],
        }
        p = tmp_path / "out.json"
        save_state(p, state)
        raw = p.read_text(encoding="utf-8")
        a_pos = raw.index('"a_key"')
        z_pos = raw.index('"z_key"')
        assert a_pos < z_pos, "Keys must be sorted alphabetically"


class TestLoadStateMissingFile:
    """load_state on a missing file returns a valid empty state."""

    def test_missing_file_returns_empty_state(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "does_not_exist.json")
        assert state == {
            "version": STATE_VERSION,
            "coverage": {},
            "findings": [],
            "confirmed_non_issues": [],
        }

    def test_missing_file_returns_correct_version(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "nonexistent.json")
        assert state["version"] == STATE_VERSION

    def test_missing_file_empty_containers(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "nonexistent.json")
        assert state["coverage"] == {}
        assert state["findings"] == []
        assert state["confirmed_non_issues"] == []

    def test_multiple_calls_for_missing_file_return_equal_states(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.json"
        s1 = load_state(p)
        s2 = load_state(p)
        assert s1 == s2


# ---------------------------------------------------------------------------
# non_issue_key
# ---------------------------------------------------------------------------


class TestNonIssueKey:
    """non_issue_key must be stable under cosmetic changes and sensitive to structural ones."""

    def test_same_handles_same_fact_same_key(self) -> None:
        k1 = non_issue_key(["pyeye.server:run", "pyeye.cache:Cache"], "uses DI")
        k2 = non_issue_key(["pyeye.server:run", "pyeye.cache:Cache"], "uses DI")
        assert k1 == k2

    def test_key_is_order_independent_on_handles(self) -> None:
        """Sorted handles: order of the input list must not matter."""
        k1 = non_issue_key(["a", "b", "c"], "some fact")
        k2 = non_issue_key(["c", "a", "b"], "some fact")
        assert k1 == k2

    def test_key_changes_when_structural_fact_changes(self) -> None:
        """A genuinely different structural_fact must produce a different key."""
        k1 = non_issue_key(["pyeye.server:run"], "raises ValueError on bad input")
        k2 = non_issue_key(["pyeye.server:run"], "returns None on bad input")
        assert k1 != k2

    def test_key_changes_when_handles_change(self) -> None:
        """A different handle set must produce a different key."""
        k1 = non_issue_key(["pyeye.server:run"], "uses DI")
        k2 = non_issue_key(["pyeye.server:stop"], "uses DI")
        assert k1 != k2

    def test_cosmetic_edit_to_source_does_not_change_key(self) -> None:
        """Simulate: a cosmetic edit to the surrounding code (whitespace/comment)
        does NOT change the handles or structural_fact the caller passes, so the
        key must remain identical.

        The structural_fact string is supplied by the caller (the orchestrator).
        If the caller passes the same string (because the fact is unchanged), the
        key must be the same, regardless of what happened to the surrounding file.
        """
        structural_fact = "raises ValueError on bad input"
        handles = ["pyeye.server:validate"]
        k_before = non_issue_key(handles, structural_fact)
        # Simulate: the orchestrator re-runs after a whitespace-only edit to
        # the file. The handles and structural_fact string are identical.
        k_after = non_issue_key(handles, structural_fact)
        assert k_before == k_after

    def test_genuine_structural_redivergence_yields_new_key(self) -> None:
        """A genuine structural change means the caller passes a DIFFERENT
        structural_fact → the key must differ.

        This models: the reviewed unit diverged structurally (e.g. now swallows
        exceptions instead of raising). The orchestrator detects this and forms
        a new structural_fact string. A new key is produced, so the non-issue is
        NOT suppressed and the finding re-surfaces.
        """
        handles = ["pyeye.server:validate"]
        k_old = non_issue_key(handles, "raises ValueError on bad input")
        k_new = non_issue_key(handles, "swallows ValueError silently")
        assert k_old != k_new

    def test_key_is_string(self) -> None:
        k = non_issue_key(["h"], "fact")
        assert isinstance(k, str)

    def test_key_is_non_empty(self) -> None:
        k = non_issue_key(["h"], "fact")
        assert k != ""

    def test_empty_handles_list_is_deterministic(self) -> None:
        """Empty handle list: key must be stable and deterministic."""
        k1 = non_issue_key([], "orphan fact")
        k2 = non_issue_key([], "orphan fact")
        assert k1 == k2

    def test_different_empty_vs_non_empty_handles(self) -> None:
        k1 = non_issue_key([], "fact")
        k2 = non_issue_key(["h"], "fact")
        assert k1 != k2


# ---------------------------------------------------------------------------
# is_stale
# ---------------------------------------------------------------------------


class TestIsStale:
    """is_stale compares stored content_hash to current hash."""

    def _entry(self, content_hash: str, last_audited_at: str = "2026-06-28T10:00:00Z") -> dict:
        return {"last_audited_at": last_audited_at, "content_hash": content_hash}

    def test_not_stale_when_hash_matches(self) -> None:
        entry = self._entry("abc123")
        assert is_stale(entry, "abc123") is False

    def test_stale_when_hash_changes(self) -> None:
        entry = self._entry("abc123")
        assert is_stale(entry, "xyz789") is True

    def test_stale_on_any_hash_difference(self) -> None:
        """Even a one-character difference must trigger staleness."""
        entry = self._entry("abc123")
        assert is_stale(entry, "abc124") is True

    def test_not_stale_right_after_audit(self) -> None:
        """Simulate: content_hash was recorded at audit time; current hash is
        the same. is_stale must be False immediately after an audit."""
        current_hash = "sha256:deadbeef"
        entry = self._entry(current_hash, last_audited_at="2026-06-28T12:00:00Z")
        assert is_stale(entry, current_hash) is False

    def test_stale_after_content_changes(self) -> None:
        """Simulate: the unit's content changed after the audit.
        The orchestrator computes a new hash and passes it in."""
        recorded_hash = "sha256:aaa"
        new_hash = "sha256:bbb"
        entry = self._entry(recorded_hash, last_audited_at="2026-06-27T09:00:00Z")
        assert is_stale(entry, new_hash) is True

    def test_is_stale_is_pure(self) -> None:
        """is_stale must not mutate the entry dict."""
        entry = self._entry("abc")
        original = dict(entry)
        is_stale(entry, "xyz")
        assert entry == original


# ---------------------------------------------------------------------------
# findings_equivalent
# ---------------------------------------------------------------------------


class TestFindingsEquivalent:
    """findings_equivalent is a pure predicate over two finding dicts."""

    def test_identical_findings_are_equivalent(self) -> None:
        f = _make_finding(["h1", "h2"], grade="ambiguous", claim="X")
        assert findings_equivalent(f, f) is True

    def test_same_handles_grade_claim_equivalent(self) -> None:
        f1 = _make_finding(["h1", "h2"], grade="ambiguous", claim="X")
        f2 = _make_finding(["h1", "h2"], grade="ambiguous", claim="X")
        assert findings_equivalent(f1, f2) is True

    def test_handle_order_ignored(self) -> None:
        """Cluster membership is a SET — order must not matter."""
        f1 = _make_finding(["a", "b"], grade="ambiguous", claim="Y")
        f2 = _make_finding(["b", "a"], grade="ambiguous", claim="Y")
        assert findings_equivalent(f1, f2) is True

    def test_different_grade_not_equivalent(self) -> None:
        f1 = _make_finding(["h1"], grade="ambiguous", claim="X")
        f2 = _make_finding(["h1"], grade="deterministic_single", claim="X")
        assert findings_equivalent(f1, f2) is False

    def test_different_handles_not_equivalent(self) -> None:
        f1 = _make_finding(["h1"], grade="ambiguous", claim="X")
        f2 = _make_finding(["h2"], grade="ambiguous", claim="X")
        assert findings_equivalent(f1, f2) is False

    def test_different_handle_set_size_not_equivalent(self) -> None:
        f1 = _make_finding(["h1", "h2"], grade="ambiguous", claim="X")
        f2 = _make_finding(["h1"], grade="ambiguous", claim="X")
        assert findings_equivalent(f1, f2) is False

    def test_claim_whitespace_normalized(self) -> None:
        """Leading/trailing whitespace and collapsed internal whitespace must
        not break equivalence."""
        f1 = _make_finding(["h"], grade="ambiguous", claim="  some  claim  ")
        f2 = _make_finding(["h"], grade="ambiguous", claim="some claim")
        assert findings_equivalent(f1, f2) is True

    def test_claim_casefolded(self) -> None:
        """Claim comparison is casefolded (case-insensitive)."""
        f1 = _make_finding(["h"], grade="ambiguous", claim="Some Claim")
        f2 = _make_finding(["h"], grade="ambiguous", claim="some claim")
        assert findings_equivalent(f1, f2) is True

    def test_claim_semantics_different_not_equivalent(self) -> None:
        f1 = _make_finding(["h"], grade="ambiguous", claim="raises exception")
        f2 = _make_finding(["h"], grade="ambiguous", claim="swallows exception")
        assert findings_equivalent(f1, f2) is False

    def test_axis_field_does_not_affect_equivalence(self) -> None:
        """The spec says equivalence is handle-set + grade + claim. Different
        axis values with same handles/grade/claim must still be equivalent.
        (Axis is not part of the equivalence predicate per spec.)"""
        f1 = {
            "handles": ["h"],
            "grade": "ambiguous",
            "claim": "x",
            "axis": "layering",
        }
        f2 = {
            "handles": ["h"],
            "grade": "ambiguous",
            "claim": "x",
            "axis": "error_handling",
        }
        assert findings_equivalent(f1, f2) is True


# ---------------------------------------------------------------------------
# merge_findings
# ---------------------------------------------------------------------------


class TestMergeFindings:
    """merge_findings unions prior + new, dropping equivalent duplicates."""

    def test_empty_prior_empty_new_is_empty(self) -> None:
        assert merge_findings([], []) == []

    def test_empty_prior_keeps_all_new(self) -> None:
        new = [_make_finding(["h1"]), _make_finding(["h2"])]
        result = merge_findings([], new)
        assert len(result) == 2

    def test_non_empty_prior_empty_new_keeps_prior(self) -> None:
        prior = [_make_finding(["h1"]), _make_finding(["h2"])]
        result = merge_findings(prior, [])
        assert result == prior

    def test_duplicate_in_new_is_dropped(self) -> None:
        """A finding in new that is equivalent to one in prior is dropped."""
        prior = [_make_finding(["h1"], grade="ambiguous", claim="X")]
        new = [_make_finding(["h1"], grade="ambiguous", claim="X")]
        result = merge_findings(prior, new)
        assert len(result) == 1

    def test_non_equivalent_new_finding_is_kept(self) -> None:
        """A genuinely different finding in new must be added."""
        prior = [_make_finding(["h1"], grade="ambiguous", claim="X")]
        new = [_make_finding(["h2"], grade="ambiguous", claim="Y")]
        result = merge_findings(prior, new)
        assert len(result) == 2

    def test_equivalent_finding_by_handle_set(self) -> None:
        """Handle-order variant of a prior finding is treated as equivalent."""
        prior = [_make_finding(["a", "b"], grade="ambiguous", claim="Z")]
        new = [_make_finding(["b", "a"], grade="ambiguous", claim="Z")]
        result = merge_findings(prior, new)
        assert len(result) == 1

    def test_different_grade_is_not_duplicate(self) -> None:
        prior = [_make_finding(["h1"], grade="ambiguous", claim="X")]
        new = [_make_finding(["h1"], grade="deterministic_single", claim="X")]
        result = merge_findings(prior, new)
        assert len(result) == 2

    def test_prior_is_not_mutated(self) -> None:
        prior = [_make_finding(["h1"])]
        original_prior = list(prior)
        merge_findings(prior, [_make_finding(["h2"])])
        assert prior == original_prior

    def test_new_is_not_mutated(self) -> None:
        new = [_make_finding(["h2"])]
        original_new = list(new)
        merge_findings([], new)
        assert new == original_new

    def test_order_prior_then_new(self) -> None:
        """Merged result should contain prior findings first, then new ones."""
        f_prior = _make_finding(["h1"], claim="prior")
        f_new = _make_finding(["h2"], claim="new")
        result = merge_findings([f_prior], [f_new])
        assert result[0] == f_prior
        assert result[1] == f_new

    def test_multiple_new_some_duplicate(self) -> None:
        """Some new findings duplicate prior; others are genuinely new."""
        prior = [
            _make_finding(["h1"], grade="ambiguous", claim="A"),
            _make_finding(["h2"], grade="ambiguous", claim="B"),
        ]
        new = [
            _make_finding(["h1"], grade="ambiguous", claim="A"),  # duplicate of prior[0]
            _make_finding(["h3"], grade="ambiguous", claim="C"),  # genuinely new
        ]
        result = merge_findings(prior, new)
        assert len(result) == 3
        # h1/A and h2/B from prior, h3/C from new
        handles_in_result = [set(f["handles"]) for f in result]
        assert {"h1"} in handles_in_result
        assert {"h2"} in handles_in_result
        assert {"h3"} in handles_in_result

    def test_claim_whitespace_normalization_causes_dedup(self) -> None:
        """Claim whitespace normalization must prevent phantom duplicates."""
        prior = [_make_finding(["h"], grade="ambiguous", claim="some claim")]
        new = [_make_finding(["h"], grade="ambiguous", claim="  some  claim  ")]
        result = merge_findings(prior, new)
        assert len(result) == 1

    def test_claim_casefolding_causes_dedup(self) -> None:
        """Claim casefolding must prevent phantom duplicates."""
        prior = [_make_finding(["h"], grade="ambiguous", claim="Some Claim")]
        new = [_make_finding(["h"], grade="ambiguous", claim="some claim")]
        result = merge_findings(prior, new)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Non-issue suppression integration
# ---------------------------------------------------------------------------


class TestNonIssueSuppression:
    """Integration: non_issue_key is used to check if a finding was dismissed."""

    def _dismiss(self, handles: list[str], structural_fact: str, state: dict) -> None:
        key = non_issue_key(handles, structural_fact)
        state["confirmed_non_issues"].append(
            {
                "handles": handles,
                "structural_fact": structural_fact,
                "key": key,
            }
        )

    def _is_suppressed(self, handles: list[str], structural_fact: str, state: dict) -> bool:
        key = non_issue_key(handles, structural_fact)
        return any(ni["key"] == key for ni in state["confirmed_non_issues"])

    def test_dismissed_divergence_recognized_as_suppressed(self, tmp_path: Path) -> None:
        state = load_state(tmp_path / "missing.json")  # fresh empty
        # Simulate: user dismissed this divergence
        self._dismiss(["pyeye.server:validate"], "raises ValueError on bad input", state)
        # Re-check: same handles + same structural_fact → suppressed
        assert (
            self._is_suppressed(["pyeye.server:validate"], "raises ValueError on bad input", state)
            is True
        )

    def test_cosmetic_edit_keeps_suppressed(self, tmp_path: Path) -> None:
        """After a cosmetic edit to the surrounding code (whitespace/comment),
        the caller passes the SAME handles + structural_fact → still suppressed."""
        state = load_state(tmp_path / "missing.json")
        self._dismiss(["pyeye.server:validate"], "raises ValueError on bad input", state)
        # Cosmetic edit: caller still passes identical handles + structural_fact
        assert (
            self._is_suppressed(["pyeye.server:validate"], "raises ValueError on bad input", state)
            is True
        )

    def test_genuine_structural_redivergence_resurfaces(self, tmp_path: Path) -> None:
        """A genuine structural change means the caller passes a DIFFERENT
        structural_fact → the key is different → NOT suppressed."""
        state = load_state(tmp_path / "missing.json")
        self._dismiss(["pyeye.server:validate"], "raises ValueError on bad input", state)
        # Genuine structural change: caller now reports a different structural_fact
        assert (
            self._is_suppressed(["pyeye.server:validate"], "swallows ValueError silently", state)
            is False
        )


# ---------------------------------------------------------------------------
# build_non_issue
# ---------------------------------------------------------------------------


class TestBuildNonIssue:
    """build_non_issue constructs a well-formed NonIssue entry from a finding.

    The function must:
    - Return the correct shape: {"handles": list, "structural_fact": str, "key": str}.
    - Use finding["handles"] as handles and finding["claim"] as structural_fact.
    - Compute "key" via non_issue_key(handles, structural_fact) — NOT a new keying.
    - Be pure (no I/O, no mutation of the input finding).
    - Produce the same key as two findings with identical handles+claim (stable).
    - Produce a different key for a finding with a different claim (re-surfaces).
    """

    def _make_full_finding(
        self,
        handles: list[str],
        claim: str = "uses constructor injection",
        grade: str = "deterministic_single",
        axis: str = "dependency_acquisition",
        evidence: str = "N/N modules use DI",
        recommendation: str = "codify as the project norm",
    ) -> dict:
        """Return a finding dict with all six standard fields."""
        return {
            "axis": axis,
            "claim": claim,
            "grade": grade,
            "handles": handles,
            "evidence": evidence,
            "recommendation": recommendation,
        }

    def test_returns_correct_shape(self) -> None:
        finding = self._make_full_finding(["pyeye.server:run"])
        result = build_non_issue(finding)
        assert set(result.keys()) == {"handles", "structural_fact", "key"}

    def test_handles_field_equals_finding_handles(self) -> None:
        handles = ["pyeye.server:run", "pyeye.cache:Cache"]
        finding = self._make_full_finding(handles)
        result = build_non_issue(finding)
        assert result["handles"] == handles

    def test_structural_fact_equals_finding_claim(self) -> None:
        claim = "raises ValueError on bad input"
        finding = self._make_full_finding(["pyeye.server:validate"], claim=claim)
        result = build_non_issue(finding)
        assert result["structural_fact"] == claim

    def test_key_equals_non_issue_key_of_handles_and_claim(self) -> None:
        """Key must equal non_issue_key(finding["handles"], finding["claim"]) — reuses the function."""
        handles = ["pyeye.server:run"]
        claim = "uses constructor injection"
        finding = self._make_full_finding(handles, claim=claim)
        result = build_non_issue(finding)
        expected_key = non_issue_key(handles, claim)
        assert result["key"] == expected_key

    def test_two_findings_same_handles_and_claim_yield_same_key(self) -> None:
        """Findings with the same handles + claim must produce the same NonIssue key."""
        handles = ["pyeye.server:run"]
        claim = "all modules use a factory for DI"
        f1 = self._make_full_finding(handles, claim=claim, evidence="3/3 modules")
        f2 = self._make_full_finding(handles, claim=claim, evidence="different evidence")
        ni1 = build_non_issue(f1)
        ni2 = build_non_issue(f2)
        assert ni1["key"] == ni2["key"]

    def test_finding_with_different_claim_yields_different_key(self) -> None:
        """A genuine structural re-divergence (different claim) yields a new key."""
        handles = ["pyeye.server:validate"]
        f_old = self._make_full_finding(handles, claim="raises ValueError on bad input")
        f_new = self._make_full_finding(handles, claim="swallows ValueError silently")
        ni_old = build_non_issue(f_old)
        ni_new = build_non_issue(f_new)
        assert ni_old["key"] != ni_new["key"]

    def test_finding_with_different_handles_yields_different_key(self) -> None:
        """Different handles → different key."""
        claim = "uses DI"
        f1 = self._make_full_finding(["pyeye.server:run"], claim=claim)
        f2 = self._make_full_finding(["pyeye.server:stop"], claim=claim)
        assert build_non_issue(f1)["key"] != build_non_issue(f2)["key"]

    def test_key_is_handle_order_independent(self) -> None:
        """Key must be order-independent on the handles list (sorted before hashing)."""
        claim = "all validators are at the boundary"
        f1 = self._make_full_finding(["b", "a"], claim=claim)
        f2 = self._make_full_finding(["a", "b"], claim=claim)
        assert build_non_issue(f1)["key"] == build_non_issue(f2)["key"]

    def test_is_pure_does_not_mutate_input(self) -> None:
        """build_non_issue must not mutate the input finding."""
        finding = self._make_full_finding(["pyeye.server:run"])
        original = dict(finding)
        build_non_issue(finding)
        assert finding == original

    def test_result_is_json_serialisable(self) -> None:
        """The returned NonIssue dict must round-trip through JSON (needed for save_state)."""
        finding = self._make_full_finding(["pyeye.server:run", "pyeye.cache:Cache"])
        result = build_non_issue(finding)
        serialised = json.dumps(result)
        restored = json.loads(serialised)
        assert restored == result
