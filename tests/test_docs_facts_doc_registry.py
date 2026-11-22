"""pyeye's doc registry as a data file, read without importing anything (#1107).

``docs/facts/docs.toml`` holds the same entries as the typed
:data:`pyeye.docs_facts.docs.DOCS`. Until the typed list is deleted, these tests
run the two side by side: the entries are equal, field for field and in order,
and a plan built from the file is byte-identical to one built from the typed
list, with nothing stale.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pyeye.docs_facts import doc_registry, docs
from pyeye.docs_facts.cli import plan, stale
from pyeye.docs_facts.config import ConfigError
from pyeye.docs_facts.pages import PAGES
from pyeye.docs_facts.setup import pyeye_setup

ROOT = Path(__file__).resolve().parent.parent


def _pyeye_file() -> tuple[docs.DocEntry, ...]:
    return doc_registry.read(ROOT, doc_registry.PYEYE_REGISTRY)


class TestPyeyesRegistryFile:
    def test_the_file_holds_the_typed_registry(self) -> None:
        """Equal entries, in the same order: path, audience, kind, allow, covers, site."""
        assert _pyeye_file() == docs.DOCS

    def test_each_generated_page_is_listed_as_a_reference_entry(self) -> None:
        """Reference pages are listed explicitly (#1107 Q3), exactly the generated ones."""
        listed = {e.path for e in _pyeye_file() if e.kind == "reference"}
        assert listed == set(PAGES)

    def test_a_plan_from_the_file_is_byte_identical(self) -> None:
        """``generate`` would write the same text with either registry."""
        typed = plan(ROOT)
        from_file = plan(ROOT, setup=replace(pyeye_setup(), docs=_pyeye_file()))
        assert from_file.outputs == typed.outputs
        assert from_file.problems == typed.problems
        assert from_file.notes == typed.notes

    def test_generate_writes_nothing_and_check_passes(self) -> None:
        result = plan(ROOT, setup=replace(pyeye_setup(), docs=_pyeye_file()))
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
