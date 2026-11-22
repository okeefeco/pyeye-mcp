"""Candidate pairs: scored from names, docstrings and parameters; never findings (#1092)."""

from __future__ import annotations

import math

import pytest

from pyeye.docs_facts.structure import candidates as cand
from pyeye.docs_facts.structure.dump import Definition, Dump


def _fn(handle: str, summary: str = "", signature: str | None = None) -> Definition:
    module = handle.rsplit(".", 1)[0]
    return Definition(handle, "function", module, module, signature, summary)


def _cls(handle: str) -> Definition:
    module = handle.rsplit(".", 1)[0]
    return Definition(handle, "class", module, module, None, "")


def _method(owner: str, name: str) -> Definition:
    module = owner.rsplit(".", 1)[0]
    return Definition(f"{owner}.{name}", "method", module, owner, f"{name}(self)", "")


def _dump(*definitions: Definition) -> Dump:
    return Dump(modules=(), definitions=definitions)


class TestTokens:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("get_base_prefix", ("get", "base", "prefix")),
            ("HTTPRequestParser", ("httprequest", "parser")),
            ("readFiles", ("read", "file")),
            ("class_access", ("class", "access")),  # 'ss' isn't a plural
            ("the self of a 2 x", ()),
        ],
    )
    def test_tokens(self, text: str, expected: tuple[str, ...]) -> None:
        assert cand.tokens(text) == expected

    def test_parameters(self) -> None:
        assert cand.parameters("f(self, path: str, retries: int=3) -> str") == (
            "self  path  retries"
        )
        assert cand.parameters("Thing") == ""
        assert cand.parameters(None) == ""


class TestItems:
    def test_methods_count_by_name_only_and_dunders_are_left_out(self) -> None:
        found = cand.items(
            _dump(
                _fn("a.load_file", "Load a file.", "load_file(path)"),
                _cls("a.Store"),
                _method("a.Store", "save_file"),
                _method("a.Store", "__init__"),
                _method("a.Store", "__repr__"),
            )
        )

        assert [(i.handle, i.name, i.doc, i.params) for i in found] == [
            ("a.load_file", ("load", "file"), ("load", "file"), ("path",)),
            ("a.Store", ("store",), (), ()),
            ("a.Store.save_file", ("save", "file"), (), ()),
        ]

    def test_areas_default_to_the_module(self) -> None:
        found = cand.items(_dump(_fn("a.f"), _fn("b.g")), {"a": "core"})

        assert [i.area for i in found] == ["core", "b"]

    def test_hook_names_need_three_owners(self) -> None:
        found = cand.items(
            _dump(
                *(_method(f"m.C{n}", "process") for n in range(3)),
                *(_method(f"m.D{n}", "close") for n in range(2)),
            )
        )

        assert cand.hook_names(found) == {"process"}


class TestScore:
    def test_the_trial_formula(self) -> None:
        dump = _dump(
            _fn("a.read_config", "Read the configuration file.", "read_config(config_file)"),
            _fn("b.load_config", "Load the configuration file.", "load_config(config_file)"),
            _fn("c.unrelated_thing"),
        )
        weights = cand.idf(cand.items(dump))
        name = cand.overlap(("read", "config"), ("load", "config"), weights)
        doc = cand.jaccard(
            ("read", "configuration", "file"), ("load", "configuration", "file"), weights
        )
        params = cand.jaccard(("config", "file"), ("config", "file"), weights)

        (pair,) = cand.score(dump)

        assert (pair.a, pair.b) == ("a.read_config", "b.load_config")
        assert pair.score == round(name + 0.5 * doc + 0.25 * params, 4)
        assert params == 1.0

    def test_overlap_is_relative_to_the_shorter_name(self) -> None:
        weights = {"base": 1.0, "prefix": 1.0, "get": 0.5, "env": 2.0}

        shared = 2.0
        expected = (shared / 2.0) * (1 - math.exp(-shared / 3))
        assert cand.overlap(("base", "prefix"), ("get", "base", "prefix", "env"), weights) == (
            pytest.approx(expected)
        )
        assert cand.overlap((), ("base",), weights) == 0.0
        assert cand.overlap(("x",), ("x",), {"x": 0.0}) == 0.0
        assert cand.jaccard((), ("x",), weights) == 0.0
        assert cand.jaccard(("x",), ("x",), {"x": 0.0}) == 0.0

    def test_a_pair_needs_a_shared_name_word(self) -> None:
        """Docstrings alone never make a candidate (the trial's rule)."""
        dump = _dump(_fn("a.alpha", "Normalise a path."), _fn("b.beta", "Normalise a path."))

        assert cand.score(dump) == []

    def test_interface_hooks_are_skipped(self) -> None:
        dump = _dump(
            *(_method(f"m{n}.C", "process_request") for n in range(3)),
            _fn("x.process_request_body"),
            *(_fn(f"y{n}.other_thing") for n in range(4)),  # so 'process' has weight
        )

        pairs = cand.score(dump)

        assert pairs and all(
            not (p.a.endswith(".process_request") and p.b.endswith(".process_request"))
            for p in pairs
        )

    def test_byte_identical_methods_in_two_classes_pair_up(self) -> None:
        """RFC #1083's within-area test case: Env/EnvManager.get_base_prefix."""
        dump = _dump(
            _cls("env.base.Env"),
            _method("env.base.Env", "get_base_prefix"),
            _cls("env.manager.EnvManager"),
            _method("env.manager.EnvManager", "get_base_prefix"),
        )
        areas = {"env.base": "env", "env.manager": "env"}

        assert cand.score(dump, areas) == []
        pairs = cand.score(dump, areas, within_areas=True)
        assert ("env.base.Env.get_base_prefix", "env.manager.EnvManager.get_base_prefix") in {
            (p.a, p.b) for p in pairs
        }

    def test_within_areas_never_pairs_inside_one_owner(self) -> None:
        dump = _dump(_cls("m.C"), _method("m.C", "load_file"), _method("m.C", "load_files"))

        assert cand.score(dump, within_areas=True) == []

    def test_order_is_best_first_then_by_handle(self) -> None:
        dump = _dump(
            _fn("a.load_config", "Load the configuration file."),
            _fn("b.load_config", "Load the configuration file."),
            _fn("c.load_data"),
            _fn("d.load_data"),
        )

        pairs = cand.score(dump)

        assert pairs == sorted(pairs, key=lambda p: (-p.score, p.a, p.b))
        assert (pairs[0].a, pairs[0].b) == ("a.load_config", "b.load_config")

    def test_an_item_with_no_name_tokens_pairs_with_nothing(self) -> None:
        dump = _dump(_fn("c.load"), _fn("a.x"), _fn("b.x"))

        assert cand.score(dump) == []
