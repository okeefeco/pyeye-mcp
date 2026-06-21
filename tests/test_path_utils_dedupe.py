"""Tests for ``path_utils.dedupe_paths`` — the shared root-list deduper (#423 review).

``dedupe_paths`` is the single dedupe-by-resolved-identity helper that both
``edges._analyzer_roots`` (namespace-portion union; original paths kept) and
``resolve._project_roots`` (root-promotion comparison; resolved paths) ride on.
"""

from __future__ import annotations

from pathlib import Path

from pyeye.path_utils import dedupe_paths


class TestDedupePaths:
    def test_preserves_first_seen_order(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        c = tmp_path / "c"
        for d in (a, b, c):
            d.mkdir()
        assert dedupe_paths([a, b, c]) == [a, b, c]

    def test_dedupes_by_resolved_identity_keeping_first(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        a.mkdir()
        # Two spellings of the same dir (trailing "." component) collapse to one;
        # the FIRST occurrence is kept.
        dupe = tmp_path / "a" / "."
        result = dedupe_paths([a, dupe, a])
        assert result == [a]

    def test_returns_original_paths_by_default(self, tmp_path: Path) -> None:
        # default resolve_output=False → caller-facing (unresolved) paths returned.
        link_target = tmp_path / "real"
        link_target.mkdir()
        result = dedupe_paths([link_target])
        assert result == [link_target]

    def test_resolve_output_returns_resolved_paths(self, tmp_path: Path) -> None:
        d = tmp_path / "d"
        d.mkdir()
        result = dedupe_paths([d], resolve_output=True)
        assert result == [d.resolve()]

    def test_skips_unresolvable_paths_without_raising(self, tmp_path: Path) -> None:
        good = tmp_path / "good"
        good.mkdir()
        # A path with a NUL byte cannot be resolved → skipped, not raised.
        bad = Path("bad\x00name")
        result = dedupe_paths([good, bad])
        assert result == [good]

    def test_accepts_str_inputs(self, tmp_path: Path) -> None:
        d = tmp_path / "s"
        d.mkdir()
        assert dedupe_paths([str(d)]) == [d]

    def test_empty_input(self) -> None:
        assert dedupe_paths([]) == []
