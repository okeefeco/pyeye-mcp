"""Failing tests for the recursive ``TypeRef`` shape on ``inspect()`` — Task 8.1.

Background
----------
The 2026-05-02 progressive-disclosure spec was amended on 2026-05-04 (commit
`edae961`) to replace the flat-string representation of type-bearing fields
(`parameters[].type`, `return_type`, attribute `type`) with a recursive
``TypeRef`` shape::

    type TypeRef = {
      raw: string              # always present — annotation slice as written
      handle?: Handle          # canonical handle when the head has exactly
                               # one canonical referent; absent otherwise
      args?: TypeRef[]         # recursive children for parameterized types;
                               # absent for bare names
    }

These tests pin the shape contract for every scenario the spec calls out
(including both halves of the head-canonicalisation rule and the Callable
degraded path). They are EXPECTED TO FAIL against the current implementation,
which still returns flat strings for those fields. Failure messages will
typically say ``isinstance(..., dict)`` failed because the value is ``str``.
That is the *correct* failure mode — Task 8.2 will introduce the TypeRef
builder that makes them pass.

Fixture layout
--------------
``tests/fixtures/typeref_basic/``::

    mypackage/
      __init__.py     # package marker / docstring
      models.py       # defines ``CustomModel`` (project class used as generic arg)
      services.py     # one function (or class) per scenario (a)–(h)

Each scenario lives in its own top-level definition in ``services.py`` so
failures point unambiguously at the scenario being exercised.

Scenarios (mirrors plan §8.1)
-----------------------------
(a) Bare-name leaf  — ``def bare_name_leaf(x: Path)``
(b) Generic, typing aliases — ``Dict[str, List[CustomModel]]``
(c) Generic, PEP 585 builtins — ``dict[str, list[CustomModel]]``
(d) PEP 604 union — ``str | None``
(e) Unresolvable forward ref — ``"FutureType"`` quoted, no such symbol
(f) Callable degraded path — ``Callable[[int, str], bool]``
(g) Return-type symmetry — ``-> Dict[str, CustomModel]``
(h) Attribute-type symmetry — ``HasTypedField.field: List[CustomModel]``
"""

from pathlib import Path
from typing import Any

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "typeref_basic"

_BARE_NAME_LEAF = "mypackage.services.bare_name_leaf"
_TYPING_ALIAS_GENERIC = "mypackage.services.typing_alias_generic"
_BUILTIN_GENERIC = "mypackage.services.builtin_generic"
_PEP604_UNION = "mypackage.services.pep604_union"
_UNRESOLVABLE_FORWARD = "mypackage.services.unresolvable_forward"
_CALLABLE_PARAM = "mypackage.services.callable_param"
_RETURNS_DICT_MODEL = "mypackage.services.returns_dict_model"
_HAS_TYPED_FIELD = "mypackage.services.HasTypedField.field"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the typeref_basic fixture."""
    return JediAnalyzer(str(_FIXTURE))


# ---------------------------------------------------------------------------
# TypeRef shape helper — used to keep per-test assertions focused on the
# scenario-specific facts rather than re-checking "is this even a dict" every
# time.
# ---------------------------------------------------------------------------


def _assert_typeref_shape(node: Any, *, where: str) -> None:
    """A TypeRef must be a dict with a non-empty ``raw`` string.

    ``handle`` and ``args`` are optional per the spec's per-node
    absence-vs-zero invariant; this helper only enforces the universal field.
    """
    assert isinstance(node, dict), (
        f"{where}: expected TypeRef dict, got {type(node).__name__} "
        f"(value={node!r}). The current implementation returns flat strings "
        "for type fields; this assertion pins the post-Phase-8 shape."
    )
    assert "raw" in node, f"{where}: TypeRef must contain 'raw' key (got {node!r})"
    assert isinstance(node["raw"], str), f"{where}: TypeRef.raw must be a str"
    assert node["raw"], f"{where}: TypeRef.raw must be non-empty"


def _first_param_type(result: dict[str, Any]) -> Any:
    """Return ``result['parameters'][0]['type']`` with a clear error if missing."""
    params = result.get("parameters")
    assert isinstance(params, list) and params, f"expected at least one parameter, got: {params!r}"
    p0 = params[0]
    assert (
        isinstance(p0, dict) and "type" in p0
    ), f"expected parameters[0] to carry a 'type' field, got: {p0!r}"
    return p0["type"]


# ---------------------------------------------------------------------------
# (a) Bare-name leaf — Path
# ---------------------------------------------------------------------------


class TestBareNameLeaf:
    """``def bare_name_leaf(x: Path)`` → leaf TypeRef ``{raw, handle}``."""

    @pytest.mark.asyncio
    async def test_bare_leaf_is_typeref_with_handle_and_no_args(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_BARE_NAME_LEAF, analyzer)
        type_node = _first_param_type(result)

        _assert_typeref_shape(type_node, where="parameters[0].type")
        assert (
            type_node["raw"] == "Path"
        ), f"raw must be the annotation as written; got {type_node['raw']!r}"
        assert type_node.get("handle") == "pathlib.Path", (
            f"handle must canonicalize Path → pathlib.Path; got " f"{type_node.get('handle')!r}"
        )
        assert "args" not in type_node, f"bare names omit 'args' (got {type_node.get('args')!r})"


# ---------------------------------------------------------------------------
# (b) Generic with typing aliases — Dict[str, List[CustomModel]]
# ---------------------------------------------------------------------------


class TestTypingAliasGeneric:
    """``Dict[str, List[CustomModel]]`` → recursive tree, typing.* heads.

    Pins the rule: handle is what Jedi resolves at the annotation site,
    NOT a normalized form. ``Dict`` (imported from typing) → ``typing.Dict``,
    even though Python ≥3.9 treats it as a deprecated alias for ``dict``.
    """

    @pytest.mark.asyncio
    async def test_root_handle_is_typing_dict(self, analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_TYPING_ALIAS_GENERIC, analyzer)
        root = _first_param_type(result)

        _assert_typeref_shape(root, where="parameters[0].type")
        assert (
            root["raw"] == "Dict[str, List[CustomModel]]"
        ), f"raw must be the annotation as written; got {root['raw']!r}"
        assert root.get("handle") == "typing.Dict", (
            "head canonicalisation: typing.Dict must NOT be rewritten to "
            f"builtins.dict; got handle={root.get('handle')!r}"
        )

        args = root.get("args")
        assert isinstance(args, list) and len(args) == 2, f"Dict has 2 type args; got args={args!r}"

        # arg 0: str → builtins.str (leaf)
        a0 = args[0]
        _assert_typeref_shape(a0, where="parameters[0].type.args[0]")
        assert a0["raw"] == "str"
        assert a0.get("handle") == "builtins.str"
        assert "args" not in a0

        # arg 1: List[CustomModel] → typing.List with one nested arg
        a1 = args[1]
        _assert_typeref_shape(a1, where="parameters[0].type.args[1]")
        assert a1["raw"] == "List[CustomModel]"
        assert a1.get("handle") == "typing.List", (
            f"typing.List must NOT be rewritten to builtins.list; "
            f"got handle={a1.get('handle')!r}"
        )
        nested = a1.get("args")
        assert isinstance(nested, list) and len(nested) == 1
        leaf = nested[0]
        _assert_typeref_shape(leaf, where="parameters[0].type.args[1].args[0]")
        assert leaf["raw"] == "CustomModel"
        assert leaf.get("handle") == "mypackage.models.CustomModel", (
            "project-class leaf must canonicalize to its definition site; "
            f"got handle={leaf.get('handle')!r}"
        )


# ---------------------------------------------------------------------------
# (c) Generic with PEP 585 builtins — dict[str, list[CustomModel]]
# ---------------------------------------------------------------------------


class TestBuiltinGeneric:
    """``dict[str, list[CustomModel]]`` → recursive tree, builtins.* heads.

    Pins the rule's other half: PEP 585 lowercase builtins resolve to
    ``builtins.dict`` / ``builtins.list``, NOT to ``typing.Dict`` / ``typing.List``.
    """

    @pytest.mark.asyncio
    async def test_root_handle_is_builtins_dict(self, analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_BUILTIN_GENERIC, analyzer)
        root = _first_param_type(result)

        _assert_typeref_shape(root, where="parameters[0].type")
        assert (
            root["raw"] == "dict[str, list[CustomModel]]"
        ), f"raw must be the annotation as written; got {root['raw']!r}"
        assert root.get("handle") == "builtins.dict", (
            "head canonicalisation: builtins.dict must NOT be rewritten to "
            f"typing.Dict; got handle={root.get('handle')!r}"
        )

        args = root.get("args")
        assert isinstance(args, list) and len(args) == 2, f"dict has 2 type args; got args={args!r}"

        a1 = args[1]
        _assert_typeref_shape(a1, where="parameters[0].type.args[1]")
        assert a1["raw"] == "list[CustomModel]"
        assert a1.get("handle") == "builtins.list", (
            f"builtins.list must NOT be rewritten to typing.List; "
            f"got handle={a1.get('handle')!r}"
        )


# ---------------------------------------------------------------------------
# (d) PEP 604 union — str | None
# ---------------------------------------------------------------------------


class TestPep604Union:
    """``str | None`` → root has no ``handle`` (no single head); ``args`` carry
    each alternative with its own resolution result.
    """

    @pytest.mark.asyncio
    async def test_union_root_has_no_handle_and_args_carry_alternatives(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_PEP604_UNION, analyzer)
        root = _first_param_type(result)

        _assert_typeref_shape(root, where="parameters[0].type")
        assert (
            root["raw"] == "str | None"
        ), f"raw must be the annotation as written; got {root['raw']!r}"
        assert "handle" not in root, (
            "PEP 604 union has no single canonical head — handle must be absent. "
            f"Got handle={root.get('handle')!r}"
        )

        args = root.get("args")
        assert (
            isinstance(args, list) and len(args) == 2
        ), f"str | None has 2 alternatives; got args={args!r}"

        # str arm → builtins.str (Jedi resolves cleanly).
        str_arm = args[0]
        _assert_typeref_shape(str_arm, where="parameters[0].type.args[0]")
        assert str_arm["raw"] == "str"
        assert (
            str_arm.get("handle") == "builtins.str"
        ), f"str arm must resolve to builtins.str; got {str_arm.get('handle')!r}"

        # None arm: per no-guess rule, handle is absent unless Jedi resolves it
        # to a single definition. Empirically Jedi returns [] for None in
        # annotation context, so handle must be absent. If a future Jedi /
        # implementation legitimately resolves it (e.g. to builtins.None /
        # types.NoneType), that is also conformant — but a wrong handle is not.
        none_arm = args[1]
        _assert_typeref_shape(none_arm, where="parameters[0].type.args[1]")
        assert none_arm["raw"] == "None"
        if "handle" in none_arm:
            assert none_arm["handle"] in {"builtins.None", "types.NoneType"}, (
                "if handle is populated for None it must be a recognized "
                f"NoneType handle; got {none_arm['handle']!r}"
            )


# ---------------------------------------------------------------------------
# (e) Unresolvable forward ref — "FutureType"
# ---------------------------------------------------------------------------


class TestUnresolvableForwardRef:
    """``def f(x: "FutureType")`` where FutureType doesn't exist anywhere
    in the project → ``{raw: "FutureType"}`` with ``handle`` ABSENT.

    This pins the no-guess rule: a wrong handle is worse than an absent one.
    The lookup-style failure mode (silently binding to an unrelated symbol)
    must not recur — see the spec's reference to the prior bug.
    """

    @pytest.mark.asyncio
    async def test_forward_ref_yields_typeref_without_handle(self, analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_UNRESOLVABLE_FORWARD, analyzer)
        node = _first_param_type(result)

        _assert_typeref_shape(node, where="parameters[0].type")
        assert node["raw"] == "FutureType", (
            "raw must be the unquoted forward-ref content; " f"got {node['raw']!r}"
        )
        assert "handle" not in node, (
            "no-guess rule: unresolvable forward ref must NOT carry a handle. "
            f"Got handle={node.get('handle')!r}"
        )
        assert "args" not in node, (
            "bare-name forward ref must omit 'args'; " f"got args={node.get('args')!r}"
        )


# ---------------------------------------------------------------------------
# (f) Callable degraded path — Callable[[int, str], bool]
# ---------------------------------------------------------------------------


class TestCallableDegradedPath:
    """``Callable[[int, str], bool]`` → conformant TypeRef even when the
    implementation declines to populate ``args`` / ``handle``.

    The spec explicitly permits Callable to degrade in v1 because its bracket
    structure (``[args_list, return_type]``) doesn't fit the uniform recursion.
    The only hard requirement is a non-empty ``raw`` carrying the full
    expression as written.
    """

    @pytest.mark.asyncio
    async def test_callable_preserves_raw_handle_and_args_optional(
        self, analyzer: JediAnalyzer
    ) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_CALLABLE_PARAM, analyzer)
        node = _first_param_type(result)

        _assert_typeref_shape(node, where="parameters[0].type")
        assert node["raw"] == "Callable[[int, str], bool]", (
            "raw must preserve the full Callable expression as written; " f"got {node['raw']!r}"
        )
        # handle and args may be absent — that is conformant per the spec.
        # If the implementation chooses to populate either, no further
        # assertions are made here (a future Callable-aware variant of the
        # spec will add stricter expectations).


# ---------------------------------------------------------------------------
# (g) Return-type symmetry — -> Dict[str, CustomModel]
# ---------------------------------------------------------------------------


class TestReturnTypeSymmetry:
    """``def f(...) -> Dict[str, CustomModel]`` → ``inspect.return_type`` is
    a TypeRef tree with the same recursive shape parameter types use.
    """

    @pytest.mark.asyncio
    async def test_return_type_is_typeref_tree(self, analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_RETURNS_DICT_MODEL, analyzer)
        rt = result.get("return_type")

        _assert_typeref_shape(rt, where="return_type")
        assert rt["raw"] == "Dict[str, CustomModel]"
        assert rt.get("handle") == "typing.Dict", (
            "return-type head must follow the same canonicalisation rules as "
            f"parameter types; got handle={rt.get('handle')!r}"
        )

        args = rt.get("args")
        assert isinstance(args, list) and len(args) == 2

        a0 = args[0]
        _assert_typeref_shape(a0, where="return_type.args[0]")
        assert a0.get("handle") == "builtins.str"

        a1 = args[1]
        _assert_typeref_shape(a1, where="return_type.args[1]")
        assert a1["raw"] == "CustomModel"
        assert a1.get("handle") == "mypackage.models.CustomModel"


# ---------------------------------------------------------------------------
# (h) Attribute-type symmetry — class C: field: List[CustomModel]
# ---------------------------------------------------------------------------


class TestAttributeTypeSymmetry:
    """``HasTypedField.field: List[CustomModel]`` → ``inspect(handle).type``
    is a TypeRef tree with the same recursive shape parameter types use.
    """

    @pytest.mark.asyncio
    async def test_attribute_type_is_typeref_tree(self, analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_HAS_TYPED_FIELD, analyzer)
        type_node = result.get("type")

        _assert_typeref_shape(type_node, where="type")
        assert (
            type_node["raw"] == "List[CustomModel]"
        ), f"raw must be the annotation as written; got {type_node['raw']!r}"
        assert type_node.get("handle") == "typing.List", (
            "attribute-type head must follow the same canonicalisation rules "
            f"as parameter types; got handle={type_node.get('handle')!r}"
        )

        args = type_node.get("args")
        assert isinstance(args, list) and len(args) == 1
        leaf = args[0]
        _assert_typeref_shape(leaf, where="type.args[0]")
        assert leaf["raw"] == "CustomModel"
        assert leaf.get("handle") == "mypackage.models.CustomModel"
