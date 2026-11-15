"""Top-level config keys that nothing reads are ignored with a warning (#581).

The docs and ``create_example_config`` described ``exclude``,
``exclude_patterns``, ``cache``, ``analysis``, ``performance``, ``plugins``,
``default_packages``, ``logging`` and ``watch_exclude`` as if they worked, but no
code in ``src/pyeye`` reads them. As with the dead ``standalone`` options
(#513), configs that carry them still load. Each load logs a warning, and
``configure_packages`` reports the keys instead of pretending they apply.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.config import IGNORED_TOP_LEVEL_KEYS, ProjectConfig, create_example_config
from pyeye.mcp.server import configure_packages

_SRC = Path(__file__).resolve().parents[1] / "src" / "pyeye"


def _write(path: Path, data: dict) -> None:
    (path / ".pyeye.json").write_text(json.dumps(data))


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "has never read these keys" in r.getMessage()]


def test_no_source_reads_an_ignored_key():
    """Guard: if code starts reading one of these keys, it must leave the list."""
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in _SRC.rglob("*.py")
        if p.name != "config.py" or p.parent != _SRC
    )
    config_py = (_SRC / "config.py").read_text(encoding="utf-8")
    for key in IGNORED_TOP_LEVEL_KEYS:
        read = rf"""config(?:\.config)?(?:\.get\(|\[)\s*["']{key}["']"""
        assert not re.search(read, src), key
        assert not re.search(read, config_py), key


@pytest.mark.parametrize("key", IGNORED_TOP_LEVEL_KEYS)
def test_each_ignored_key_warns_on_load(tmp_path, caplog, key):
    _write(tmp_path, {"packages": ["."], key: {"anything": 1}})

    with caplog.at_level(logging.WARNING):
        config = ProjectConfig(str(tmp_path))

    assert config.get_ignored_top_level_keys() == [key]
    (message,) = _warnings(caplog)
    assert f"Ignoring {key} in the pyeye config" in message
    assert "#581" in message


def test_keys_are_listed_sorted_in_one_warning(tmp_path, caplog):
    _write(tmp_path, {"packages": ["."], "exclude": [], "cache": {}, "analysis": {}})

    with caplog.at_level(logging.WARNING):
        config = ProjectConfig(str(tmp_path))

    assert config.get_ignored_top_level_keys() == ["analysis", "cache", "exclude"]
    (message,) = _warnings(caplog)
    assert "Ignoring analysis, cache, exclude in" in message


def test_pyproject_tool_section_is_checked_too(tmp_path, caplog):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pyeye]\npackages = ["."]\n\n[tool.pyeye.cache]\nttl_seconds = 300\n'
    )

    with caplog.at_level(logging.WARNING):
        config = ProjectConfig(str(tmp_path))

    assert config.get_ignored_top_level_keys() == ["cache"]


def test_live_config_does_not_warn(tmp_path, caplog):
    _write(tmp_path, {"packages": ["."], "namespaces": {}, "standalone": {"dirs": []}})

    with caplog.at_level(logging.WARNING):
        config = ProjectConfig(str(tmp_path))

    assert config.get_ignored_top_level_keys() == []
    assert not _warnings(caplog)


def test_ignored_keys_still_load(tmp_path):
    """A config carrying them keeps working; only the dead keys are ignored."""
    (tmp_path / "lib").mkdir()
    _write(tmp_path, {"packages": ["lib"], "exclude": ["**/tests/**"]})

    config = ProjectConfig(str(tmp_path))

    assert (tmp_path / "lib").resolve().as_posix() in [
        Path(p).resolve().as_posix() for p in config.get_package_paths()
    ]


def test_example_config_has_no_ignored_keys(tmp_path):
    create_example_config(str(tmp_path))

    example = json.loads((tmp_path / ".pyeye.json.example").read_text())
    assert not set(example) & set(IGNORED_TOP_LEVEL_KEYS)


def test_committed_example_config_has_no_ignored_keys():
    example = json.loads(
        (Path(__file__).resolve().parents[1] / ".pyeye.json.example").read_text(encoding="utf-8")
    )
    assert not set(example) & set(IGNORED_TOP_LEVEL_KEYS)


class TestConfigurePackagesReportsThem:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("pyeye.mcp.server.get_project_manager", return_value=Mock()):
            yield tmp_path

    async def test_reports_ignored_top_level_keys(self, project):
        _write(project, {"exclude_patterns": ["**/build"], "cache": {"ttl_seconds": 1}})

        result = await configure_packages()

        (warning,) = result["warnings"]
        assert "Ignoring cache, exclude_patterns in" in warning

    async def test_reports_both_kinds_of_ignored_keys(self, project):
        _write(project, {"cache": {}, "standalone": {"dirs": [], "recursive": True}})

        result = await configure_packages()

        assert len(result["warnings"]) == 2
        assert any("standalone.recursive" in w for w in result["warnings"])
        assert any("Ignoring cache in" in w for w in result["warnings"])

    async def test_no_warnings_key_when_clean(self, project):
        _write(project, {"packages": ["."]})

        result = await configure_packages()

        assert "warnings" not in result
