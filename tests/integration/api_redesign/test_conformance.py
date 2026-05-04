"""Conformance tests for the 2026-05-02 progressive-disclosure API design.

These tests pin acceptance criteria from the spec at
``docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md``.
Unlike the unit tests under ``tests/unit/mcp/operations/``, these exercise
the full ``inspect()`` pipeline end-to-end against a dedicated fixture
project — the same shape an external conformance harness would use to
verify a third-party implementation.

Each test class corresponds to a specific numbered acceptance criterion
(see the docstring of each class). When adding new criteria, add a new
class with a docstring naming the criterion number; do not extend an
existing class with unrelated assertions.
"""

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.inspect import inspect

# ---------------------------------------------------------------------------
# Criterion #14 — TypeRef shape conformance across both halves of the
# head-canonicalisation rule, plus cross-fixture invariants for the
# no-guess rule, return-type symmetry, and the Callable degraded path.
# ---------------------------------------------------------------------------

_TYPEREF_COMPOUND_FIXTURE = Path(__file__).parent / "fixtures" / "typeref_compound"


@pytest.fixture
def compound_analyzer() -> JediAnalyzer:
    """JediAnalyzer rooted at the typeref_compound conformance fixture."""
    return JediAnalyzer(str(_TYPEREF_COMPOUND_FIXTURE))


def _assert_typeref(node: Any, *, where: str) -> None:
    """Universal TypeRef shape: dict with non-empty ``raw`` string.

    ``handle`` and ``args`` are optional per the per-node absence-vs-zero
    invariant; this helper enforces only the universal field so every
    other assertion in this module can stay focused on its specific fact.
    """
    assert isinstance(node, dict), (
        f"{where}: expected TypeRef dict, got {type(node).__name__} " f"(value={node!r})"
    )
    assert (
        "raw" in node and isinstance(node["raw"], str) and node["raw"]
    ), f"{where}: TypeRef must carry a non-empty 'raw' string; got {node!r}"


def _first_param_type(result: dict[str, Any]) -> Any:
    """Return ``parameters[0]['type']`` with a clear error if missing."""
    params = result.get("parameters")
    assert isinstance(params, list) and params, f"expected at least one parameter; got: {params!r}"
    p0 = params[0]
    assert (
        isinstance(p0, dict) and "type" in p0
    ), f"expected parameters[0] to carry a 'type' field; got: {p0!r}"
    return p0["type"]


class TestCriterion14TypeRefConformance:
    """Acceptance criterion #14 — TypeRef shape conformance.

    Pins the head-canonicalisation rule (``typing.Dict`` MUST NOT be silently
    rewritten to ``builtins.dict`` and vice-versa), the per-leaf project
    resolution that compound generics must thread through, the no-guess
    rule for unresolvable forward refs, return-type symmetry, and the
    Callable degraded-path contract.

    Each test method maps to one bullet of the criterion as written in the
    spec; when the criterion changes, the corresponding test method here
    is the canonical place to update.
    """

    # ---- Fixture A — typing aliases ---------------------------------------

    @pytest.mark.asyncio
    async def test_fixture_a_root_handle_is_typing_dict(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture A: ``Dict[str, List[CustomModel]]`` root → ``typing.Dict``."""
        result = await inspect("service_typing_aliases.process", compound_analyzer)
        root = _first_param_type(result)
        _assert_typeref(root, where="parameters[0].type")

        assert (
            root["raw"] == "Dict[str, List[CustomModel]]"
        ), f"raw must preserve the annotation as written; got {root['raw']!r}"
        assert root.get("handle") == "typing.Dict", (
            "head canonicalisation: Dict imported from typing MUST resolve "
            "to typing.Dict, not builtins.dict. The implementation is "
            "forbidden from silently rewriting one form to the other. "
            f"Got handle={root.get('handle')!r}"
        )

    @pytest.mark.asyncio
    async def test_fixture_a_recursive_args_resolve_per_leaf(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture A: nested args resolve per-leaf — ``str``, ``List``, ``CustomModel``."""
        result = await inspect("service_typing_aliases.process", compound_analyzer)
        root = _first_param_type(result)

        args = root.get("args")
        assert isinstance(args, list) and len(args) == 2, f"Dict has 2 type args; got args={args!r}"

        # arg 0: str → builtins.str (leaf)
        a0 = args[0]
        _assert_typeref(a0, where="parameters[0].type.args[0]")
        assert a0.get("handle") == "builtins.str", (
            f"first arg must canonicalize to builtins.str; " f"got handle={a0.get('handle')!r}"
        )

        # arg 1: List[CustomModel] → typing.List with one nested arg
        a1 = args[1]
        _assert_typeref(a1, where="parameters[0].type.args[1]")
        assert a1.get("handle") == "typing.List", (
            "second arg head: List imported from typing MUST resolve to "
            f"typing.List, not builtins.list. Got handle={a1.get('handle')!r}"
        )

        nested = a1.get("args")
        assert (
            isinstance(nested, list) and len(nested) == 1
        ), f"List has 1 type arg; got args={nested!r}"
        leaf = nested[0]
        _assert_typeref(leaf, where="parameters[0].type.args[1].args[0]")
        # Project class: handle is fixture-layout-dependent. The criterion
        # is "resolves to the project's CustomModel," not a specific FQN —
        # accept any path that ends in .CustomModel and threads through
        # the project's models module.
        leaf_handle = leaf.get("handle")
        assert isinstance(leaf_handle, str) and leaf_handle, (
            "project-class leaf must carry a handle (resolves via Jedi at "
            f"the annotation site); got handle={leaf_handle!r}"
        )
        assert leaf_handle.endswith(
            ".CustomModel"
        ), f"leaf handle must end with .CustomModel; got {leaf_handle!r}"
        assert "models" in leaf_handle, (
            "leaf handle must thread through the project's models module; " f"got {leaf_handle!r}"
        )

    @pytest.mark.asyncio
    async def test_fixture_a_every_node_has_non_empty_raw(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture A: every node in the recursive tree carries non-empty ``raw``."""
        result = await inspect("service_typing_aliases.process", compound_analyzer)
        root = _first_param_type(result)

        # Walk the whole tree and assert raw at every node.
        def _walk(node: Any, where: str) -> None:
            _assert_typeref(node, where=where)
            for i, child in enumerate(node.get("args", []) or []):
                _walk(child, where=f"{where}.args[{i}]")

        _walk(root, where="parameters[0].type")

    # ---- Fixture B — PEP 585 builtins -------------------------------------

    @pytest.mark.asyncio
    async def test_fixture_b_root_handle_is_builtins_dict(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture B: ``dict[str, list[CustomModel]]`` root → ``builtins.dict``."""
        result = await inspect("service_pep585.process", compound_analyzer)
        root = _first_param_type(result)
        _assert_typeref(root, where="parameters[0].type")

        assert (
            root["raw"] == "dict[str, list[CustomModel]]"
        ), f"raw must preserve the annotation as written; got {root['raw']!r}"
        assert root.get("handle") == "builtins.dict", (
            "head canonicalisation: lowercase dict MUST resolve to "
            "builtins.dict, not typing.Dict. The implementation is forbidden "
            f"from silently rewriting one form to the other. "
            f"Got handle={root.get('handle')!r}"
        )

    @pytest.mark.asyncio
    async def test_fixture_b_inner_list_handle_is_builtins_list(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture B: nested ``list[CustomModel]`` → ``builtins.list``."""
        result = await inspect("service_pep585.process", compound_analyzer)
        root = _first_param_type(result)
        args = root.get("args")
        assert isinstance(args, list) and len(args) == 2

        a1 = args[1]
        _assert_typeref(a1, where="parameters[0].type.args[1]")
        assert a1.get("handle") == "builtins.list", (
            "lowercase list MUST resolve to builtins.list, not typing.List; "
            f"got handle={a1.get('handle')!r}"
        )

    # ---- Cross-fixture: typing vs builtin halves are DISTINCT --------------

    @pytest.mark.asyncio
    async def test_typing_and_builtin_halves_produce_distinct_root_handles(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Load-bearing: Fixtures A and B must NOT collapse to the same handle.

        This is the assertion that catches a silent ``typing.Dict`` ↔
        ``builtins.dict`` rewrite at the implementation layer. Asserting each
        fixture in isolation could pass even if both produced (say)
        ``builtins.dict``; comparing them across fixtures is the only way
        to pin the head-canonicalisation rule against the rewriting failure
        mode the spec explicitly forbids.
        """
        result_a = await inspect("service_typing_aliases.process", compound_analyzer)
        result_b = await inspect("service_pep585.process", compound_analyzer)

        root_a = _first_param_type(result_a)
        root_b = _first_param_type(result_b)

        handle_a = root_a.get("handle")
        handle_b = root_b.get("handle")

        assert (
            handle_a == "typing.Dict"
        ), f"Fixture A precondition: typing.Dict expected; got {handle_a!r}"
        assert (
            handle_b == "builtins.dict"
        ), f"Fixture B precondition: builtins.dict expected; got {handle_b!r}"
        assert handle_a != handle_b, (
            "head canonicalisation: typing.Dict and builtins.dict MUST be "
            "distinct handles in the wire format. If they collapse, the "
            "implementation has silently normalised one form — a spec "
            f"violation. Got handle_a={handle_a!r}, handle_b={handle_b!r}."
        )

    # ---- Cross-fixture: forward-ref no-guess rule -------------------------

    @pytest.mark.asyncio
    async def test_forward_ref_leaf_has_raw_but_no_handle(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Forward-ref ``"DoesNotExist"`` → ``raw`` present, ``handle`` ABSENT.

        Pins the no-guess rule: ``DoesNotExist`` is a syntactically-valid
        Python identifier but no canonical referent exists in the project.
        A wrong handle would be worse than an absent one — best-effort
        global bare-name search is non-conforming.
        """
        result = await inspect("service_forward_ref.future", compound_analyzer)
        node = _first_param_type(result)
        _assert_typeref(node, where="parameters[0].type")

        assert (
            "DoesNotExist" in node["raw"]
        ), f"raw must carry the forward-ref content; got {node['raw']!r}"
        assert "handle" not in node, (
            "no-guess rule: an unresolvable forward ref MUST NOT carry a "
            f"handle. Got handle={node.get('handle')!r}"
        )

    # ---- Cross-fixture: Callable degraded path ----------------------------

    @pytest.mark.asyncio
    async def test_callable_preserves_raw_handle_and_args_optional(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Callable → non-empty ``raw`` mandatory; ``handle``/``args`` optional.

        The spec explicitly permits Callable to degrade in v1 because its
        bracket structure (``[args_list, return_type]``) does not fit the
        uniform TypeRef recursion. The only hard requirement is the full
        expression preserved in ``raw``.
        """
        result = await inspect("service_callable.register", compound_analyzer)
        node = _first_param_type(result)
        _assert_typeref(node, where="parameters[0].type")

        assert node["raw"] == "Callable[[int, str], bool]", (
            "raw must preserve the full Callable expression as written; " f"got {node['raw']!r}"
        )
        # handle and args may be absent; if handle IS present it must be a
        # legitimate Callable canonicalisation (not a guessed match). Both
        # collections.abc.Callable and typing.Callable are acceptable —
        # they refer to the same underlying object and Jedi resolves
        # collections.abc.Callable back to typing.Callable in many setups.
        if "handle" in node:
            assert node["handle"] in {
                "typing.Callable",
                "collections.abc.Callable",
            }, (
                "if handle is populated for Callable it must be a recognized "
                f"Callable canonicalisation; got {node['handle']!r}"
            )

    # ---- Cross-fixture: return-type symmetry on Fixture A -----------------

    @pytest.mark.asyncio
    async def test_return_type_follows_same_recursive_shape(
        self, compound_analyzer: JediAnalyzer
    ) -> None:
        """Fixture A return type ``List[CustomModel]`` → recursive TypeRef.

        Pins the symmetry requirement: ``return_type`` follows the identical
        recursive shape as parameter ``type``. The same head-canonicalisation
        rule (typing.* preserved, no silent rewrite) applies.
        """
        result = await inspect("service_typing_aliases.process", compound_analyzer)
        rt = result.get("return_type")
        _assert_typeref(rt, where="return_type")

        assert (
            rt["raw"] == "List[CustomModel]"
        ), f"raw must preserve the annotation as written; got {rt['raw']!r}"
        assert rt.get("handle") == "typing.List", (
            "return-type head must follow the same canonicalisation rules "
            f"as parameter types; got handle={rt.get('handle')!r}"
        )

        args = rt.get("args")
        assert isinstance(args, list) and len(args) == 1, f"List has 1 type arg; got args={args!r}"
        leaf = args[0]
        _assert_typeref(leaf, where="return_type.args[0]")
        leaf_handle = leaf.get("handle")
        assert (
            isinstance(leaf_handle, str)
            and leaf_handle.endswith(".CustomModel")
            and "models" in leaf_handle
        ), (
            "return-type leaf must canonicalize to the project's CustomModel "
            f"definition site; got {leaf_handle!r}"
        )
