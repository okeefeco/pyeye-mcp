"""Tests for ``jedi_analyzer._parse_or_record`` (#729).

The one place a project-wide scan maps a parse failure to "disclosed": a
:class:`SyntaxError` records the file and skips it; anything else propagates
to the scan's existing handling (#704), so an internal failure is never
relabelled as a parse gap.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pyeye.analyzers.jedi_analyzer import _parse_or_record
from pyeye.path_utils import path_to_key


def test_parseable_file_returns_its_tree(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("X = 1\n", encoding="utf-8")
    unparseable: list[str] = []
    tree = _parse_or_record(f, unparseable)
    assert tree is not None and unparseable == []


def test_syntax_error_is_recorded_as_posix(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_text("x = = 1\n", encoding="utf-8")
    unparseable: list[str] = []
    assert _parse_or_record(f, unparseable) is None
    assert unparseable == [path_to_key(f)]
    assert "\\" not in unparseable[0]


def test_other_failures_propagate(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("X = 1\n", encoding="utf-8")
    unparseable: list[str] = []
    with (
        patch(
            "pyeye.analyzers.jedi_analyzer.file_artifact_cache.get_ast", side_effect=OSError("disk")
        ),
        pytest.raises(OSError),
    ):
        _parse_or_record(f, unparseable)
    assert unparseable == []
