"""The ``architecture-handles`` rule: every handle an architecture page names resolves (#1176).

Ruling B on #1173 (maintainer, 2026-11-23): a removed or renamed helper must not
leave a stale handle in an area doc or top map. The rule reads the ``structure``
dump's members facts, never the code (C19), and scans only the registered pages
matching the kind's ``architecture_pages`` globs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pyeye.docs_facts import cli, config, rules
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.extractors import structure as kind
from pyeye.docs_facts.facts import Fact
from pyeye.docs_facts.structure import handles, options
from tests.utils.docs_facts_config import write_config
from tests.utils.structure import write_project


def _members(owner: str, *names: str, unreadable: tuple[str, ...] = ()) -> Fact:
    value = {
        "members": [
            {"name": n, "kind": "function", "signature": None, "summary": ""} for n in names
        ],
        "unreadable": [{"name": n, "kind": "function", "reason": "x"} for n in unreadable],
    }
    return Fact(f"arch.members.{owner}", value, "")


FACTS = {
    f.id: f
    for f in (
        _members("pkg", "paths", "shapes"),
        _members("pkg.paths", "helper"),
        _members("pkg.shapes", "Square"),
        _members("pkg.shapes.Square", "area", unreadable=("odd",)),
        _members("tool.cli", "main"),
    )
}


def _scan(prose: str, name: str = "docs/architecture/area.md") -> list[rules.Finding]:
    rule = kind.handles_rule("arch", options.ARCHITECTURE_PAGES)
    return rule.scan(rules.Page(name, prose, prose, "prose"), FACTS)


class TestWhatResolves:
    def test_owners_members_and_unreadable_members_resolve(self) -> None:
        known = handles.known("arch", FACTS)
        assert {"pkg", "pkg.paths", "pkg.paths.helper", "pkg.shapes.Square.area"} <= known
        assert "pkg.shapes.Square.odd" in known  # exists, pyeye just couldn't read it

    def test_the_roots_are_the_dumps_top_level_names(self) -> None:
        assert handles.roots(handles.known("arch", FACTS)) == frozenset({"pkg", "tool"})

    def test_only_this_prefixs_members_count(self) -> None:
        other = {"layout.members.pkg": _members("pkg", "x")}
        assert handles.known("arch", other) == frozenset()


class TestFindings:
    def test_existing_handles_pass_in_code_spans_and_plain_text(self) -> None:
        prose = (
            "Use `pkg.paths.helper` to normalise.\n"
            "Shapes live in pkg.shapes, e.g. pkg.shapes.Square.area().\n"
            "The CLI is `tool.cli.main`.\n"
        )
        assert _scan(prose) == []

    def test_a_removed_handle_fails_with_its_line(self) -> None:
        (finding,) = _scan("# Area\n\nCall `pkg.paths.gone` here.\n")
        assert finding.line == 3
        assert finding.message == "`pkg.paths.gone` doesn't resolve in the arch dump or with pyeye"

    def test_a_renamed_handle_fails_in_plain_text_too(self) -> None:
        (finding,) = _scan("Squares: pkg.shapes.Rectangle.area.\n")
        assert (
            finding.message
            == "`pkg.shapes.Rectangle.area` doesn't resolve in the arch dump or with pyeye"
        )

    def test_each_occurrence_is_reported(self) -> None:
        assert [f.line for f in _scan("`pkg.nope`\n\nand pkg.nope\n")] == [1, 3]

    @pytest.mark.parametrize(
        "prose",
        [
            "See src/pkg/paths.py and docs/pkg.notes.md.",  # paths: preceded by / or .
            "https://example.com/pkg.whatever",  # a URL
            "my-pkg.thing and xpkg.thing",  # part of another word
            "The pkg package, and pkg.",  # no dotted name
            "Other roots like os.path.join are not this dump's",
        ],
    )
    def test_what_isnt_a_handle_is_ignored(self, prose: str) -> None:
        assert _scan(prose) == []

    def test_fact_block_content_isnt_scanned(self) -> None:
        text = "<!-- fact:begin arch.members.pkg -->`pkg.gone`<!-- fact:end -->\n"
        rule = kind.handles_rule("arch", options.ARCHITECTURE_PAGES)
        page = rules.Page("docs/architecture/a.md", text, rules.prose_text(text), "prose")
        assert rule.scan(page, FACTS) == []

    def test_only_architecture_pages_are_scanned(self) -> None:
        assert _scan("`pkg.gone`", name="docs/guide.md") == []
        rule = kind.handles_rule("arch", ("design/*.md",))
        page = rules.Page("design/map.md", "`pkg.gone`", "`pkg.gone`", "prose")
        assert len(rule.scan(page, FACTS)) == 1

    def test_no_members_facts_means_nothing_to_check(self) -> None:
        rule = kind.handles_rule("arch", options.ARCHITECTURE_PAGES)
        page = rules.Page("docs/architecture/a.md", "`pkg.gone`", "`pkg.gone`", "prose")
        assert rule.scan(page, {}) == []


class TestPyeyesResolver:
    """A handle the dump doesn't list goes through pyeye before it's called stale (#1176)."""

    def test_a_dump_miss_that_pyeye_resolves_passes(self) -> None:
        asked: list[str] = []

        def resolves(handle: str) -> bool:
            asked.append(handle)
            return handle == "pkg.Helper"  # e.g. a re-export of pkg.paths.helper

        defined = handles.known("arch", FACTS)
        text = "`pkg.Helper` and `pkg.gone`, `pkg.gone` again, `pkg.paths.helper`"
        assert handles.unresolved(text, defined, resolves) == [(1, "pkg.gone"), (1, "pkg.gone")]
        assert asked == ["pkg.Helper", "pkg.gone"]  # once per distinct miss, never a dump hit

    def test_no_miss_never_asks(self) -> None:
        def resolves(handle: str) -> bool:
            raise AssertionError(f"asked about {handle}")

        assert (
            handles.unresolved("`pkg.paths.helper`", handles.known("arch", FACTS), resolves) == []
        )

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            ({"found": True, "handle": "pkg.paths.helper"}, True),
            ({"found": True, "ambiguous": True, "candidates": []}, True),
            ({"found": False, "reason": "unresolved"}, False),
            ({}, False),
        ],
    )
    def test_what_counts_as_found(self, result: dict[str, object], expected: bool) -> None:
        assert handles.found(result) is expected


class TestTheRule:
    def test_it_follows_the_prefix_and_needs_the_members_facts(self) -> None:
        rule = kind.handles_rule("layout", options.ARCHITECTURE_PAGES)
        assert rule.id == rules.ARCHITECTURE_HANDLES == "architecture-handles"
        assert rule.requires == frozenset({"layout.members."})
        assert rules.ARCHITECTURE_HANDLES in rules.RULE_IDS

    def test_the_kind_brings_it(self) -> None:
        extractor = kind.structure({"prefix": "layout"})
        assert rules.ARCHITECTURE_HANDLES in [r.id for r in extractor.rules]

    def test_architecture_pages_is_an_option(self) -> None:
        assert options.parse({}).architecture_pages == ("docs/architecture/**",)
        assert options.parse({"architecture_pages": ["a/*.md"]}).architecture_pages == ("a/*.md",)
        with pytest.raises(ValueError, match="architecture_pages"):
            options.parse({"architecture_pages": "a/*.md"})


class TestThroughCheck:
    def test_check_fails_on_a_stale_handle_and_passes_a_live_one(self, tmp_path: Path) -> None:
        project = write_project(tmp_path / "repo")
        page = project / "docs" / "architecture" / "paths.md"
        page.parent.mkdir(parents=True)
        page.write_text(
            "# Paths\n\nUse `pkg.paths.helper`.\nNot pkg.paths.renamed_helper.\n", encoding="utf-8"
        )
        write_config(
            project,
            [DocEntry("docs/architecture/paths.md", "both", "prose")],
            changelog=None,
            extractors=[{"kind": "structure", "exclude": ["bad-dir/*"]}],
            reference_only=["arch"],
        )
        result = cli.plan(project, setup=config.load(project))
        found = [p for p in result.problems if ": architecture-handles: `" in p]
        assert found == [
            "docs/architecture/paths.md:4: architecture-handles: "
            "`pkg.paths.renamed_helper` doesn't resolve in the arch dump or with pyeye"
        ]

    def test_a_handle_outside_the_dump_resolves_through_pyeye(self, tmp_path: Path) -> None:
        """``pkg.cfg`` is left out of the dump, but pyeye still finds its functions."""
        project = write_project(tmp_path / "repo")
        page = project / "docs" / "architecture" / "cfg.md"
        page.parent.mkdir(parents=True)
        page.write_text(
            "# Config\n\nLoad with `pkg.cfg.load_config`.\nNot `pkg.cfg.load_settings`.\n",
            encoding="utf-8",
        )
        write_config(
            project,
            [DocEntry("docs/architecture/cfg.md", "both", "prose")],
            changelog=None,
            extractors=[{"kind": "structure", "exclude": ["bad-dir/*", "pkg/cfg.py"]}],
            reference_only=["arch"],
        )
        result = cli.plan(project, setup=config.load(project))
        assert [p for p in result.problems if ": architecture-handles: `" in p] == [
            "docs/architecture/cfg.md:4: architecture-handles: "
            "`pkg.cfg.load_settings` doesn't resolve in the arch dump or with pyeye"
        ]

    def test_without_the_structure_kind_it_doesnt_run(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
        (tmp_path / "docs" / "architecture").mkdir(parents=True)
        (tmp_path / "docs" / "architecture" / "a.md").write_text("`pkg.gone`\n", encoding="utf-8")
        write_config(
            tmp_path,
            [DocEntry("docs/architecture/a.md", "both", "prose")],
            changelog=None,
            facts=[
                {"id": "demo.x", "from": "toml", "file": "pyproject.toml", "key": "project.name"}
            ],
        )
        result = cli.plan(tmp_path, setup=config.load(tmp_path))
        assert not [p for p in result.problems if "architecture-handles" in p]
