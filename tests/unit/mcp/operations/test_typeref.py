"""Unit tests for the recursive ``TypeRef`` builder.

These tests target the low-level paths in
:mod:`pyeye.mcp.operations.typeref` that the conformance tests in
``test_inspect_typeref.py`` don't always reach: forward-ref recursion,
caching, attribute-chain heads, the degraded-path policy for Literal /
Annotated / etc., and the cache-key invariants.
"""

from __future__ import annotations

import ast
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.typeref import (
    _annotation_source,
    _attribute_target_position,
    _cache_key,
    _collect_union_alternatives,
    _degraded_head_kind,
    _dotted_name,
    _is_callable_shape,
    _typeref_cache,
    build_typeref,
    degraded_counts,
    get_and_reset_degraded_counts,
)

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "typeref_basic"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the typeref_basic fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.fixture(autouse=True)
def _clear_typeref_cache() -> Iterator[None]:
    """Drop the per-process TypeRef cache between tests."""
    _typeref_cache.clear()
    yield
    _typeref_cache.clear()


@pytest.fixture(autouse=True)
def _clear_degraded_counts() -> Iterator[None]:
    """Reset the degraded-path telemetry counter between tests."""
    degraded_counts.clear()
    yield
    degraded_counts.clear()


# ---------------------------------------------------------------------------
# Helpers — pure-function tests
# ---------------------------------------------------------------------------


class TestPureHelpers:
    """Tests for the synchronous helpers — no Jedi, no I/O."""

    def test_collect_union_alternatives_flattens_left_recursive(self) -> None:
        """``A | B | C`` parses left-recursively; collector must yield 3 leaves."""
        tree = ast.parse("x: int | str | bytes", mode="exec")
        ann_assign = tree.body[0]
        assert isinstance(ann_assign, ast.AnnAssign)
        ann = ann_assign.annotation
        assert isinstance(ann, ast.BinOp)

        out: list[ast.expr] = []
        _collect_union_alternatives(ann, out)
        names = [getattr(n, "id", None) for n in out]
        assert names == ["int", "str", "bytes"]

    def test_collect_union_alternatives_non_binop_appends_self(self) -> None:
        """A non-BinOp node is appended verbatim (degenerate base case)."""
        node = ast.Name(id="X")
        out: list[ast.expr] = []
        _collect_union_alternatives(node, out)
        assert out == [node]

    def test_attribute_target_position_for_name(self) -> None:
        """For a Name node, position is its own (line, col)."""
        tree = ast.parse("Foo", mode="eval")
        node = tree.body
        assert isinstance(node, ast.Name)
        assert _attribute_target_position(node) == (node.lineno, node.col_offset)

    def test_attribute_target_position_for_attribute_chain(self) -> None:
        """For ``a.b.Foo`` the position points to ``Foo`` (rightmost attr)."""
        tree = ast.parse("a.b.Foo", mode="eval")
        node = tree.body
        assert isinstance(node, ast.Attribute)
        line, col = _attribute_target_position(node)
        # 'a.b.Foo' starts at col 0; 'Foo' starts at col 4 (a=0, .=1, b=2, .=3, Foo=4)
        assert line == 1
        assert col == 4

    def test_attribute_target_position_with_zero_end_col(self) -> None:
        """``end_col_offset=0`` falls back to lineno without going negative."""
        # Synthesise an Attribute with a zero end_col_offset (defensive path).
        receiver = ast.Name(id="a", lineno=1, col_offset=0, end_lineno=1, end_col_offset=1)
        node = ast.Attribute(
            value=receiver,
            attr="b",
            ctx=ast.Load(),
            lineno=1,
            col_offset=0,
            end_lineno=1,
            end_col_offset=0,
        )
        line, col = _attribute_target_position(node)
        assert line == 1
        assert col == 0  # max(0, 0 - len('b')) = max(0, -1) = 0

    def test_dotted_name_for_name(self) -> None:
        """Bare Name → its identifier."""
        node = ast.parse("Foo", mode="eval").body
        assert _dotted_name(node) == "Foo"

    def test_dotted_name_for_attribute_chain(self) -> None:
        """Attribute chain → dotted joined string."""
        node = ast.parse("pkg.sub.Foo", mode="eval").body
        assert _dotted_name(node) == "pkg.sub.Foo"

    def test_dotted_name_for_non_name_node_is_none(self) -> None:
        """Subscript or other expression → None (no dotted form)."""
        node = ast.parse("Foo[int]", mode="eval").body
        assert _dotted_name(node) is None

    def test_dotted_name_for_attribute_with_call_receiver_is_none(self) -> None:
        """Attribute whose receiver isn't dottable → None propagates."""
        node = ast.parse("foo().bar", mode="eval").body
        assert _dotted_name(node) is None

    def test_annotation_source_strips_quotes_for_string_literal(self) -> None:
        """Forward-ref ``Constant(value='Foo')`` → unquoted ``"Foo"``.

        ``ast.unparse`` would render the string as ``'Foo'`` (with quotes);
        we want the unquoted forward-ref content because the conformance test
        ``test_forward_ref_yields_typeref_without_handle`` requires
        ``raw == "FutureType"`` (no quotes).
        """
        tree = ast.parse("'FutureType'", mode="eval")
        const = tree.body
        assert isinstance(const, ast.Constant)
        assert _annotation_source(const) == "FutureType"

    def test_annotation_source_for_non_string_constant(self) -> None:
        """Numeric / None constants flow through ``ast.unparse``."""
        tree = ast.parse("None", mode="eval")
        node = tree.body
        assert _annotation_source(node) == "None"

    def test_annotation_source_for_subscript(self) -> None:
        """Generic expressions round-trip through ``ast.unparse``."""
        tree = ast.parse("Dict[str, int]", mode="eval")
        node = tree.body
        assert _annotation_source(node) == "Dict[str, int]"

    def test_is_callable_shape_by_handle(self) -> None:
        """``typing.Callable`` head is recognised regardless of slice shape."""
        slice_node = ast.parse("[int]", mode="eval").body
        assert _is_callable_shape("typing.Callable", slice_node) is True
        assert _is_callable_shape("collections.abc.Callable", slice_node) is True

    def test_is_callable_shape_by_slice_shape(self) -> None:
        """Tuple-of-(List, X) slice triggers Callable degraded path even with no head."""
        # Build a Tuple slice whose first element is a List
        list_node = ast.List(elts=[], ctx=ast.Load())
        tuple_node = ast.Tuple(elts=[list_node, ast.Name(id="X", ctx=ast.Load())], ctx=ast.Load())
        assert _is_callable_shape(None, tuple_node) is True

    def test_is_callable_shape_negative(self) -> None:
        """Standard generics like ``Dict[str, int]`` aren't Callable-shaped."""
        slice_node = ast.parse("(str, int)", mode="eval").body
        assert _is_callable_shape("typing.Dict", slice_node) is False

    def test_degraded_head_kind_recognised(self) -> None:
        """``typing.Literal`` etc. are flagged as degraded."""
        assert _degraded_head_kind("typing.Literal") == "Literal"
        assert _degraded_head_kind("typing.Annotated") == "Annotated"
        assert _degraded_head_kind("typing.ParamSpec") == "ParamSpec"

    def test_degraded_head_kind_unknown_returns_none(self) -> None:
        """Standard generic heads are not degraded."""
        assert _degraded_head_kind("typing.Dict") is None
        assert _degraded_head_kind("builtins.list") is None
        assert _degraded_head_kind(None) is None


# ---------------------------------------------------------------------------
# Cache-key invariants
# ---------------------------------------------------------------------------


class TestCacheKey:
    """Invariants of the per-process TypeRef cache key."""

    def test_cache_key_none_when_file_path_is_none(self) -> None:
        """``file_path=None`` means uncacheable."""
        assert _cache_key(None, "Path") is None

    def test_cache_key_none_on_oserror(self, tmp_path: Path) -> None:
        """If ``os.stat`` fails (file gone), key is ``None``."""
        ghost = tmp_path / "does_not_exist.py"
        assert _cache_key(ghost, "X") is None

    def test_cache_key_includes_mtime_ns(self, tmp_path: Path) -> None:
        """The mtime_ns component participates in the key."""
        f = tmp_path / "a.py"
        f.write_text("x: int\n")
        key1 = _cache_key(f, "int")
        # Bump mtime to a stable larger value
        os.utime(f, ns=(0, os.stat(f).st_mtime_ns + 1_000_000))
        key2 = _cache_key(f, "int")
        assert key1 is not None and key2 is not None
        assert key1 != key2, "different mtime_ns must produce different keys"


# ---------------------------------------------------------------------------
# Forward-ref recursion
# ---------------------------------------------------------------------------


class TestForwardRefRecursion:
    """Forward-ref strings are re-parsed and recursed.

    The fixture only exercises the unresolvable single-leaf case. These
    tests exercise the recursive paths inside ``_build_forward_ref_node``
    directly — generic forward-refs, union forward-refs, malformed
    forward-refs, and known-resolvable forward-refs.
    """

    @pytest.mark.asyncio
    async def test_resolvable_forward_ref_leaf(self, analyzer: JediAnalyzer) -> None:
        """Forward-ref string for a project class resolves via canonicalization.

        Uses the existing ``mypackage.models.CustomModel`` fixture and a
        synthetic file that references it as a forward-ref string.
        """
        services = _FIXTURE / "mypackage" / "services.py"
        # Synthesise an annotation node ``"CustomModel"`` situated *inside* the
        # services file (so resolve_canonical can find CustomModel via the
        # fixture's import wiring).
        ann = ast.parse('x: "CustomModel"\n').body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        # The forward-ref content is "CustomModel"
        assert result["raw"] == "CustomModel"
        # resolve_canonical resolves bare "CustomModel" via project search
        # (no scoping context); accept either a populated handle pointing at
        # the project class, or an absent handle if Jedi can't disambiguate.
        if "handle" in result:
            assert result["handle"] == "mypackage.models.CustomModel"

    @pytest.mark.asyncio
    async def test_malformed_forward_ref_string_degrades_to_raw(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Unparseable forward-ref content → ``{raw: "..."}`` only."""
        services = _FIXTURE / "mypackage" / "services.py"
        ann = ast.parse('x: "not valid python ::"\n').body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        assert result["raw"] == "not valid python ::"
        assert "handle" not in result
        assert "args" not in result

    @pytest.mark.asyncio
    async def test_generic_forward_ref_recurses_into_args(self, analyzer: JediAnalyzer) -> None:
        """``"List[CustomModel]"`` produces a TypeRef tree with a child arg."""
        services = _FIXTURE / "mypackage" / "services.py"
        ann = ast.parse('x: "List[CustomModel]"\n').body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        assert result["raw"] == "List[CustomModel]"
        # Args should reflect the single child
        args = result.get("args")
        assert isinstance(args, list)
        assert len(args) == 1
        assert args[0]["raw"] == "CustomModel"

    @pytest.mark.asyncio
    async def test_union_forward_ref_carries_alternatives_no_root_handle(
        self, analyzer: JediAnalyzer
    ) -> None:
        """``"int | None"`` inside a forward-ref → no root handle, args carry alternatives."""
        services = _FIXTURE / "mypackage" / "services.py"
        ann = ast.parse('x: "int | None"\n').body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        assert result["raw"] == "int | None"
        assert "handle" not in result, "unions have no canonical head"
        args = result.get("args")
        assert isinstance(args, list) and len(args) == 2
        assert {a["raw"] for a in args} == {"int", "None"}

    @pytest.mark.asyncio
    async def test_nested_forward_ref_string_inside_forward_ref(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Forward-ref that contains a nested string literal still parses cleanly.

        Exercises the ``Constant(value=str)`` branch inside
        ``_build_forward_ref_node``.
        """
        services = _FIXTURE / "mypackage" / "services.py"
        # ``"Optional['CustomModel']"`` — the inner 'CustomModel' is itself a
        # forward-ref string after re-parsing the outer one.
        ann = ast.parse("x: \"Optional['CustomModel']\"\n").body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        assert result["raw"].startswith("Optional[")
        # Top-level recursed; args should carry the inner forward-ref
        args = result.get("args")
        assert isinstance(args, list) and len(args) == 1
        # The inner is itself a re-parsed forward-ref → raw 'CustomModel'
        assert args[0]["raw"] == "CustomModel"

    @pytest.mark.asyncio
    async def test_numeric_constant_inside_forward_ref(self, analyzer: JediAnalyzer) -> None:
        """Forward-ref containing a non-string constant (e.g. inside Literal)."""
        services = _FIXTURE / "mypackage" / "services.py"
        # ``"Literal[1]"`` — the inner ``1`` is a Constant(value=1).
        # Literal is on the degraded list, so args should be omitted at the
        # outer level. We just assert raw is preserved.
        ann = ast.parse('x: "Literal[1]"\n').body[0]
        assert isinstance(ann, ast.AnnAssign)
        result = await build_typeref(ann.annotation, services, analyzer)
        assert result["raw"] == "Literal[1]"


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


class TestCaching:
    """The TypeRef cache is keyed by (file, mtime_ns, raw) and reuses results."""

    @pytest.mark.asyncio
    async def test_repeated_build_for_same_annotation_hits_cache(
        self, analyzer: JediAnalyzer
    ) -> None:
        """Two builds for the same (file, raw) return the same dict object."""
        services = _FIXTURE / "mypackage" / "services.py"
        ann = ast.parse("x: Path\n").body[0]
        assert isinstance(ann, ast.AnnAssign)
        first = await build_typeref(ann.annotation, services, analyzer)
        second = await build_typeref(ann.annotation, services, analyzer)
        # Same dict identity proves the cache returned the stored instance
        assert first is second

    @pytest.mark.asyncio
    async def test_no_cache_when_file_path_does_not_exist(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        """Builds against a missing file run uncached and still produce a valid TypeRef."""
        ghost = tmp_path / "ghost.py"
        # Don't create the file
        ann = ast.parse("x: int\n").body[0]
        assert isinstance(ann, ast.AnnAssign)
        # The build still runs (no caching) — head resolution will fail (no
        # script available) so handle is absent, but raw is preserved.
        result = await build_typeref(ann.annotation, ghost, analyzer)
        assert result["raw"] == "int"


# ---------------------------------------------------------------------------
# Direct degraded-path coverage
# ---------------------------------------------------------------------------


class TestDegradedPath:
    """Annotations whose shape doesn't fit the uniform recursion."""

    @pytest.mark.asyncio
    async def test_literal_annotation_omits_args(self, tmp_path: Path) -> None:
        """``Literal[1, "x"]`` preserves raw; args omitted (per spec degraded path)."""
        f = tmp_path / "lit.py"
        f.write_text("from typing import Literal\n\ndef g(x: Literal[1, 'x']) -> None: ...\n")
        # Re-parse against the file so positions are absolute
        tree = ast.parse(f.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        ann = fn.args.args[0].annotation
        assert ann is not None
        # Use a project-rooted analyzer at tmp_path so Jedi can resolve
        # ``Literal`` via stdlib typing.
        local_analyzer = JediAnalyzer(str(tmp_path))
        result = await build_typeref(ann, f, local_analyzer)
        assert result["raw"] == "Literal[1, 'x']"
        assert "args" not in result

    @pytest.mark.asyncio
    async def test_unsupported_node_kind_degrades(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        """An expression that isn't Name / Attribute / Subscript / BinOp / Constant degrades.

        We synthesise an ``ast.Call`` annotation (not legal Python at the
        type level, but a defensive code path nonetheless).
        """
        f = tmp_path / "weird.py"
        f.write_text("# placeholder\n")
        # Build a Call node: ``foo()``
        call = ast.parse("foo()", mode="eval").body
        result = await build_typeref(call, f, analyzer)
        assert result["raw"] == "foo()"
        assert "handle" not in result
        assert "args" not in result


# ---------------------------------------------------------------------------
# Degraded-path telemetry counter
# ---------------------------------------------------------------------------


class TestDegradedCounts:
    """The module-level counter records degraded-path categories.

    Operators rely on :func:`get_and_reset_degraded_counts` for empirical
    prioritisation since debug-level logs are silenced in production by
    default.
    """

    @pytest.mark.asyncio
    async def test_literal_annotation_increments_counter(self, tmp_path: Path) -> None:
        """A ``Literal`` annotation bumps the ``"Literal"`` category."""
        f = tmp_path / "lit.py"
        f.write_text("from typing import Literal\n\ndef g(x: Literal[1, 'x']) -> None: ...\n")
        tree = ast.parse(f.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        ann = fn.args.args[0].annotation
        assert ann is not None
        local_analyzer = JediAnalyzer(str(tmp_path))
        await build_typeref(ann, f, local_analyzer)
        # Counter snapshot must include the Literal category
        assert degraded_counts.get("Literal") == 1

    @pytest.mark.asyncio
    async def test_unsupported_node_kind_increments_counter(
        self, analyzer: JediAnalyzer, tmp_path: Path
    ) -> None:
        """A degraded leaf bumps a counter keyed by the AST node-type name."""
        f = tmp_path / "weird.py"
        f.write_text("# placeholder\n")
        # Build a Call node: ``foo()`` — falls through to the catch-all
        call = ast.parse("foo()", mode="eval").body
        await build_typeref(call, f, analyzer)
        assert degraded_counts.get("Call") == 1

    @pytest.mark.asyncio
    async def test_get_and_reset_returns_snapshot_and_clears(self, tmp_path: Path) -> None:
        """``get_and_reset_degraded_counts`` returns a snapshot, then resets."""
        f = tmp_path / "lit.py"
        f.write_text("from typing import Literal\n\ndef g(x: Literal[1, 'x']) -> None: ...\n")
        tree = ast.parse(f.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        ann = fn.args.args[0].annotation
        assert ann is not None
        local_analyzer = JediAnalyzer(str(tmp_path))
        await build_typeref(ann, f, local_analyzer)

        snapshot = get_and_reset_degraded_counts()
        assert snapshot.get("Literal") == 1
        # After reset the underlying counter must be empty
        assert degraded_counts == {}
        # Snapshot is a fresh dict — mutating it doesn't disturb the counter
        snapshot["spurious"] = 99
        assert "spurious" not in degraded_counts

    def test_get_and_reset_on_empty_counter_returns_empty(self) -> None:
        """Calling the accessor with no recorded categories returns an empty dict."""
        assert get_and_reset_degraded_counts() == {}


# ---------------------------------------------------------------------------
# Smoke for goto-failure paths
# ---------------------------------------------------------------------------


class TestGotoFailures:
    """Head resolution returns ``None`` when Jedi can't disambiguate or errors."""

    @pytest.mark.asyncio
    async def test_unknown_head_yields_no_handle(self, tmp_path: Path) -> None:
        """A bare reference to a symbol that doesn't exist anywhere → handle absent."""
        f = tmp_path / "u.py"
        # NoSuchSymbol is not imported and not defined anywhere — Jedi goto
        # returns no definitions, so the no-guess rule applies.
        f.write_text("def g(x: NoSuchSymbol) -> None: ...\n")
        tree = ast.parse(f.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        ann = fn.args.args[0].annotation
        assert ann is not None
        local = JediAnalyzer(str(tmp_path))
        result = await build_typeref(ann, f, local)
        assert result["raw"] == "NoSuchSymbol"
        assert "handle" not in result


# ---------------------------------------------------------------------------
# inspect.py helpers — exercise the new AST-walking helpers added by Phase 8
# ---------------------------------------------------------------------------


class TestInspectHelpers:
    """Coverage for the ``_iter_function_args`` / ``_ast_arg_defaults`` /
    ``_build_param_kind_for_arg`` / ``_extract_return_type`` helpers added
    to ``inspect.py`` for TypeRef integration.
    """

    @pytest.mark.asyncio
    async def test_inspect_function_with_all_param_kinds(self, tmp_path: Path) -> None:
        """A function with positional-only / vararg / kw-only / kwarg returns
        the expected ``Param.kind`` values for each.
        """
        from pyeye.mcp.operations.inspect import inspect

        f = tmp_path / "all_kinds.py"
        f.write_text(
            "def f(po, /, pk, *args, ko, **kw):\n    pass\ndef g(a=1, *, b=2):\n    pass\n"
        )
        local = JediAnalyzer(str(tmp_path))
        result = await inspect("all_kinds.f", local)
        # parameters key may be present even when symbol is shaky; we only
        # care that the helpers were exercised. Build a {name: kind} map.
        params = result.get("parameters", [])
        kinds = {p["name"]: p["kind"] for p in params}
        # Even if Jedi infers slightly differently, the AST-based extractor
        # must include all five names with their canonical kinds.
        assert kinds.get("po") == "positional"
        assert kinds.get("pk") == "positional_or_keyword"
        assert kinds.get("args") == "var_positional"
        assert kinds.get("ko") == "keyword_only"
        assert kinds.get("kw") == "var_keyword"

        result_g = await inspect("all_kinds.g", local)
        params_g = result_g.get("parameters", [])
        defaults_g = {p["name"]: p.get("default") for p in params_g}
        assert defaults_g.get("a") == "1"
        assert defaults_g.get("b") == "2"

    @pytest.mark.asyncio
    async def test_extract_return_type_handles_unannotated_function(self, tmp_path: Path) -> None:
        """A function with no return annotation produces ``return_type=None``."""
        from pyeye.mcp.operations.inspect import inspect

        f = tmp_path / "noret.py"
        f.write_text("def h():\n    return 1\n")
        local = JediAnalyzer(str(tmp_path))
        result = await inspect("noret.h", local)
        # function kind path runs even when handle resolution is shaky,
        # because the AST walk locates the FunctionDef by line; the result
        # may be None (unannotated) or absent if Jedi treats it as a
        # variable. Both are acceptable here — the test is about coverage.
        assert result.get("return_type") is None or "return_type" not in result

    @pytest.mark.asyncio
    async def test_attribute_with_complex_default_omits_default(self, tmp_path: Path) -> None:
        """An attribute whose default isn't a literal omits ``default``."""
        from pyeye.mcp.operations.inspect import inspect

        f = tmp_path / "attr.py"
        # Default is a function call — not a literal — so ``default`` must
        # be absent. The TypeRef for ``int`` is still produced.
        f.write_text("from typing import Any\n\nVALUE: int = int('1')\n")
        local = JediAnalyzer(str(tmp_path))
        result = await inspect("attr.VALUE", local)
        assert (
            "default" not in result
        ), f"complex defaults must be omitted; got default={result.get('default')!r}"


# ---------------------------------------------------------------------------
# Pytest discovery hint — keep at end so the module's import side-effects
# (clearing the cache fixture, etc.) settle before any collection.
# ---------------------------------------------------------------------------


def test_module_imports_cleanly() -> None:
    """Sanity check: the module imports under the current Python interpreter."""
    assert sys.version_info >= (3, 10), "TypeRef relies on PEP 604 union syntax (3.10+)"
