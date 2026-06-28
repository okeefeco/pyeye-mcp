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

from pyeye.architecture_review.guard import (
    apply_cross_derivation_guard,
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
