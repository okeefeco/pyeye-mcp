"""pyeye's doc registry is a data file, read without importing anything (#1107).

``docs/facts/docs.toml`` replaced the typed ``DOCS``; it was proven equal to it,
entry for entry and in order, before the typed list was deleted. These tests
read it the way the config does, and run the reader's refusals.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyeye.docs_facts import config, doc_registry, docs
from pyeye.docs_facts.cli import plan, stale
from pyeye.docs_facts.config import ConfigError

ROOT = Path(__file__).resolve().parent.parent


class TestPyeyesRegistryFile:
    def test_the_config_reads_it(self) -> None:
        file = doc_registry.read(ROOT, doc_registry.PYEYE_REGISTRY)
        assert config.load(ROOT).docs == file
        assert len(file) > 0

    def test_generate_writes_nothing_and_check_passes(self) -> None:
        result = plan(ROOT)
        assert result.problems == []
        assert stale(ROOT, result) == []


ENTRY = {"path": "a.md", "audience": "human", "kind": "prose"}


def _write(root: Path, name: str, text: str) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")
    return name


class TestReading:
    def test_toml(self, tmp_path: Path) -> None:
        name = _write(
            tmp_path,
            "reg.toml",
            '[[doc]]\npath = "a.md"\naudience = "both"\nkind = "prose"\nsite = false\n'
            'covers = ["x.y"]\n\n[doc.allow]\n"removed-name" = ["m", "m"]\n',
        )
        (entry,) = doc_registry.read(tmp_path, name)
        assert entry == docs.DocEntry(
            "a.md", "both", "prose", allow={"removed-name": ("m", "m")}, covers=("x.y",), site=False
        )

    def test_json(self, tmp_path: Path) -> None:
        name = _write(tmp_path, "reg.json", json.dumps({"doc": [ENTRY]}))
        assert doc_registry.read(tmp_path, name) == (docs.DocEntry("a.md", "human", "prose"),)

    @pytest.mark.parametrize("suffix", [".yaml", ".yml"])
    def test_yaml(self, tmp_path: Path, suffix: str) -> None:
        name = _write(
            tmp_path, f"reg{suffix}", "doc:\n  - {path: a.md, audience: human, kind: prose}\n"
        )
        assert doc_registry.read(tmp_path, name) == (docs.DocEntry("a.md", "human", "prose"),)


class TestRefusals:
    def test_a_file_outside_the_repository(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _write(tmp_path, "reg.toml", "doc = []\n")
        with pytest.raises(ConfigError, match="outside the repository"):
            doc_registry.read(repo, "../reg.toml")

    def test_an_unknown_format(self, tmp_path: Path) -> None:
        name = _write(tmp_path, "reg.ini", "")
        with pytest.raises(ConfigError, match="unknown format"):
            doc_registry.read(tmp_path, name)

    def test_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="doesn't exist"):
            doc_registry.read(tmp_path, "reg.toml")

    @pytest.mark.parametrize("text", ['doc = "a.md"\n', "other = []\n"])
    def test_no_list_of_entries(self, tmp_path: Path, text: str) -> None:
        name = _write(tmp_path, "reg.toml", text)
        with pytest.raises(ConfigError, match="'doc' key is a list"):
            doc_registry.read(tmp_path, name)

    def test_a_json_file_that_isnt_a_table(self, tmp_path: Path) -> None:
        name = _write(tmp_path, "reg.json", "[]")
        with pytest.raises(ConfigError, match="'doc' key is a list"):
            doc_registry.read(tmp_path, name)

    def test_a_bad_entry_names_the_file_and_position(self, tmp_path: Path) -> None:
        bad = {**ENTRY, "kind": "essay"}
        name = _write(tmp_path, "reg.json", json.dumps({"doc": [ENTRY, bad]}))
        with pytest.raises(ConfigError, match=r"'reg\.json' doc\[1\]: .*kind 'essay'"):
            doc_registry.read(tmp_path, name)
