"""The architecture review engine on real ``arch.*`` facts (#1178, #1132 R1).

A fixture repository (``tests/utils/structure``'s project) gets a docs-facts
config with the ``structure`` kind and two areas, its real facts written to the
snapshot as ``generate`` writes them, ``CHECK`` lines on an architecture page,
decision entries and a convention document. Hand-written snapshots cover the
edge cases a real run can't reach (an unmeasured module, no facts at all).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from pyeye.docs_facts import architecture, cli, config, review
from pyeye.docs_facts.docs import DocEntry
from pyeye.docs_facts.extractors import structure as kind
from pyeye.docs_facts.facts import Fact
from tests.utils.docs_facts_config import write_config
from tests.utils.structure import write_project

AREAS = {"core": ["pkg.paths*", "pkg.util*"], "shapes": ["pkg.shapes*", "pkg.hooks*"]}

ARCH_PAGE = """\
# Architecture

## Layers

CHECK no-import: pkg.util -> pkg.paths
CHECK no-import: pkg.paths -> pkg.util
CHECK no-import: pkg.shapes -> pkg.util
CHECK no-import: pkg.cfg -> missing_dependency
"""

AGENTS = (
    "# Agents\n\n## Logging\n\nUse the module logger.\n\n## Docstrings\n\nEvery module has one.\n"
)


def _entry(name: str, status: str, applies_to: str) -> tuple[str, str]:
    title = name.removesuffix(".md")
    text = (
        "---\n"
        f'date: "2026-01-01"\ntitle: "{title}"\nissues: []\nanchors: []\n'
        f'status: "{status}"\namends: []\nsupersedes: []\namended_by: []\nsuperseded_by: []\n'
        "---\n\n"
        f"## 2026-01-01 — {title}\n\n"
        "**Friction:** x.\n**Decision:** y.\n**Anchor:** z.\n"
        f"**Applies-to:** {applies_to}\n**Verify:** unverifiable — a test fixture.\n"
    )
    return name, text


DECISIONS = [
    _entry(
        "2026-01-01-1-util-delegates.md", "active", "`pkg.util.normalise_path` and `pkg/util.py`"
    ),
    _entry("2026-01-01-2-old-paths.md", "superseded", "`pkg.paths.helper`"),
    _entry("2026-01-01-3-shapes.md", "active", "`pkg.shapes.Base` and `pkg.gone.thing`"),
    _entry("2026-01-01-4-policy.md", "active", "none (policy decision: release classification)"),
    _entry(
        "2026-01-01-5-short.md", "active", "`util.normalise_path`, `os.path.join` and `pkg.util`"
    ),
]


def _repo(root: Path, *, structure: bool = True) -> Path:
    write_project(root)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "architecture.md").write_text(ARCH_PAGE, encoding="utf-8")
    (root / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
    entries = root / "docs" / "decisions" / "entries"
    entries.mkdir(parents=True, exist_ok=True)
    for name, text in DECISIONS:
        (entries / name).write_text(text, encoding="utf-8")
    extractors = [{"kind": "structure", "include": ["pkg/*"], "areas": AREAS}] if structure else []
    write_config(
        root,
        [DocEntry("docs/architecture.md", "human", "prose")],
        changelog=None,
        extractors=extractors,
    )
    return root


def _write_snapshot(root: Path, values: dict[str, Any]) -> None:
    path = root / "docs" / "facts" / "facts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"facts": values, "views": {}}), encoding="utf-8")


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture repository, with its real facts in the snapshot."""
    root = _repo(tmp_path_factory.mktemp("arch_engine"))
    opts = architecture.structure_options(root)
    assert opts is not None
    facts = {i.id: i for i in kind.extract(root, opts) if isinstance(i, Fact)}
    setup = config.load(root)
    for rel, text in cli.snapshot_texts(facts, setup.paths).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def core(repo: Path) -> dict[str, Any]:
    return architecture.plan(repo, "core", conventions=["AGENTS.md"])


@pytest.fixture(scope="module")
def shapes(repo: Path) -> dict[str, Any]:
    return architecture.plan(repo, "shapes")


def _by(packet: dict[str, Any], category: str) -> list[dict[str, Any]]:
    return [f for f in packet["findings"] if f["category"] == category]


class TestArea:
    def test_a_configured_area_uses_its_patterns(self, core: dict[str, Any]) -> None:
        assert core["area"] == {"id": "core", "patterns": AREAS["core"], "configured": True}
        assert core["modules"] == ["pkg.paths", "pkg.util"]

    def test_a_module_prefix_is_an_implicit_area(self, repo: Path) -> None:
        packet = architecture.plan(repo, "pkg.cfg")

        assert packet["area"] == {
            "id": "pkg.cfg",
            "patterns": ["pkg.cfg", "pkg.cfg.*"],
            "configured": False,
        }
        assert packet["modules"] == ["pkg.cfg"]

    def test_an_unassigned_module_is_a_coverage_gap(self, core: dict[str, Any]) -> None:
        assert {"pkg", "pkg.cfg", "pkg.old", "pkg.settings"} <= set(core["unassigned"])
        assert "pkg.util" not in core["unassigned"]

    def test_the_area_holds_definitions_inside_its_modules(self) -> None:
        area = architecture.Area("core", ("pkg.util*",), True)

        assert area.holds("pkg.util.normalise_path")
        assert not area.holds("pkg.paths.helper")

    def test_the_packet_carries_only_the_areas_facts(self, core: dict[str, Any]) -> None:
        assert "arch.imports.pkg.util" in core["facts"]
        assert "arch.members.pkg.util" in core["facts"]
        assert not any("pkg.shapes" in fid for fid in core["facts"])


class TestCurationAsData:
    """#1175: areas and pairs may be data files; unassigned modules and pairs are recorded."""

    def test_areas_from_a_data_file(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        (root / "areas.toml").write_text(
            '[areas]\ncore = ["pkg.paths*", "pkg.util*"]\n', encoding="utf-8"
        )
        write_config(
            root,
            [DocEntry("docs/architecture.md", "human", "prose")],
            changelog=None,
            extractors=[{"kind": "structure", "include": ["pkg/*"], "areas": "areas.toml"}],
        )
        imports = {"runtime": [], "type_only": [], "unresolved": [], "measured": True}
        _write_snapshot(root, {"arch.imports.pkg.util": imports})

        packet = architecture.plan(root, "core", resolver=_NoSites())

        assert packet["area"] == {"id": "core", "patterns": AREAS["core"], "configured": True}
        assert packet["modules"] == ["pkg.util"]

    def test_unassigned_is_the_recorded_gap(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        imports = {"runtime": [], "type_only": [], "unresolved": [], "measured": True}
        _write_snapshot(
            root,
            {
                "arch.imports.pkg.util": imports,
                "arch.coverage.gaps": {"unassigned": ["pkg.stray"], "missing": []},
            },
        )

        packet = architecture.plan(root, "core", resolver=_NoSites())

        assert packet["unassigned"] == ["pkg.stray"]

    def test_the_areas_curated_pairs_are_in_its_facts(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        imports = {"runtime": [], "type_only": [], "unresolved": [], "measured": True}
        pairs = [{"a": "pkg.util.normalise_path", "b": "pkg.paths.helper", "label": "delegates"}]
        _write_snapshot(
            root,
            {"arch.imports.pkg.util": imports, "arch.pairs.core": pairs, "arch.pairs.shapes": []},
        )

        packet = architecture.plan(root, "core", resolver=_NoSites())

        assert packet["facts"]["arch.pairs.core"] == pairs
        assert "arch.pairs.shapes" not in packet["facts"]


class TestTheRulePass:
    def test_a_broken_check_is_a_deviation_from_its_rule(self, core: dict[str, Any]) -> None:
        [deviation] = _by(core, "deviation")

        assert deviation["anchor"] == {"kind": "rule", "id": "no-import: pkg.util -> pkg.paths"}
        assert deviation["evidence"] == ["pkg.util"]
        assert "pkg.util imports pkg.paths.helper" in deviation["problem"]
        assert review.finding_problems(deviation) == []

    def test_a_holding_check_is_an_adherence(self, core: dict[str, Any]) -> None:
        [adherence] = _by(core, "adherence")

        assert adherence["anchor"]["id"] == "no-import: pkg.paths -> pkg.util"
        assert review.finding_problems(adherence) == []

    def test_a_type_only_import_doesnt_break_a_check(self, shapes: dict[str, Any]) -> None:
        [adherence] = _by(shapes, "adherence")
        [rule] = shapes["rules"]

        assert adherence["anchor"]["id"] == "no-import: pkg.shapes -> pkg.util"
        assert rule["ignored"] == [["pkg.shapes", "pkg.util"]]

    def test_only_the_checks_governing_the_area_are_in_scope(self, core: dict[str, Any]) -> None:
        assert [r["id"] for r in core["rules"]] == [
            "no-import: pkg.util -> pkg.paths",
            "no-import: pkg.paths -> pkg.util",
        ]
        assert core["rules"][0]["page"] == "docs/architecture.md"
        assert core["rules"][0]["line"] == 5

    def test_an_unresolved_import_breaks_a_check(self, repo: Path) -> None:
        [deviation] = _by(architecture.plan(repo, "pkg.cfg"), "deviation")

        assert deviation["anchor"]["id"] == "no-import: pkg.cfg -> missing_dependency"

    def test_an_unmeasured_module_leaves_its_rule_unverified(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        imports = {"runtime": [], "type_only": [], "unresolved": [], "measured": False}
        _write_snapshot(root, {"arch.imports.pkg.util": imports})

        packet = architecture.plan(root, "core", resolver=_NoSites())

        assert packet["findings"] == []
        assert packet["unverified_rules"][0]["unmeasured"] == ["pkg.util"]
        assert "couldn't read the imports" in packet["unverified_rules"][0]["reason"]


class _NoSites:
    def canonical(self, identifier: str) -> tuple[str | None, str | None]:
        return None, f"not asked: {identifier}"


class TestTheDecisionPass:
    def test_a_decision_whose_site_is_in_the_area_is_a_candidate(
        self, core: dict[str, Any]
    ) -> None:
        [candidate] = [
            d for d in core["decisions"] if d["decision"] == "2026-01-01-1-util-delegates.md"
        ]

        assert candidate["sites"] == [
            {"text": "pkg.util.normalise_path", "handle": "pkg.util.normalise_path"},
            {"text": "pkg/util.py", "handle": "pkg.util"},
        ]

    def test_a_superseded_decision_governs_nothing(self, repo: Path) -> None:
        packet = architecture.plan(repo, "core")

        assert "2026-01-01-2-old-paths.md" not in {d["decision"] for d in packet["decisions"]}

    def test_each_area_gets_its_own_candidates(self, shapes: dict[str, Any]) -> None:
        assert [d["decision"] for d in shapes["decisions"]] == ["2026-01-01-3-shapes.md"]

    def test_an_unresolved_site_is_reported_never_silently_unmatched(
        self, core: dict[str, Any]
    ) -> None:
        assert {
            "decision": "2026-01-01-3-shapes.md",
            "site": "pkg.gone.thing",
            "reason": "unresolved",
        } in core["unresolved_sites"]

    def test_a_short_form_is_listed_apart_never_as_stale(self, core: dict[str, Any]) -> None:
        """#1188: a site not rooted at a project top-level name is a short form, never resolved."""
        short = {"decision": "2026-01-01-5-short.md", "site": "util.normalise_path"}

        assert short in core["short_form_sites"]
        assert all(s["site"] != "util.normalise_path" for s in core["unresolved_sites"])

    def test_an_external_site_is_listed_apart(self, core: dict[str, Any]) -> None:
        """A stdlib or environment name can't be in an area: it is listed, never 'not here'."""
        assert {
            "decision": "2026-01-01-5-short.md",
            "site": "os.path.join",
            "reason": "external",
        } in core["external_sites"]
        assert all(s["site"] != "os.path.join" for s in core["unresolved_sites"])

    def test_only_stale_project_sites_are_unresolved(self, core: dict[str, Any]) -> None:
        assert [s["site"] for s in core["unresolved_sites"]] == ["pkg.gone.thing"]

    def test_a_decision_with_a_short_form_still_matches_on_its_handles(
        self, core: dict[str, Any]
    ) -> None:
        assert "2026-01-01-5-short.md" in {d["decision"] for d in core["decisions"]}

    def test_a_none_applies_to_has_no_sites(self, core: dict[str, Any]) -> None:
        assert "2026-01-01-4-policy.md" not in {s["decision"] for s in core["unresolved_sites"]}


class TestNoRecordedArchitecture:
    def test_no_structure_kind_says_so(self, tmp_path: Path) -> None:
        packet = architecture.plan(_repo(tmp_path, structure=False), "core")

        assert packet["findings"] == []
        assert packet["notes"] == [
            f"{architecture.NO_ARCHITECTURE} (no structure kind is configured)"
        ]

    def test_an_empty_snapshot_says_so(self, tmp_path: Path) -> None:
        root = _repo(tmp_path)
        _write_snapshot(root, {})

        packet = architecture.plan(root, "core", resolver=_NoSites())

        assert packet["notes"] == [
            f"{architecture.NO_ARCHITECTURE} (the snapshot records no arch.* facts)"
        ]

    def test_an_area_with_no_recorded_module_says_so(self, repo: Path) -> None:
        packet = architecture.plan(repo, "nowhere")

        assert packet["modules"] == []
        assert "no recorded module is in area 'nowhere'" in packet["notes"][0]

    def test_no_config_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(config.ConfigError):
            architecture.plan(tmp_path, "core")


def _reviewer(category: str, **fields: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "review": "architecture",
        "area": "core",
        "category": category,
        "problem": "what the reviewer found",
        "anchor": {"kind": "decision", "id": "2026-01-01-1-util-delegates.md"},
        "evidence": ["pkg.util.normalise_path"],
    }
    if category == "deviation":
        finding["recommendation"] = "follow the decision"
    if category in ("decision_needed", "ambiguity"):
        finding["anchor"] = {"kind": "fact", "id": "arch.members.pkg.util"}
        finding["question"] = "which?"
    if category == "decision_needed":
        finding["proposal"] = "record it"
    if category == "ambiguity":
        finding["options"] = [{"text": "A", "cost": "a"}, {"text": "B", "cost": "b"}]
        finding["assessment"] = f"{review.UNANCHORED}: B"
    finding.update(fields)
    return finding


class TestValidation:
    @pytest.mark.parametrize("category", review.OUTCOMES)
    def test_each_outcome_passes_against_the_packet(
        self, core: dict[str, Any], category: str
    ) -> None:
        assert architecture.problems(_reviewer(category), core) == []

    def test_a_convention_anchor_is_one_of_the_packets_documents(
        self, repo: Path, core: dict[str, Any]
    ) -> None:
        ok = _reviewer("deviation", anchor={"kind": "convention", "id": "AGENTS.md#logging"})
        no_section = _reviewer("deviation", anchor={"kind": "convention", "id": "AGENTS.md#gone"})
        other = _reviewer("deviation", anchor={"kind": "convention", "id": "README.md#x"})

        assert architecture.problems(ok, core, repo) == []
        assert any("doesn't have" in p for p in architecture.problems(no_section, core))
        assert any("isn't one of the packet's" in p for p in architecture.problems(other, core))

    def test_a_decision_that_doesnt_govern_the_area_cant_be_deviated_from(
        self, core: dict[str, Any]
    ) -> None:
        finding = _reviewer(
            "deviation", anchor={"kind": "decision", "id": "2026-01-01-3-shapes.md"}
        )

        assert any("doesn't govern this area" in p for p in architecture.problems(finding, core))

    def test_rule_outcomes_come_only_from_the_mechanical_pass(self, core: dict[str, Any]) -> None:
        finding = _reviewer(
            "adherence", anchor={"kind": "rule", "id": "no-import: pkg.util -> pkg.paths"}
        )

        assert any("mechanical pass" in p for p in architecture.problems(finding, core))

    def test_evidence_must_be_in_the_area(self, core: dict[str, Any]) -> None:
        finding = _reviewer("deviation", evidence=["pkg.shapes.Base"])

        assert any("outside area 'core'" in p for p in architecture.problems(finding, core))

    def test_the_area_must_be_the_packets(self, core: dict[str, Any]) -> None:
        assert any(
            "packet's, 'core'" in p
            for p in architecture.problems(_reviewer("deviation", area="x"), core)
        )

    def test_a_fact_anchor_must_be_one_of_the_packets_facts(self, core: dict[str, Any]) -> None:
        finding = _reviewer(
            "decision_needed", anchor={"kind": "fact", "id": "arch.members.pkg.shapes"}
        )

        assert any("doesn't exist" in p for p in architecture.problems(finding, core))

    def test_a_docs_finding_isnt_an_architecture_finding(self, core: dict[str, Any]) -> None:
        assert architecture.problems({"page": "README.md"}, core) == [
            "an architecture finding says review: 'architecture'"
        ]


class TestReport:
    def test_tiers_in_rank_order_with_adherence_as_a_count(self, core: dict[str, Any]) -> None:
        findings = [
            _reviewer("ambiguity"),
            _reviewer("decision_needed"),
            _reviewer("deviation"),
            _reviewer("adherence", evidence=[]),
        ]

        out = architecture.report(core, findings)

        assert [f["anchor"]["kind"] for f in out["rule_deviations"]] == ["rule"]
        assert [f["anchor"]["kind"] for f in out["record_deviations"]] == ["decision"]
        assert len(out["decisions_needed"]) == len(out["ambiguities"]) == 1
        assert out["adherence"]["count"] == 2  # the mechanical one and the reviewer's
        assert out["rejected"] == []
        assert "blast" not in json.dumps(out)

    def test_more_evidence_ranks_first_within_a_tier(self, core: dict[str, Any]) -> None:
        one = _reviewer("decision_needed", evidence=["pkg.util"])
        two = _reviewer("decision_needed", evidence=["pkg.util", "pkg.paths"])

        out = architecture.report(core, [one, two])

        assert [len(f["evidence"]) for f in out["decisions_needed"]] == [2, 1]

    def test_an_invalid_or_repeated_finding_is_rejected_with_why(
        self, core: dict[str, Any]
    ) -> None:
        bad = _reviewer("deviation", evidence=["pkg.shapes.Base"])
        twice = [_reviewer("decision_needed"), _reviewer("decision_needed")]

        out = architecture.report(core, [bad, *twice])

        assert [r["index"] for r in out["rejected"]] == [0, 2]
        assert len(out["decisions_needed"]) == 1

    def test_the_report_carries_what_the_review_couldnt_settle(self, core: dict[str, Any]) -> None:
        out = architecture.report(core, [])

        assert out["unresolved_sites"] == core["unresolved_sites"]
        assert out["short_form_sites"] == core["short_form_sites"]
        assert out["external_sites"] == core["external_sites"]
        assert out["unassigned"] == core["unassigned"]


class TestCommandLine:
    def test_plan_validate_and_report(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["architecture", "--root", repo.as_posix(), "plan", "core"]) == 0
        packet = json.loads(capsys.readouterr().out)
        assert packet["area"]["id"] == "core"
        (tmp_path / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
        good = _reviewer("decision_needed", evidence=["pkg.util.normalise_path"])
        bad = _reviewer("deviation", evidence=["pkg.shapes.Base"])
        (tmp_path / "findings.json").write_text(json.dumps([good, bad]), encoding="utf-8")
        args = ["architecture", "--root", repo.as_posix()]
        files = [
            (tmp_path / "findings.json").as_posix(),
            "--packet",
            (tmp_path / "packet.json").as_posix(),
        ]

        assert cli.main([*args, "validate", *files]) == 1
        assert list(json.loads(capsys.readouterr().out)) == ["1"]
        assert cli.main([*args, "report", *files]) == 0
        out = json.loads(capsys.readouterr().out)
        assert len(out["decisions_needed"]) == 1
        assert [r["index"] for r in out["rejected"]] == [1]

    def test_no_config_exits_1_with_the_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["architecture", "--root", tmp_path.as_posix(), "plan", "core"]) == 1
        assert "nothing to check" in capsys.readouterr().err


def test_nothing_of_the_analysed_repository_is_imported(core: dict[str, Any]) -> None:
    """C19: the plan reads facts and pyeye's static analysis; it never imports the code."""
    assert core["modules"]
    assert not any(m == "pkg" or m.startswith("pkg.") for m in sys.modules)
