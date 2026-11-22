"""Relationship labels from pyeye's facts; deprecation is a flag, never a label (#1092)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from pyeye.docs_facts.structure import dump, relations
from tests.utils.structure import write_project


@dataclass
class FakeFacts:
    calls: dict[str, frozenset[str] | None] = field(default_factory=dict)
    bases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    warns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def callees(self, handle: str) -> frozenset[str] | None:
        return self.calls.get(handle, frozenset())

    def superclasses(self, handle: str) -> tuple[str, ...] | None:
        return self.bases.get(handle, ())

    def deprecation(self, handle: str) -> tuple[str, ...] | None:
        return self.warns.get(handle, ())


def _owner(mapping: dict[str, str]):  # type: ignore[no-untyped-def]
    return mapping.get


class TestRelate:
    def test_a_call_either_way_is_delegates(self) -> None:
        facts = FakeFacts(calls={"b.wrap": frozenset({"a.core"})})

        assert relations.relate("a.core", "b.wrap", facts, _owner({})).label == "delegates"
        assert relations.relate("b.wrap", "a.core", facts, _owner({})).label == "delegates"

    def test_constructing_a_class_or_calling_its_method_is_delegates(self) -> None:
        facts = FakeFacts(calls={"b.make": frozenset({"a.Thing.__init__"})})

        assert relations.relate("a.Thing", "b.make", facts, _owner({})).label == "delegates"

    def test_a_prefix_that_isnt_a_dotted_child_is_no_call(self) -> None:
        facts = FakeFacts(calls={"b.f": frozenset({"a.core_extra"})})

        assert relations.relate("a.core", "b.f", facts, _owner({})).label == relations.UNVERIFIED

    def test_override_through_a_transitive_ancestor(self) -> None:
        facts = FakeFacts(bases={"m.Leaf": ("m.Mid",), "m.Mid": ("m.Root",)})
        owner = _owner({"m.Root.area": "m.Root", "m.Leaf.area": "m.Leaf"})

        assert relations.relate("m.Root.area", "m.Leaf.area", facts, owner).label == "override"

    def test_shared_ancestor_is_sibling(self) -> None:
        facts = FakeFacts(bases={"m.A": ("m.Base",), "m.B": ("m.Base",)})
        owner = _owner({"m.A.scale": "m.A", "m.B.resize": "m.B"})

        assert relations.relate("m.A.scale", "m.B.resize", facts, owner).label == "sibling"

    def test_same_name_without_ancestry_is_unverified(self) -> None:
        owner = _owner({"m.A.run": "m.A", "n.B.run": "n.B"})

        relation = relations.relate("m.A.run", "n.B.run", FakeFacts(), owner)

        assert relation.label == relations.UNVERIFIED and relation.measured

    def test_an_unconditional_deprecation_flags_but_never_labels(self) -> None:
        """A deprecated copy is still a copy: the pair stays a possible duplicate."""
        facts = FakeFacts(warns={"a.old": ("unconditional",), "b.new": ("conditional",)})

        relation = relations.relate("a.old", "b.new", facts, _owner({}))

        assert relation.label == relations.UNVERIFIED
        assert relation.deprecated == ("a.old",)
        assert relation.conditionally_deprecated == ("b.new",)

    def test_unmeasured_callees_are_reported(self) -> None:
        facts = FakeFacts(calls={"a.f": None})

        assert not relations.relate("a.f", "b.g", facts, _owner({})).measured

    def test_ancestors_tolerate_cycles(self) -> None:
        facts = FakeFacts(bases={"m.A": ("m.B",), "m.B": ("m.A", "m.C")})

        assert relations.ancestors("m.A", facts) == {"m.B", "m.C"}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_project(tmp_path_factory.mktemp("structure"))


@pytest.fixture(scope="module")
def labelled(project: Path) -> dict[tuple[str, str], relations.Relation]:
    pairs = [
        ("pkg.paths.helper", "pkg.util.normalise_path"),
        ("pkg.old.old_helper", "pkg.paths.helper"),
        ("pkg.old.maybe_old", "pkg.paths.helper"),
        ("pkg.shapes.Base.area", "pkg.shapes.Square.area"),
        ("pkg.shapes.Square.scale_shape", "pkg.shapes.Circle.resize_shape"),
        ("pkg.cfg.load_config", "pkg.settings.read_config"),
        ("pkg.shapes.Square", "pkg.util.normalise_path"),
    ]
    with dump.Pyeye(project) as ops:
        collected = dump.collect(project, include=("pkg/*",), pyeye=ops)
        found = relations.relate_all(pairs, relations.PyeyeFacts(ops, collected), collected)
    return {(r.a, r.b): r for r in found}


class TestOnPyeyeFacts:
    def test_delegation(self, labelled: dict[tuple[str, str], relations.Relation]) -> None:
        assert labelled[("pkg.paths.helper", "pkg.util.normalise_path")].label == "delegates"

    def test_deprecation_is_a_flag(
        self, labelled: dict[tuple[str, str], relations.Relation]
    ) -> None:
        old = labelled[("pkg.old.old_helper", "pkg.paths.helper")]
        maybe = labelled[("pkg.old.maybe_old", "pkg.paths.helper")]

        assert (old.label, old.deprecated) == (relations.UNVERIFIED, ("pkg.old.old_helper",))
        assert (maybe.deprecated, maybe.conditionally_deprecated) == ((), ("pkg.old.maybe_old",))

    def test_override_and_sibling(
        self, labelled: dict[tuple[str, str], relations.Relation]
    ) -> None:
        assert labelled[("pkg.shapes.Base.area", "pkg.shapes.Square.area")].label == "override"
        assert (
            labelled[("pkg.shapes.Square.scale_shape", "pkg.shapes.Circle.resize_shape")].label
            == "sibling"
        )

    def test_an_unexplained_pair_stays_unverified(
        self, labelled: dict[tuple[str, str], relations.Relation]
    ) -> None:
        relation = labelled[("pkg.cfg.load_config", "pkg.settings.read_config")]

        assert relation.label == relations.UNVERIFIED and relation.measured

    def test_a_class_is_measured_through_its_methods(
        self, labelled: dict[tuple[str, str], relations.Relation]
    ) -> None:
        assert labelled[("pkg.shapes.Square", "pkg.util.normalise_path")].measured

    def test_a_class_without_methods_is_unmeasured(self, project: Path) -> None:
        empty = dump.Definition("m.Empty", "class", "m", "m", None, "")
        collected = dump.Dump(modules=(), definitions=(empty,))
        with dump.Pyeye(project) as ops:
            facts = relations.PyeyeFacts(ops, collected)

            assert facts.callees("m.Empty") is None
            assert facts.callees("no.such.function") is None
            assert facts.superclasses("no.such.Thing") is None
            assert facts.deprecation("no.such.thing") is None
