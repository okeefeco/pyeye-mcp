"""The ``structure`` kind: architecture facts, its rules and its advisory page (#1092)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import cli, config, kinds, registry, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.extractors import structure as kind
from pyeye.docs_facts.facts import Advisory, ExtractionError, Fact
from pyeye.docs_facts.structure import (
    candidates as candidates_mod,
    coverage,
    dump,
    options,
    relations as relations_mod,
)
from tests.utils.docs_facts_config import write_config
from tests.utils.structure import write_project


def _facts(items: list[Any]) -> dict[str, Fact]:
    return {i.id: i for i in items if isinstance(i, Fact)}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_project(tmp_path_factory.mktemp("structure_kind"))


@pytest.fixture(scope="module")
def extracted(project: Path) -> list[Any]:
    opts = options.parse(
        {"min_score": 0.0, "within_areas": True, "candidates_page": "docs/candidates.md"}
    )
    return kind.extract(project, opts)


@pytest.fixture(scope="module")
def facts(extracted: list[Any]) -> dict[str, Fact]:
    return _facts(extracted)


class TestRegistration:
    def test_structure_is_a_generic_built_in_kind(self) -> None:
        assert kinds.BUILT_IN_KINDS["structure"] is kind.structure

    def test_factory_owns_its_prefix_and_brings_its_rules(self) -> None:
        extractor = kind.structure({"prefix": "layout"})
        assert extractor.prefixes == ("layout",)
        assert [r.id for r in extractor.rules] == [
            rules.LAYERING,
            rules.STRUCTURE_COVERAGE,
            rules.ARCHITECTURE_HANDLES,
        ]
        assert {need for r in extractor.rules for need in r.requires} == {
            "layout.imports.",
            "layout.coverage.gaps",
            "layout.members.",
        }

    def test_bad_options_are_a_kind_options_error(self) -> None:
        with pytest.raises(kinds.KindOptionsError, match="unknown option"):
            kind.structure({"nope": 1})

    def test_config_names_it_as_data(self, tmp_path: Path) -> None:
        write_config(tmp_path, [], extractors=[{"kind": "structure", "include": ["pkg/*"]}])
        setup = config.load(tmp_path)
        assert [e.name for e in setup.extractors] == ["structure"]
        assert {rules.LAYERING, rules.STRUCTURE_COVERAGE} <= {r.id for r in setup.rules}

    def test_config_error_names_the_entry(self, tmp_path: Path) -> None:
        write_config(tmp_path, [], extractors=[{"kind": "structure", "min_score": -1}])
        with pytest.raises(config.ConfigError, match=r"extractors\[0\] \(structure\).*min_score"):
            config.load(tmp_path)

    def test_two_structure_kinds_are_refused(self, tmp_path: Path) -> None:
        write_config(
            tmp_path,
            [],
            extractors=[{"kind": "structure"}, {"kind": "structure", "prefix": "other"}],
        )
        with pytest.raises(config.ConfigError, match="rule 'layering' comes from both"):
            config.load(tmp_path)

    def test_a_rules_list_may_name_the_kinds_rules(self, tmp_path: Path) -> None:
        write_config(
            tmp_path, [], extractors=[{"kind": "structure"}], rules=[rules.STRUCTURE_COVERAGE]
        )
        assert [r.id for r in config.load(tmp_path).rules] == [rules.STRUCTURE_COVERAGE]

    def test_without_the_kind_its_rules_are_unknown(self, tmp_path: Path) -> None:
        write_config(tmp_path, [], rules=[rules.LAYERING])
        with pytest.raises(config.ConfigError, match="unknown rule"):
            config.load(tmp_path)


class TestOptions:
    def test_defaults(self) -> None:
        opts = options.parse({})
        assert (opts.areas, opts.min_score, opts.candidates_page, opts.pairs) == (
            (),
            0.9,
            None,
            (),
        )

    def test_pairs(self) -> None:
        opts = options.parse({"pairs": [["a.x", "b.y"], ["c.z", "a.x"]]})
        assert opts.pairs == (("a.x", "b.y"), ("c.z", "a.x"))

    @pytest.mark.parametrize(
        ("pairs", "match"),
        [
            ("a.x", "'pairs' must be a list"),
            ([["a.x"]], r"pairs\[0\] must be two"),
            ([["a.x", ""]], r"pairs\[0\] must be two"),
            ([["a.x", 3]], r"pairs\[0\] must be two"),
            ([["a.x", "a.x"]], "with itself"),
            ([["a.x", "b.y"], ["b.y", "a.x"]], r"pairs\[1\] repeats"),
        ],
    )
    def test_bad_pairs(self, pairs: Any, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            options.parse({"pairs": pairs})

    def test_areas_and_page(self) -> None:
        opts = options.parse(
            {"areas": {"io": ["pkg.paths", "pkg.util"]}, "candidates_page": "docs/c.md"}
        )
        assert opts.areas == (("io", ("pkg.paths", "pkg.util")),)
        assert opts.candidates_page == "docs/c.md"

    @pytest.mark.parametrize(
        ("table", "match"),
        [
            ({"areas": ["x"]}, "'areas' must be a table"),
            ({"areas": {"-bad": ["x"]}}, "area '-bad'"),
            ({"areas": {"a.b": ["x"]}}, "area 'a.b'"),
            ({"areas": {"a": []}}, "areas.a"),
            ({"min_score": "1"}, "min_score"),
            ({"min_score": True}, "min_score"),
            ({"min_score": -0.5}, "min_score"),
            ({"candidates_page": "/abs.md"}, "candidates_page"),
            ({"candidates_page": "../out.md"}, "candidates_page"),
            ({"candidates_page": ""}, "candidates_page"),
        ],
    )
    def test_bad_values(self, table: dict[str, Any], match: str) -> None:
        with pytest.raises(ValueError, match=match):
            options.parse(table)


class TestAreas:
    def test_unmatched_module_is_its_own_area(self) -> None:
        assert kind.area_of(["a.x", "b"], [("first", ("a.*",))]) == {"a.x": "first", "b": "b"}

    def test_module_in_two_areas_is_refused(self) -> None:
        with pytest.raises(ExtractionError, match="matches areas"):
            kind.area_of(["a.x"], [("one", ("a.*",)), ("two", ("*.x",))])

    def test_unmatched_module_named_like_an_area_is_refused(self) -> None:
        with pytest.raises(ExtractionError, match="named like area"):
            kind.area_of(["io", "a.x"], [("io", ("a.*",))])


class TestFacts:
    def test_members_of_modules_and_classes(self, facts: dict[str, Fact]) -> None:
        paths = facts["arch.members.pkg.paths"].value
        assert paths["members"] == [
            {
                "name": "helper",
                "kind": "function",
                "signature": "helper(path: str, strict: bool=False) -> str",
                "summary": "Normalise a file path.",
            }
        ]
        square = facts["arch.members.pkg.shapes.Square"].value
        assert [m["name"] for m in square["members"]] == ["area", "scale_shape"]
        assert "`helper`" in facts["arch.members.pkg.paths"].markdown

    def test_unreadable_definition_is_kept_on_its_owner(self, facts: dict[str, Fact]) -> None:
        star = facts["arch.members.pkg.star"]
        assert [u["name"] for u in star.value["unreadable"]] == ["star"]
        assert "couldn't read" in star.markdown
        assert facts["arch.coverage.unreadable"].value == ["pkg.star.star"]

    def test_imports_split_runtime_type_only_unresolved(self, facts: dict[str, Fact]) -> None:
        shapes = facts["arch.imports.pkg.shapes"].value
        assert shapes["measured"] is True
        assert shapes["type_only"] == ["pkg.util"]
        assert "pkg.util" not in shapes["runtime"]
        assert facts["arch.imports.pkg.cfg"].value["unresolved"] == ["missing_dependency"]
        assert "TYPE_CHECKING" in facts["arch.imports.pkg.shapes"].markdown

    def test_imported_by_is_the_set_of_packages(self, facts: dict[str, Fact]) -> None:
        assert facts["arch.imported_by.pkg.paths"].value == ["pkg"]
        assert facts["arch.imported_by.pkg.settings"].value == []
        assert facts["arch.imported_by.pkg.settings"].markdown == "No module imports it."

    def test_coverage_gaps_fact(self, facts: dict[str, Fact]) -> None:
        gaps = facts["arch.coverage.gaps"].value
        assert list(gaps) == list(kind.GAP_CATEGORIES)
        assert gaps["unmapped"] == ["bad-dir/x.py"]
        assert "bad-dir/x.py" in facts["arch.coverage.gaps"].markdown

    def test_cross_facts_hold_only_pyeye_backed_labels(self, facts: dict[str, Fact]) -> None:
        labels = {
            (p["a"], p["b"], p["label"])
            for fid, f in facts.items()
            if fid.startswith("arch.cross.")
            for p in f.value["labelled"]
        }
        assert ("pkg.shapes.Base.area", "pkg.shapes.Square.area", "override") in labels
        assert (
            "pkg.shapes.Circle.resize_shape",
            "pkg.shapes.Square.scale_shape",
            "sibling",
        ) in labels
        assert all(label != "possible duplicate (unverified)" for *_, label in labels)
        # The unverified pair (load_config / read_config) is no fact anywhere.
        dumped = json.dumps({fid: f.value for fid, f in facts.items()})
        assert 'read_config", "label' not in dumped

    def test_delegation_across_areas(self, tmp_path: Path) -> None:
        (tmp_path / "app").mkdir()
        (tmp_path / "app/__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "app/store.py").write_text(
            'def load_records(path: str) -> list:\n    """Load the records."""\n    return []\n',
            encoding="utf-8",
        )
        (tmp_path / "app/cli.py").write_text(
            "from app.store import load_records\n\n\n"
            'def load_records_command(path: str) -> list:\n    """Load the records."""\n'
            "    return load_records(path)\n",
            encoding="utf-8",
        )
        # Unrelated definitions, so the pair's shared words are rare (IDF > 0).
        (tmp_path / "app/misc.py").write_text(
            "".join(
                f"def {n}(): ...\n"
                for n in ("render_html", "parse_args", "open_socket", "sort_items")
            ),
            encoding="utf-8",
        )
        opts = options.parse({"areas": {"storage": ["app.store"], "ui": ["app.cli"]}})
        built = _facts(kind.extract(tmp_path, opts))
        pair = {"a": "app.cli.load_records_command", "b": "app.store.load_records"}
        expected = {**pair, "label": "delegates"}
        assert built["arch.cross.storage"].value["labelled"] == [expected]
        assert built["arch.cross.ui"].value["labelled"] == [expected]
        assert "delegates" in built["arch.cross.ui"].markdown

    def test_curated_pairs_are_labelled_and_unknown_ones_are_gaps(self, project: Path) -> None:
        opts = options.parse(
            {
                "pairs": [
                    ["pkg.paths.helper", "pkg.util.normalise_path"],
                    ["pkg.cfg.load_config", "pkg.nowhere.gone"],
                ],
                "candidates_page": "docs/c.md",
            }
        )
        built = kind.extract(project, opts)
        found = _facts(built)
        delegates = {"a": "pkg.paths.helper", "b": "pkg.util.normalise_path", "label": "delegates"}
        assert delegates in found["arch.cross.pkg.paths"].value["labelled"]
        assert delegates in found["arch.cross.pkg.util"].value["labelled"]
        assert found["arch.coverage.gaps"].value["unknown_pairs"] == [
            "pkg.cfg.load_config ~ pkg.nowhere.gone (not in the dump: pkg.nowhere.gone)"
        ]
        (page,) = [i for i in built if isinstance(i, Advisory)]
        assert (
            "| curated | `pkg.paths.helper` | `pkg.util.normalise_path` | delegates |" in page.text
        )

    def test_a_curated_pair_that_is_also_scored_is_labelled_once(self) -> None:
        scored = [candidates_mod.Candidate(1.0, "a.x", "a", "b.y", "b")]
        assert kind.to_label(scored, [("b.y", "a.x"), ("a.x", "c.z")]) == [
            ("a.x", "b.y"),
            ("a.x", "c.z"),
        ]

    def test_deprecation_is_a_flag_on_its_area(self, facts: dict[str, Fact]) -> None:
        assert facts["arch.cross.pkg.old"].value["deprecated"] == ["pkg.old.old_helper"]
        assert "pkg.old.maybe_old" not in facts["arch.cross.pkg.old"].value["deprecated"]
        assert "Deprecated" in facts["arch.cross.pkg.old"].markdown

    def test_every_area_has_a_cross_fact(self, facts: dict[str, Fact]) -> None:
        modules = {fid.removeprefix("arch.imports.") for fid in facts if ".imports." in fid}
        areas = {fid.removeprefix("arch.cross.") for fid in facts if ".cross." in fid}
        assert areas == modules
        assert "No candidate pair" in facts["arch.cross.pkg.hooks"].markdown

    def test_advisory_page_lists_unverified_candidates(self, extracted: list[Any]) -> None:
        pages = [i for i in extracted if isinstance(i, Advisory)]
        assert [p.path for p in pages] == ["docs/candidates.md"]
        assert "pkg.settings.read_config" in pages[0].text
        assert "possible duplicate (unverified)" in pages[0].text
        assert pages[0].text.startswith(
            "# Candidate pairs: arch (judgment)\n\n**Judgment, not fact.**"
        )
        for line in kind.filters(options.parse({"min_score": 0.0, "within_areas": True})):
            assert f"- {line}\n" in pages[0].text
        assert "score at least 0:" in pages[0].text

    def test_page_flags_a_pair_whose_callees_are_unmeasured(self) -> None:
        found = _empty(modules=("a", "b"))
        defs = tuple(
            dump.Definition(h, "function", h.split(".")[0], h.split(".")[0], None, "")
            for h in ("a.f", "b.g")
        )
        found = kind.Collected(
            dump.Dump(found.dump.modules, defs),
            found.coverage,
            found.areas,
            (),
            (relations_mod.Relation("a.f", "b.g", relations_mod.UNVERIFIED, (), (), False),),
            curated=(("a.f", "b.g"),),
        )
        opts = options.parse({"candidates_page": "c.md"})
        (page,) = [i for i in kind.build(opts, found) if isinstance(i, Advisory)]
        assert (
            "| curated | `a.f` | `b.g` | possible duplicate (unverified) | callees unmeasured |"
            in (page.text)
        )

    def test_no_page_without_the_option(self) -> None:
        built = kind.build(options.parse({}), _empty())
        assert not [i for i in built if isinstance(i, Advisory)]

    def test_unidentifiable_handles_are_a_gap_not_a_crash(self) -> None:
        found = _empty(modules=("pkg.ok", "pkg.naïve"))
        built = _facts(kind.build(options.parse({}), found))
        assert built["arch.coverage.gaps"].value["unidentifiable"] == ["pkg.naïve"]
        assert "arch.imports.pkg.ok" in built

    def test_unmeasured_imports_and_importers(self) -> None:
        module = _module("pkg.x", measured=False, imported_by=None)
        assert kind.imports_value(module) == {"measured": False}
        assert kind.imports_markdown(module) == "pyeye couldn't read its imports."
        assert kind.importing_packages(module) is None
        assert "couldn't measure" in kind.imported_by_markdown(None)

    def test_prefix_is_honoured(self) -> None:
        built = _facts(kind.build(options.parse({"prefix": "layout"}), _empty(modules=("m",))))
        assert all(fid.startswith("layout.") for fid in built)

    def test_strict_source_refusals_are_reported(self, project: Path) -> None:
        opts = options.parse({"strict_source": True, "include": ["pkg/paths.py"]})
        built = _facts(kind.extract(project, opts))
        assert isinstance(built["arch.coverage.refused"].value, list)


def _module(handle: str, *, measured: bool = True, imported_by: int | None = 0) -> dump.Module:
    return dump.Module(handle, f"{handle}.py", "", imported_by, (), (), (), (), measured)


def _empty(modules: tuple[str, ...] = ()) -> kind.Collected:
    found = dump.Dump(modules=tuple(_module(m) for m in modules), definitions=())
    cov = coverage.Coverage(0, 0, (), (), (), (), (), ())
    return kind.Collected(found, cov, {m: m for m in modules}, (), ())


class TestRules:
    def test_layering_follows_the_prefix(self) -> None:
        rule = kind.layering_rule("layout")
        facts = {
            "layout.imports.a.x": Fact(
                "layout.imports.a.x",
                {"measured": True, "runtime": ["b.y"], "type_only": [], "unresolved": []},
                "",
            )
        }
        page = rules.Page("p.md", "", "CHECK no-import: a -> b\nCHECK no-import: b -> a\n", "prose")
        findings = rule.scan(page, facts)
        assert [f.line for f in findings] == [1, 2]
        assert "is broken: a.x imports b.y" in findings[0].message
        assert "can't be verified" in findings[1].message

    def test_layering_ignores_type_only_and_needs_measured_imports(self) -> None:
        facts = {
            "arch.imports.a": Fact(
                "arch.imports.a",
                {"measured": True, "runtime": [], "type_only": ["b"], "unresolved": []},
                "",
            ),
            "arch.imports.a.z": Fact("arch.imports.a.z", {"measured": False}, ""),
        }
        page = rules.Page("p.md", "", "CHECK no-import: a -> b\n", "prose")
        (finding,) = kind.layering_rule("arch").scan(page, facts)
        assert "couldn't read the imports of a.z" in finding.message

    def test_a_page_without_checks_is_quiet(self) -> None:
        page = rules.Page("p.md", "", "no checks here", "prose")
        assert kind.layering_rule("arch").scan(page, {}) == []

    def test_coverage_audit_is_one_problem_per_gap(self) -> None:
        gaps: dict[str, list[str]] = {c: [] for c in kind.GAP_CATEGORIES}
        gaps |= {"missing": ["m.f"], "skipped": ["m/s.py"]}
        facts = {"arch.coverage.gaps": Fact("arch.coverage.gaps", gaps, "")}
        rule = kind.coverage_rule("arch")
        assert rule.audit is not None
        assert rule.audit(facts) == [
            "missing in the arch dump: m.f",
            "skipped in the arch dump: m/s.py",
        ]
        assert rule.scan(rules.Page("p", "", "", "prose"), facts) == []


class TestEngine:
    """The engine contracts #1092 adds: Rule.audit, extractor rules, advisory pages."""

    def test_rules_run_calls_audit_once(self, tmp_path: Path) -> None:
        calls: list[int] = []

        def audit(_facts: rules.Facts) -> list[str]:
            calls.append(1)
            return ["one", "two"]

        rule = rules.Rule("audited", frozenset(), False, lambda _p, _f: [], audit=audit)
        problems = rules.run(tmp_path, {}, docs=(), rules=[rule], descriptions={}, strings=())
        assert problems == ["audited: one", "audited: two"]
        assert calls == [1]

    def test_audit_gets_only_a_read_only_view_of_the_facts(self, tmp_path: Path) -> None:
        seen: list[Any] = []

        def audit(*args: Any, **kwargs: Any) -> list[str]:
            seen.append((args, kwargs))
            with pytest.raises(TypeError):
                args[0]["x.new"] = Fact("x.new", 1, "1")  # read-only
            return []

        facts = {"x.a": Fact("x.a", 1, "1")}
        rule = rules.Rule("audited", frozenset(), False, lambda _p, _f: [], audit=audit)
        rules.run(tmp_path, facts, docs=(), rules=[rule], descriptions={}, strings=())
        ((args, kwargs),) = seen
        assert kwargs == {} and len(args) == 1  # the facts, and no root or path
        assert dict(args[0]) == facts
        assert "x.new" not in facts

    def test_audit_is_skipped_when_its_facts_are_absent(self, tmp_path: Path) -> None:
        rule = kind.coverage_rule("arch")
        assert rules.run(tmp_path, {}, docs=(), rules=[rule], descriptions={}, strings=()) == []
        assert rules.skipped([rule], {}) == [
            "skipped rule structure-coverage: needs arch.coverage.gaps"
        ]

    def test_build_separates_advisory_pages(self, tmp_path: Path) -> None:
        extractor = registry.Extractor(
            "x", ("x",), lambda _root: [Fact("x.a", 1, "1"), Advisory("out.md", "hello")]
        )
        advisory: dict[str, str] = {}
        assert list(registry.build(tmp_path, [extractor], advisory)) == ["x.a"]
        assert advisory == {"out.md": "hello"}
        assert list(registry.build(tmp_path, [extractor])) == ["x.a"]  # dropped

    def test_build_refuses_a_page_twice(self, tmp_path: Path) -> None:
        extractor = registry.Extractor(
            "x", ("x",), lambda _root: [Advisory("o.md", "a"), Advisory("o.md", "b")]
        )
        with pytest.raises(ValueError, match="produced twice"):
            registry.build(tmp_path, [extractor])


def _advisory_setup(tmp_path: Path, page: str) -> config.Setup:
    extractor = registry.Extractor(
        "x", ("x",), lambda _root: [Fact("x.a", 1, "1"), Advisory(page, "advice\n")]
    )
    doc = DocEntry("README.md", "human", "prose")
    (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")
    return config.Setup(extractors=(extractor,), docs=(doc,), rules=(), pages={}, changelog=None)


class TestAdvisoryPages:
    def test_generate_writes_it_and_check_never_compares_it(self, tmp_path: Path) -> None:
        setup = _advisory_setup(tmp_path, "docs/advice.md")
        assert cli.generate(tmp_path, setup) == 0
        page = tmp_path / "docs/advice.md"
        assert page.read_text(encoding="utf-8") == "advice\n"
        page.write_text("edited by hand\n", encoding="utf-8")
        assert cli.check(tmp_path, setup) == 0  # never compared

    @pytest.mark.parametrize("path", ["README.md", "docs/facts/uncovered.json"])
    def test_it_may_not_shadow_a_checked_output(self, tmp_path: Path, path: str) -> None:
        setup = _advisory_setup(tmp_path, path)
        result = cli.plan(tmp_path, setup=setup)
        assert f"{path}: an advisory page can't also be a checked output" in result.problems


class TestRulesThroughCheck:
    def test_check_fails_on_a_broken_layering_line_and_a_gap(self, project: Path) -> None:
        doc = DocEntry("ARCH.md", "human", "prose")
        (project / "ARCH.md").write_text(
            "# Arch\n\nCHECK no-import: pkg.util -> pkg.paths\n", encoding="utf-8"
        )
        write_config(
            project,
            [doc],
            changelog=None,
            extractors=[{"kind": "structure", "prefix": "layout"}],
            reference_only=["layout"],
        )
        result = cli.plan(project, setup=config.load(project))
        assert any(
            p.startswith("ARCH.md:3: layering: CHECK no-import: pkg.util -> pkg.paths is broken")
            for p in result.problems
        )
        assert "structure-coverage: unmapped in the layout dump: bad-dir/x.py" in result.problems
        assert not [n for n in result.notes if "layering" in n or "structure-coverage" in n]
