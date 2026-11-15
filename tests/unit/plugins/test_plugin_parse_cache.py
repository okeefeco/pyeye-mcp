"""Plugins parse through the shared ``file_artifact_cache`` (#699).

5505cad moved ``AnalyzerPlugin._parse_source`` off the shared AST cache, on the
suspicion that it caused #684. #684 turned out to be parso's in-memory cache GC
(fixed in #706), so plugins go back to the one parse/cache implementation that the
primitives and handle enrichment use (#629). The #622 contract is unchanged: a
file that can't be read or parsed is skipped with a warning, and nothing else is
swallowed.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

import pytest

from pyeye import file_artifact_cache
from pyeye.plugins.pydantic import PydanticPlugin

MODEL = "from pydantic import BaseModel\n\n\nclass User(BaseModel):\n    name: str\n"


def _plugin(root: Path) -> PydanticPlugin:
    return PydanticPlugin(str(root))


class TestSharedCache:
    def test_plugin_gets_the_shared_cached_tree(self, tmp_path: Path) -> None:
        path = tmp_path / "models.py"
        path.write_text(MODEL)

        tree = _plugin(tmp_path)._parse_source(path, path.read_text())

        assert tree is not None
        # The very object the primitives get: one parse, one cache.
        assert tree is file_artifact_cache.get_ast(path)

    def test_two_plugin_walks_parse_once(self, tmp_path: Path) -> None:
        path = tmp_path / "models.py"
        path.write_text(MODEL)
        plugin = _plugin(tmp_path)

        first = plugin._parse_source(path, path.read_text())
        second = plugin._parse_source(path, path.read_text())

        assert first is second

    def test_an_edited_file_is_reparsed(self, tmp_path: Path) -> None:
        path = tmp_path / "models.py"
        path.write_text(MODEL)
        plugin = _plugin(tmp_path)
        before = plugin._parse_source(path, path.read_text())

        path.write_text(MODEL + "\n\nclass Admin(User):\n    pass\n")
        stat = path.stat()
        # Make the mtime change visible even on coarse-mtime filesystems.
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        after = plugin._parse_source(path, path.read_text())

        assert after is not before
        assert after is not None
        assert [n.name for n in after.body if isinstance(n, ast.ClassDef)] == ["User", "Admin"]

    async def test_find_models_still_finds_models(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text(MODEL)

        models = await _plugin(tmp_path).find_models()

        assert [m["name"] for m in models] == ["User"]


class TestReadParseContract:
    """#622: skip only what can't be read or parsed, and say so."""

    def test_syntax_error_is_skipped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "broken.py"
        path.write_text("class Broken(:\n")
        caplog.set_level(logging.WARNING)

        assert _plugin(tmp_path)._parse_source(path, path.read_text()) is None
        assert any(
            "error parsing" in r.getMessage() and "broken.py" in r.getMessage()
            for r in caplog.records
        )

    def test_file_gone_after_read_is_skipped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "gone.py"
        path.write_text(MODEL)
        content = path.read_text()
        path.unlink()
        caplog.set_level(logging.WARNING)

        assert _plugin(tmp_path)._parse_source(path, content) is None
        assert any(
            "error reading" in r.getMessage() and "gone.py" in r.getMessage()
            for r in caplog.records
        )

    def test_undecodable_file_is_skipped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "latin1.py"
        path.write_bytes(b"name = '\xe9'\n")
        caplog.set_level(logging.WARNING)

        assert _plugin(tmp_path)._parse_source(path, "name = 'e'\n") is None
        assert any("latin1.py" in r.getMessage() for r in caplog.records)

    def test_unexpected_errors_propagate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "models.py"
        path.write_text(MODEL)

        def boom(_path: object) -> object:
            raise RuntimeError("cache broke")

        monkeypatch.setattr(file_artifact_cache, "get_ast", boom)

        with pytest.raises(RuntimeError, match="cache broke"):
            _plugin(tmp_path)._parse_source(path, path.read_text())
