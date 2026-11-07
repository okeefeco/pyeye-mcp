"""The dead standalone-scan options are gone from the 2.0 surface (#513, #253).

``configure_packages`` used to accept ``recursive``, ``file_pattern`` and
``exclude_patterns`` and persist them under ``standalone`` in ``.pyeye.json``.
Nothing read them: their only consumer, ``JediAnalyzer._discover_standalone_files``,
lost its last caller when ``find_references`` was removed (#505). Even with a
caller, ``exclude_patterns`` was never read from config at all. Standalone
directories are scanned wholesale via ``get_project_files``.

So the options were removed rather than shipped as a capability that silently
does nothing. That also brings ``configure_packages`` to 4 parameters (#253).
Existing ``.pyeye.json`` files that still carry the keys load fine. The keys are
ignored with a warning, and ``configure_packages`` reports them back instead of
pretending they apply.
"""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig, create_example_config
from pyeye.mcp.server import configure_packages, mcp

_REMOVED = ("recursive", "file_pattern", "exclude_patterns")


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A temp project as cwd (``configure_packages`` loads config from ``.``)."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("")
    monkeypatch.chdir(tmp_path)
    with patch("pyeye.mcp.server.get_project_manager", return_value=Mock()):
        yield tmp_path


def _saved(project: Path) -> dict:
    return json.loads((project / ".pyeye.json").read_text())


class TestConfigurePackagesSurface:
    def test_signature_has_no_dead_standalone_options(self):
        assert list(inspect.signature(configure_packages).parameters) == [
            "packages",
            "namespaces",
            "standalone_dirs",
            "save",
        ]

    def test_saves_only_dirs_under_standalone(self, project):
        result = configure_packages(standalone_dirs=["scripts"], save=True)

        assert _saved(project)["standalone"] == {"dirs": ["scripts"]}
        assert result["standalone"] == {"dirs": ["scripts"]}
        assert "warnings" not in result  # absent, not empty, when nothing is ignored

    def test_reports_legacy_keys_already_in_config(self, project):
        legacy = {"dirs": ["scripts"], "recursive": False, "exclude_patterns": ["*_gen.py"]}
        (project / ".pyeye.json").write_text(json.dumps({"standalone": legacy}))

        result = configure_packages(packages=["."], save=False)

        assert result["standalone"] == {"dirs": ["scripts"]}
        assert len(result["warnings"]) == 1
        warning = result["warnings"][0]
        assert "standalone.exclude_patterns" in warning
        assert "standalone.recursive" in warning
        assert "#513" in warning


class TestOldClients:
    async def test_removed_arguments_are_tolerated_not_applied(self, project):
        """A pre-2.0 client passing a removed option gets no error, and the
        response shows only what actually applies."""
        result = await mcp.call_tool(
            "configure_packages",
            {"standalone_dirs": ["scripts"], "recursive": False, "exclude_patterns": ["x"]},
        )

        payload = json.loads(result.content[0].text)
        assert payload["standalone"] == {"dirs": ["scripts"]}
        assert _saved(project)["standalone"] == {"dirs": ["scripts"]}


class TestProjectConfigTolerance:
    def test_legacy_keys_are_ignored_with_a_warning(self, tmp_path, caplog):
        legacy = {"dirs": ["scripts"], "recursive": True, "file_pattern": "*.py"}
        (tmp_path / ".pyeye.json").write_text(json.dumps({"standalone": legacy}))

        with caplog.at_level(logging.WARNING, logger="pyeye.config"):
            config = ProjectConfig(str(tmp_path))
            assert config.get_standalone_config() == {"dirs": ["scripts"]}

        assert config.get_ignored_standalone_keys() == ["file_pattern", "recursive"]
        assert any("standalone.file_pattern" in r.getMessage() for r in caplog.records)

    def test_no_standalone_section(self, tmp_path):
        config = ProjectConfig(str(tmp_path))
        assert config.get_standalone_config() == {"dirs": []}
        assert config.get_ignored_standalone_keys() == []

    def test_example_config_has_no_removed_keys(self, tmp_path):
        create_example_config(str(tmp_path))
        example = json.loads((tmp_path / ".pyeye.json.example").read_text())

        assert not set(_REMOVED) & set(example["standalone"])


def test_dead_discovery_method_is_gone():
    assert not hasattr(JediAnalyzer, "_discover_standalone_files")
