"""The structure kind's curation inputs and outputs for /arch-facts (#1175, #1173).

Areas and pairs as committed data files, rejected pairs, the curated-pairs fact
``<p>.pairs.<area>``, an unassigned module as a coverage gap, and
``imported_by`` as the set of importing areas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import cli, config, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.extractors import structure as kind
from pyeye.docs_facts.facts import Advisory, ExtractionError, Fact
from pyeye.docs_facts.structure import options
from tests.utils.docs_facts_config import write_config
from tests.utils.structure import write_project

AREAS_TOML = """\
[areas]
root = ["pkg"]
io = ["pkg.paths", "pkg.util"]
config = ["pkg.cfg", "pkg.settings"]
legacy = ["pkg.old"]
shapes = ["pkg.shapes"]
"""

#: Curated: a delegation and an unverified pair. Rejected: a scored candidate,
#: and a pair naming a handle the dump lacks.
PAIRS = {
    "pair": [
        {"a": "pkg.paths.helper", "b": "pkg.util.normalise_path"},
        {"a": "pkg.cfg.load_config", "b": "pkg.settings.read_config"},
        {"a": "pkg.old.old_helper", "b": "pkg.paths.helper", "rejected": "an old shim"},
        {"a": "pkg.gone.x", "b": "pkg.paths.helper", "rejected": "stale"},
    ]
}


def _facts(items: list[Any]) -> dict[str, Fact]:
    return {i.id: i for i in items if isinstance(i, Fact)}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = write_project(tmp_path_factory.mktemp("curation"))
    (root / "arch").mkdir()
    (root / "arch/areas.toml").write_text(AREAS_TOML, encoding="utf-8")
    (root / "arch/pairs.json").write_text(json.dumps(PAIRS), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def extracted(project: Path) -> list[Any]:
    opts = options.parse(
        {
            "areas": "arch/areas.toml",
            "pairs": "arch/pairs.json",
            "min_score": 0.0,
            "candidates_page": "docs/candidates.md",
        }
    )
    return kind.extract(project, opts)


@pytest.fixture(scope="module")
def facts(extracted: list[Any]) -> dict[str, Fact]:
    return _facts(extracted)


class TestOptions:
    def test_a_string_names_a_data_file(self) -> None:
        opts = options.parse({"areas": "a/areas.toml", "pairs": "a/pairs.yaml"})
        assert (opts.areas_file, opts.pairs_file) == ("a/areas.toml", "a/pairs.yaml")
        assert (opts.areas, opts.pairs, opts.rejected) == ((), (), ())

    def test_inline_pairs_take_tables_and_rejections(self) -> None:
        opts = options.parse(
            {"pairs": [["a.x", "b.y"], {"a": "c.z", "b": "d.w", "rejected": "unrelated"}]}
        )
        assert opts.pairs == (("a.x", "b.y"),)
        assert opts.rejected == (("c.z", "d.w", "unrelated"),)

    @pytest.mark.parametrize(
        ("table", "match"),
        [
            ({"pairs": [{"a": "a.x", "b": "b.y", "why": "?"}]}, "unknown key"),
            ({"pairs": [{"a": "a.x", "b": "b.y", "rejected": " "}]}, "non-empty reason"),
            ({"pairs": [{"a": "a.x", "b": "b.y", "rejected": 3}]}, "non-empty reason"),
            ({"pairs": [{"a": "a.x"}]}, "two non-empty handles"),
            (
                {"pairs": [["a.x", "b.y"], {"a": "b.y", "b": "a.x", "rejected": "no"}]},
                "repeats the pair",
            ),
            ({"areas": "/abs/areas.toml"}, "'areas' must be a path inside"),
            ({"areas": "../areas.toml"}, "'areas' must be a path inside"),
            ({"pairs": "C:/pairs.toml"}, "'pairs' must be a path inside"),
            ({"pairs": "..\\pairs.toml"}, "'pairs' must be a path inside"),
            ({"pairs": 3}, "'pairs' must be a list"),
        ],
    )
    def test_bad_values(self, table: dict[str, Any], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            options.parse(table)


class TestLoad:
    def test_reads_toml_json_and_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "areas.yaml").write_text("areas:\n  io: [pkg.paths]\n", encoding="utf-8")
        (tmp_path / "pairs.toml").write_text(
            '[[pair]]\na = "a.x"\nb = "b.y"\n\n[[pair]]\na = "c.z"\nb = "d.w"\nrejected = "no"\n',
            encoding="utf-8",
        )
        loaded = options.load(
            options.parse({"areas": "areas.yaml", "pairs": "pairs.toml"}), tmp_path
        )
        assert loaded.areas == (("io", ("pkg.paths",)),)
        assert loaded.pairs == (("a.x", "b.y"),)
        assert loaded.rejected == (("c.z", "d.w", "no"),)

    def test_inline_options_are_returned_as_they_are(self, tmp_path: Path) -> None:
        opts = options.parse({"areas": {"io": ["pkg.paths"]}})
        assert options.load(opts, tmp_path) is opts

    @pytest.mark.parametrize(
        ("name", "text", "match"),
        [
            ("missing.toml", None, "doesn't exist"),
            ("areas.ini", "[areas]\n", "unknown format"),
            ("areas.toml", "[other]\nio = []\n", "with a 'areas' key"),
            ("areas.toml", "[areas]\nio = []\n", "is empty"),
            ("areas.toml", '[areas]\n"bad.id" = ["x"]\n', "area 'bad.id'"),
        ],
    )
    def test_bad_areas_files_name_the_file(
        self, tmp_path: Path, name: str, text: str | None, match: str
    ) -> None:
        if text is not None:
            (tmp_path / name).write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=match) as raised:
            options.load(options.parse({"areas": name}), tmp_path)
        assert name in str(raised.value)

    def test_a_bad_pair_in_a_file_names_its_position(self, tmp_path: Path) -> None:
        (tmp_path / "p.json").write_text(json.dumps({"pair": [["a.x", "a.x"]]}), encoding="utf-8")
        with pytest.raises(ValueError, match=r"p.json pair\[0\] pairs 'a.x' with itself"):
            options.load(options.parse({"pairs": "p.json"}), tmp_path)

    def test_extract_reports_a_bad_file_as_an_extraction_error(self, tmp_path: Path) -> None:
        with pytest.raises(ExtractionError, match="doesn't exist"):
            kind.extract(tmp_path, options.parse({"areas": "nope.toml"}))


class TestCuratedPairsFact:
    def test_each_curated_pair_is_a_fact_in_both_areas(self, facts: dict[str, Fact]) -> None:
        delegates = {
            "a": "pkg.paths.helper",
            "b": "pkg.util.normalise_path",
            "label": "delegates",
            "deprecated": [],
            "measured": True,
        }
        assert facts["arch.pairs.io"].value == [delegates]  # both sides are in io
        unverified = facts["arch.pairs.config"].value
        assert [(p["a"], p["b"], p["label"]) for p in unverified] == [
            ("pkg.cfg.load_config", "pkg.settings.read_config", "possible duplicate (unverified)")
        ]
        assert "possible duplicate (unverified)" in facts["arch.pairs.config"].markdown

    def test_every_area_has_one_even_without_pairs(self, facts: dict[str, Fact]) -> None:
        assert facts["arch.pairs.shapes"].value == []
        assert facts["arch.pairs.shapes"].markdown == "No curated pair touches this area."

    def test_a_deprecated_side_is_noted(self) -> None:
        md = kind.pairs_markdown(
            [
                {
                    "a": "a.x",
                    "b": "b.y",
                    "label": "possible duplicate (unverified)",
                    "deprecated": ["a.x"],
                    "measured": False,
                }
            ]
        )
        assert md == (
            "- `a.x` and `b.y`: possible duplicate (unverified) "
            "(`a.x` is deprecated; calls unmeasured)"
        )


class TestRejectedPairs:
    def test_never_labelled_or_listed_again(
        self, facts: dict[str, Fact], extracted: list[Any]
    ) -> None:
        rejected = {"pkg.old.old_helper", "pkg.paths.helper"}
        for fid, fact in facts.items():
            if fid.startswith(("arch.pairs.", "arch.cross.")):
                pairs = fact.value if isinstance(fact.value, list) else fact.value["labelled"]
                assert all({p["a"], p["b"]} != rejected for p in pairs), fid
        (page,) = [i for i in extracted if isinstance(i, Advisory)]
        assert "`pkg.old.old_helper`" not in page.text  # scored at min_score 0, but rejected

    def test_a_rejected_pair_naming_an_unknown_handle_is_a_gap(
        self, facts: dict[str, Fact]
    ) -> None:
        assert facts["arch.coverage.gaps"].value["unknown_pairs"] == [
            "pkg.gone.x ~ pkg.paths.helper (not in the dump: pkg.gone.x) (rejected)"
        ]


class TestUnassigned:
    def test_a_module_in_no_area_is_a_gap(self, facts: dict[str, Fact]) -> None:
        assert facts["arch.coverage.gaps"].value["unassigned"] == ["pkg.hooks", "pkg.star"]

    def test_the_rule_fails_on_it(self, facts: dict[str, Fact]) -> None:
        problems = kind.coverage_problems("arch", facts)
        assert "unassigned in the arch dump: pkg.hooks" in problems

    def test_without_areas_nothing_is_unassigned(self) -> None:
        assert kind.unassigned({"a": "a", "b": "b"}, ()) == ()

    def test_a_module_in_two_areas_still_stops_extraction(self) -> None:
        with pytest.raises(ExtractionError, match="matches areas"):
            kind.area_of(["a.x"], [("one", ("a.*",)), ("two", ("*.x",))])


class TestImportedByArea:
    def test_is_the_set_of_importing_areas(self, facts: dict[str, Fact]) -> None:
        # pkg.util (area io) imports pkg.paths; the importing package's area too
        assert facts["arch.imported_by.pkg.paths"].value == ["io"]
        assert facts["arch.imported_by.pkg.paths"].markdown == "Imported from areas: `io`."

    def test_without_areas_it_stays_top_level_packages(self, project: Path) -> None:
        built = _facts(kind.extract(project, options.parse({"include": ["pkg/*"]})))
        assert built["arch.imported_by.pkg.paths"].value == ["pkg"]

    def test_importers_outside_the_scope_are_in_no_area(self) -> None:
        from pyeye.docs_facts.structure import dump

        module = dump.Module("m", "m.py", "", 2, ("a.x", "tests.t"), (), (), (), True)
        assert kind.importing_areas(module, {"a.x": "core", "m": "core"}) == ["core"]
        unmeasured = dump.Module("m", "m.py", "", None, (), (), (), (), True)
        assert kind.importing_areas(unmeasured, {}) is None


class TestThroughTheConfig:
    def test_data_files_named_in_config_reach_check(self, project: Path) -> None:
        doc = DocEntry("ARCH.md", "human", "prose")
        (project / "ARCH.md").write_text(
            "# Arch\n\n<!-- fact:begin arch.pairs.config -->x<!-- fact:end -->\n",
            encoding="utf-8",
        )
        write_config(
            project,
            [doc],
            changelog=None,
            extractors=[
                {"kind": "structure", "areas": "arch/areas.toml", "pairs": "arch/pairs.json"}
            ],
            reference_only=["arch"],
        )
        result = cli.plan(project, setup=config.load(project))
        assert "possible duplicate (unverified)" in result.outputs["ARCH.md"]
        assert f"{rules.STRUCTURE_COVERAGE}: unassigned in the arch dump: pkg.star" in (
            result.problems
        )
