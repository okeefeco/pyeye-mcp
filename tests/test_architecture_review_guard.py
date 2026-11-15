"""Tests for the #494 cross-derivation guard (Task 3.1).

Two groups:

A. Pure-helper tests with a mocked ``corroborate_fn`` — exercise candidate
   selection, grade rewrite, immutability and order preservation.
B. The #494 independence/acceptance tests — use a REAL ``ast``-based
   corroborator (:func:`imports_via_ast`) so the verdict is demonstrably
   independent of the auditor's stored evidence and of any pyeye edge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyeye.architecture_review.guard import (
    CANNOT_CONFIRM,
    CORROBORATED,
    DIVERGENT,
    apply_cross_derivation_guard,
    corroborate_imports,
    imports_via_ast,
)

# ---------------------------------------------------------------------------
# Group A — pure helper (mocked corroborate_fn)
# ---------------------------------------------------------------------------


def test_corroborated_candidate_passes_unchanged() -> None:
    """A deterministic_single that corroborates keeps its grade, no flag added."""
    finding = {"grade": "deterministic_single", "claim": "x", "axis": "layering"}

    result = apply_cross_derivation_guard([finding], corroborate_fn=lambda _f: True)

    assert len(result) == 1
    out = result[0]
    assert out["grade"] == "deterministic_single"
    assert "possible_extractor_bug" not in out
    assert out == finding


def test_divergent_candidate_downgraded_and_flagged_without_mutating_input() -> None:
    """A divergent deterministic_single is downgraded + flagged; input untouched."""
    finding = {
        "grade": "deterministic_single",
        "claim": "all modules import logging",
        "axis": "layering",
        "evidence": "edge says so",
    }

    result = apply_cross_derivation_guard([finding], corroborate_fn=lambda _f: False)

    assert len(result) == 1
    out = result[0]
    assert out["grade"] == "ambiguous"
    assert out["possible_extractor_bug"] is True
    # Every other key preserved.
    assert out["claim"] == "all modules import logging"
    assert out["axis"] == "layering"
    assert out["evidence"] == "edge says so"
    # Input dict NOT mutated.
    assert finding["grade"] == "deterministic_single"
    assert "possible_extractor_bug" not in finding


def test_non_candidates_untouched_and_corroborate_fn_never_called_for_them() -> None:
    """Only deterministic_single triggers corroborate_fn; others pass through."""
    calls: list[dict[str, Any]] = []

    def spy(finding: dict[str, Any]) -> bool:
        calls.append(finding)
        return True

    findings = [
        {"grade": "mechanical_fact", "claim": "a"},
        {"grade": "ambiguous", "claim": "b"},
        {"grade": "no_signal", "claim": "c"},
        {"grade": "deterministic_single", "claim": "d"},
    ]

    result = apply_cross_derivation_guard(findings, corroborate_fn=spy)

    # corroborate_fn called exactly once — only for the deterministic_single.
    assert len(calls) == 1
    assert calls[0]["claim"] == "d"
    # Non-candidates are the same objects, untouched.
    assert result[0] is findings[0]
    assert result[1] is findings[1]
    assert result[2] is findings[2]


def test_order_and_length_preserved() -> None:
    """Output is the same length and order as input."""
    findings = [
        {"grade": "deterministic_single", "claim": "a"},
        {"grade": "mechanical_fact", "claim": "b"},
        {"grade": "deterministic_single", "claim": "c"},
        {"grade": "no_signal", "claim": "d"},
    ]

    result = apply_cross_derivation_guard(findings, corroborate_fn=lambda _f: True)

    assert len(result) == len(findings)
    assert [f["claim"] for f in result] == ["a", "b", "c", "d"]


# ---------------------------------------------------------------------------
# Group B — #494 independence / acceptance (REAL ast corroborator)
# ---------------------------------------------------------------------------

_FIXTURE_SOURCE = '''"""A small fixture module with known imports."""

import os
from pkg.sub import thing
from . import sibling


def use() -> None:
    """Touch the imports so linters do not complain."""
    _ = (os, thing, sibling)
'''


def _write_fixture(tmp_path: Path) -> Path:
    module_file = tmp_path / "fixture_module.py"
    module_file.write_text(_FIXTURE_SOURCE, encoding="utf-8")
    return module_file


def test_imports_via_ast_returns_true_import_set(tmp_path: Path) -> None:
    """The AST reader extracts the real import set from source."""
    module_file = _write_fixture(tmp_path)

    assert imports_via_ast(module_file) == {"os", "pkg.sub", "sibling"}


def test_494_dropped_import_is_downgraded_via_ast_not_evidence(tmp_path: Path) -> None:
    """#494: a finding claiming a TRUNCATED import set is caught by the AST.

    The finding's ``evidence`` string would (wrongly) confirm the buggy fact,
    and the same suspect pyeye edge would too — but the guard derives truth from
    :func:`imports_via_ast` (the source), which disagrees, so it downgrades.
    """
    module_file = _write_fixture(tmp_path)

    true_imports = imports_via_ast(module_file)
    # Simulate the #494 bug: the pyeye imports edge silently DROPPED "pkg.sub".
    claimed_imports = {"os", "sibling"}
    assert claimed_imports < true_imports  # strictly missing a real import

    finding = {
        "grade": "deterministic_single",
        "axis": "layering",
        "claim": "module imports only os and sibling",
        "claimed_imports": sorted(claimed_imports),
        # Evidence that would (wrongly) corroborate the buggy fact if trusted.
        "evidence": "pyeye imports edge reported {os, sibling}",
    }

    def corroborate(f: dict[str, Any]) -> bool:
        # INDEPENDENT: truth comes from the AST read of source, NOT f["evidence"]
        # and NOT a pyeye edge.
        claimed = set(f["claimed_imports"])
        return claimed == imports_via_ast(module_file)

    result = apply_cross_derivation_guard([finding], corroborate_fn=corroborate)

    out = result[0]
    assert out["grade"] == "ambiguous"
    assert out["possible_extractor_bug"] is True


def test_non_divergent_confident_finding_passes_untouched(tmp_path: Path) -> None:
    """A deterministic_single whose claim matches the AST stays confident."""
    module_file = _write_fixture(tmp_path)

    finding = {
        "grade": "deterministic_single",
        "axis": "layering",
        "claim": "module imports os, pkg.sub, sibling",
        "claimed_imports": sorted(imports_via_ast(module_file)),
    }

    def corroborate(f: dict[str, Any]) -> bool:
        return set(f["claimed_imports"]) == imports_via_ast(module_file)

    result = apply_cross_derivation_guard([finding], corroborate_fn=corroborate)

    out = result[0]
    assert out["grade"] == "deterministic_single"
    assert "possible_extractor_bug" not in out


# ---------------------------------------------------------------------------
# Group C — #499 third state: cannot_confirm (an unresolvable import)
# ---------------------------------------------------------------------------


def _assert_cannot_confirm(out: dict[str, Any]) -> None:
    """Neither confirmed nor flagged as a divergence: unpromoted, needs review."""
    assert out["grade"] == "ambiguous", "cannot_confirm must not stay confident"
    assert out["corroboration"] == "cannot_confirm"
    assert "possible_extractor_bug" not in out, "an unresolved import is not a divergence"


def test_cannot_confirm_verdict_is_neither_confirmed_nor_flagged() -> None:
    finding = {"grade": "deterministic_single", "claim": "x"}

    result = apply_cross_derivation_guard([finding], corroborate_fn=lambda _f: CANNOT_CONFIRM)

    _assert_cannot_confirm(result[0])
    # Input dict NOT mutated.
    assert finding == {"grade": "deterministic_single", "claim": "x"}


def test_bool_verdicts_keep_their_meaning() -> None:
    """``True``/``False`` still mean corroborated/divergent (backward compatible)."""
    findings = [
        {"grade": "deterministic_single", "claim": "ok"},
        {"grade": "deterministic_single", "claim": "bad"},
    ]
    verdicts = {"ok": True, "bad": False}

    result = apply_cross_derivation_guard(findings, corroborate_fn=lambda f: verdicts[f["claim"]])

    assert result[0] is findings[0]
    assert result[1]["grade"] == "ambiguous"
    assert result[1]["possible_extractor_bug"] is True
    assert result[1]["corroboration"] == "divergent"


def test_named_verdicts_match_the_bools() -> None:
    findings = [
        {"grade": "deterministic_single", "claim": "ok"},
        {"grade": "deterministic_single", "claim": "bad"},
    ]
    verdicts = {"ok": CORROBORATED, "bad": DIVERGENT}

    result = apply_cross_derivation_guard(findings, corroborate_fn=lambda f: verdicts[f["claim"]])

    assert result[0] is findings[0]
    assert result[1]["possible_extractor_bug"] is True


def test_unknown_verdict_is_rejected() -> None:
    """A typo'd verdict must not silently read as agreement or divergence."""
    finding = {"grade": "deterministic_single", "claim": "x"}

    with pytest.raises(ValueError, match="corroborat"):
        apply_cross_derivation_guard([finding], corroborate_fn=lambda _f: "agree")


# --- corroborate_imports: the import-fact corroborator ----------------------


def test_corroborate_imports_agreement(tmp_path: Path) -> None:
    module_file = _write_fixture(tmp_path)
    verdict = corroborate_imports({"os", "pkg.sub", "sibling"}, [], module_file)
    assert verdict == CORROBORATED


def test_corroborate_imports_dropped_import_is_divergent(tmp_path: Path) -> None:
    """#494: a real import silently missing (not listed as unresolved) is a divergence."""
    module_file = _write_fixture(tmp_path)
    assert corroborate_imports({"os", "sibling"}, [], module_file) == DIVERGENT


def test_corroborate_imports_invented_import_is_divergent(tmp_path: Path) -> None:
    module_file = _write_fixture(tmp_path)
    claimed = {"os", "pkg.sub", "sibling", "json"}
    assert corroborate_imports(claimed, [], module_file) == DIVERGENT


def test_unresolved_import_is_cannot_confirm_not_divergence(tmp_path: Path) -> None:
    """The edge side reports ``pkg.sub.thing`` in ``unresolved_imports``: it is
    missing from the claim because the edge could not resolve it, which is not
    evidence of an extractor bug, and not agreement either."""
    module_file = _write_fixture(tmp_path)

    verdict = corroborate_imports({"os", "sibling"}, ["pkg.sub.thing"], module_file)

    assert verdict == CANNOT_CONFIRM


def test_unresolved_import_also_claimed_still_cannot_confirm(tmp_path: Path) -> None:
    """Unresolved on the edge side never reads as silent agreement."""
    module_file = _write_fixture(tmp_path)

    verdict = corroborate_imports({"os", "pkg.sub", "sibling"}, ["pkg.sub.thing"], module_file)

    assert verdict == CANNOT_CONFIRM


def test_real_divergence_wins_over_unresolved(tmp_path: Path) -> None:
    """An unexplained drop is still a divergence even when another import is unresolved."""
    module_file = _write_fixture(tmp_path)

    # "os" is dropped with no unresolved entry covering it; pkg.sub is unresolved.
    verdict = corroborate_imports({"sibling"}, ["pkg.sub.thing"], module_file)

    assert verdict == DIVERGENT


def test_unparseable_source_is_cannot_confirm(tmp_path: Path) -> None:
    """The AST side cannot derive anything (e.g. newer syntax, #703): cannot confirm."""
    module_file = tmp_path / "broken.py"
    module_file.write_text("def f(:\n    pass\n", encoding="utf-8")

    assert corroborate_imports({"os"}, [], module_file) == CANNOT_CONFIRM


def test_unreadable_source_is_cannot_confirm(tmp_path: Path) -> None:
    assert corroborate_imports({"os"}, [], tmp_path / "missing.py") == CANNOT_CONFIRM


def test_499_acceptance_unresolvable_fact_is_surfaced_for_review(tmp_path: Path) -> None:
    """#499 acceptance: a finding whose import fact is unresolvable on the edge side
    is surfaced as cannot-confirm, neither confirmed nor flagged as a divergence."""
    module_file = _write_fixture(tmp_path)
    finding = {
        "grade": "deterministic_single",
        "axis": "layering",
        "claim": "module imports only os and sibling",
        "claimed_imports": ["os", "sibling"],
        "unresolved_imports": ["pkg.sub.thing"],
    }

    def corroborate(f: dict[str, Any]) -> str:
        return corroborate_imports(set(f["claimed_imports"]), f["unresolved_imports"], module_file)

    result = apply_cross_derivation_guard([finding], corroborate_fn=corroborate)

    _assert_cannot_confirm(result[0])
