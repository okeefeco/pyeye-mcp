"""Tests for the ``expand(handle, edge)`` operation — Tasks 4.1+4.2 (Phase 4).

``expand`` is the user-facing single-hop traversal.  It composes the Phase-2/3
edge resolvers (``members``, ``callees``) and the Phase-1 stub builder into a
**discriminated-union** response (spec §4.2):

Supported edge::

    { "source": str,               # canonical source handle
      "edge": str,
      "stubs": [Stub, ...],        # [] means MEASURED, none found
      "unresolved_call_sites": int  # callees ONLY — ABSENT for members }

Not-supported edge::

    { "source": str,
      "edge": str,
      "unsupported": True,
      "reason": "deferred_reference_backend" | "not_yet_implemented"
                | "unknown_edge",
      "detail": str }

The two branches are MUTUALLY EXCLUSIVE: a supported result NEVER carries
``unsupported`` / ``reason``; an unsupported result NEVER carries ``stubs``.

Critically (the #332 failure): a supported edge with no adjacents returns a
supported result with ``stubs: []`` (measured none) — NOT the unsupported
branch.  Conflating "measured empty" with "not supported" is the bug these tests
pin against.

NO ``cursor`` field appears anywhere in this slice (absent cursor = "complete").

Fixture facts (``tests/fixtures/resolve_project``):
- ``mypackage._core.widgets.Widget`` — a class WITH members (members happy path).
- ``mypackage._core.widgets.make_widget`` — a FUNCTION (no members → empty-vs-
  unsupported pin).
- ``mypackage._core.callees_fixture.orchestrate`` — a function with project +
  stdlib callees AND an unresolvable dynamic call (callees happy path +
  ``unresolved_call_sites``).
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
_MAKE_WIDGET_HANDLE = "mypackage._core.widgets.make_widget"
_ORCHESTRATE_HANDLE = "mypackage._core.callees_fixture.orchestrate"
_MODULE_HANDLE = "mypackage._core.widgets"
_DEFAULT_NAME_HANDLE = "mypackage._core.widgets.DEFAULT_NAME"

#: imported_by fixtures (Phase 4): ``widgets`` is a module imported by several
#: other modules (supported, non-empty); ``module_forms`` is a leaf module that
#: nobody imports (supported, measured ``stubs: []``); ``Widget`` is a CLASS — a
#: non-module handle for which ``imported_by`` does not apply (unsupported).
_MODULE_WITH_IMPORTERS_HANDLE = "mypackage._core.widgets"
_MODULE_NO_IMPORTERS_HANDLE = "mypackage._core.module_forms"

#: subclasses fixtures (#348, Phase 2): a dedicated fixture project with a known
#: direct + indirect + non-importable-file topology. ``Animal`` is the base whose
#: full project subclass closure is exactly {Mammal, Dog, Lizard}; ``Loner`` is a
#: sibling base nobody subclasses (measured-empty class case).
_SUBCLASSES_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_edge"
_ANIMAL_HANDLE = "pkg.base.Animal"
_LONER_HANDLE = "pkg.base.Loner"
_MAMMAL_HANDLE = "pkg.middle.Mammal"  # direct subclass (importable module)
_DOG_HANDLE = "pkg.middle.Dog"  # indirect (grandchild) subclass
_LIZARD_HANDLE = "script_animal.Lizard"  # direct subclass in a non-importable script

#: The Phase-1 Stub keys that are ALWAYS present (spec §4.1; ``signature`` is
#: callable-only and therefore not asserted as universally present).
_STUB_REQUIRED_KEYS = {"handle", "kind", "scope", "line_start", "line_end"}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.fixture
def subclasses_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the dedicated subclasses_edge fixture (#348)."""
    return JediAnalyzer(str(_SUBCLASSES_FIXTURE))


def _assert_is_stub(stub: dict) -> None:
    """Assert *stub* conforms to the Phase-1 §4.1 Stub shape."""
    assert isinstance(stub, dict), f"stub must be a dict, got {type(stub)}"
    missing = _STUB_REQUIRED_KEYS - set(stub)
    assert not missing, f"stub missing required keys {missing}: {stub}"
    assert isinstance(stub["line_start"], int)
    assert isinstance(stub["line_end"], int)
    assert stub["line_end"] >= stub["line_start"]
    # No source content ever leaks through expand.
    for forbidden in ("body", "source", "code", "snippet", "text"):
        assert forbidden not in stub, f"stub leaked source content via {forbidden!r}: {stub}"


# ---------------------------------------------------------------------------
# Task 4.1 — supported happy paths
# ---------------------------------------------------------------------------


class TestExpandMembersSupported:
    """``expand`` over ``members`` returns the supported ExpandResult shape."""

    @pytest.mark.asyncio
    async def test_members_supported_shape(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "members", analyzer)
        # Supported branch — never unsupported.
        assert "unsupported" not in result
        assert "reason" not in result
        # Universal supported keys.
        assert result["edge"] == "members"
        assert isinstance(result["source"], str)
        assert isinstance(result["stubs"], list)

    @pytest.mark.asyncio
    async def test_members_stubs_are_phase1_stubs(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "members", analyzer)
        assert result["stubs"], "Widget should have at least one member stub"
        for stub in result["stubs"]:
            _assert_is_stub(stub)

    @pytest.mark.asyncio
    async def test_members_omits_unresolved_call_sites(self, analyzer: JediAnalyzer) -> None:
        # unresolved_call_sites is callees-specific — it must be ABSENT for members.
        result = await expand(_WIDGET_HANDLE, "members", analyzer)
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_members_no_cursor(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "members", analyzer)
        assert "cursor" not in result


class TestExpandCalleesSupported:
    """``expand`` over ``callees`` returns the supported shape WITH unresolved count."""

    @pytest.mark.asyncio
    async def test_callees_supported_shape(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_ORCHESTRATE_HANDLE, "callees", analyzer)
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "callees"
        assert isinstance(result["stubs"], list)

    @pytest.mark.asyncio
    async def test_callees_stubs_nonempty_and_valid(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_ORCHESTRATE_HANDLE, "callees", analyzer)
        assert result["stubs"], "orchestrate has resolvable callees (make_widget, math.sqrt)"
        # Every callee stub — INCLUDING the external/stdlib math.sqrt — must build.
        # If a callee stub failed to build, that is a real problem (the whole
        # reason we carry the Jedi Name through EdgeResult).
        for stub in result["stubs"]:
            _assert_is_stub(stub)

    @pytest.mark.asyncio
    async def test_callees_includes_external_callee_stub(self, analyzer: JediAnalyzer) -> None:
        # math.sqrt is an external/stdlib callee; its stub must build (scope external).
        result = await expand(_ORCHESTRATE_HANDLE, "callees", analyzer)
        handles = {stub["handle"] for stub in result["stubs"]}
        assert "math.sqrt" in handles, f"external stdlib callee math.sqrt missing; got {handles}"
        assert _MAKE_WIDGET_HANDLE in handles, f"project callee make_widget missing; got {handles}"

    @pytest.mark.asyncio
    async def test_callees_carries_unresolved_call_sites(self, analyzer: JediAnalyzer) -> None:
        # callees-specific field MUST be present and an int >= 1 (the dynamic cb() call).
        result = await expand(_ORCHESTRATE_HANDLE, "callees", analyzer)
        assert "unresolved_call_sites" in result
        assert isinstance(result["unresolved_call_sites"], int)
        assert result["unresolved_call_sites"] >= 1

    @pytest.mark.asyncio
    async def test_callees_no_cursor(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_ORCHESTRATE_HANDLE, "callees", analyzer)
        assert "cursor" not in result


# ---------------------------------------------------------------------------
# Task 4.1 — empty-vs-unsupported (#332 distinction)
# ---------------------------------------------------------------------------


class TestExpandEmptyIsSupported:
    """A container with no members → supported ``stubs: []`` — NOT unsupported."""

    @pytest.mark.asyncio
    async def test_function_members_empty_supported(self, analyzer: JediAnalyzer) -> None:
        # A FUNCTION has no members → measured-empty, NOT unsupported.
        result = await expand(_MAKE_WIDGET_HANDLE, "members", analyzer)
        assert result["stubs"] == [], "a function genuinely has no members → measured []"
        # The load-bearing #332 distinction: empty is supported, not unsupported.
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "members"
        assert "unresolved_call_sites" not in result


class TestExpandUnresolvableSourceGraceful:
    """An unresolvable source handle → graceful supported-empty, never raises.

    Mirrors how ``inspect`` returns a minimal node (rather than raising) when the
    source handle cannot be resolved to a Jedi ``Name``.  For ``expand`` this is
    a supported result with ``stubs: []`` (NOT the unsupported branch), plus
    ``unresolved_call_sites: 0`` for the callees edge.
    """

    _GHOST_HANDLE = "mypackage._core.widgets.does_not_exist_xyz"

    @pytest.mark.asyncio
    async def test_members_unresolvable_source_empty(self, analyzer: JediAnalyzer) -> None:
        result = await expand(self._GHOST_HANDLE, "members", analyzer)
        assert result["stubs"] == []
        assert result["source"] == self._GHOST_HANDLE
        assert result["edge"] == "members"
        # Supported branch — unresolvable is graceful-empty, NOT unsupported.
        assert "unsupported" not in result
        assert "reason" not in result
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_callees_unresolvable_source_empty_with_zero(
        self, analyzer: JediAnalyzer
    ) -> None:
        result = await expand(self._GHOST_HANDLE, "callees", analyzer)
        assert result["stubs"] == []
        assert "unsupported" not in result
        # callees graceful path still carries the callees-only field as 0.
        assert result["unresolved_call_sites"] == 0


# ---------------------------------------------------------------------------
# Task 4.1 — unsupported branches (reason == status)
# ---------------------------------------------------------------------------


class TestExpandUnsupported:
    """Unsupported edges return the unsupported branch with the mapped reason."""

    @pytest.mark.asyncio
    async def test_not_yet_implemented(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "superclasses", analyzer)
        assert result["unsupported"] is True
        assert result["reason"] == "not_yet_implemented"
        assert result["edge"] == "superclasses"
        assert result["source"] == _WIDGET_HANDLE
        assert isinstance(result["detail"], str) and result["detail"]
        # Mutually exclusive: an unsupported result NEVER carries stubs.
        assert "stubs" not in result
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_deferred_reference_backend(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_ORCHESTRATE_HANDLE, "callers", analyzer)
        assert result["unsupported"] is True
        assert result["reason"] == "deferred_reference_backend"
        assert result["edge"] == "callers"
        assert isinstance(result["detail"], str) and result["detail"]
        assert "stubs" not in result

    @pytest.mark.asyncio
    async def test_unknown_edge(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "bogus_edge", analyzer)
        assert result["unsupported"] is True
        assert result["reason"] == "unknown_edge"
        assert result["edge"] == "bogus_edge"
        assert isinstance(result["detail"], str) and result["detail"]
        assert "stubs" not in result

    @pytest.mark.asyncio
    async def test_unsupported_no_cursor(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "bogus_edge", analyzer)
        assert "cursor" not in result


# ---------------------------------------------------------------------------
# Task 4.1 — mutual exclusivity invariant (cross-cutting)
# ---------------------------------------------------------------------------


class TestExpandBranchesMutuallyExclusive:
    """Supported and unsupported branches never co-occur for any edge."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "edge"),
        [
            (_WIDGET_HANDLE, "members"),
            (_ORCHESTRATE_HANDLE, "callees"),
            (_MAKE_WIDGET_HANDLE, "members"),
        ],
    )
    async def test_supported_has_no_unsupported_markers(
        self, analyzer: JediAnalyzer, handle: str, edge: str
    ) -> None:
        result = await expand(handle, edge, analyzer)
        assert "stubs" in result
        assert "unsupported" not in result
        assert "reason" not in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handle", "edge"),
        [
            (_WIDGET_HANDLE, "superclasses"),
            (_ORCHESTRATE_HANDLE, "callers"),
            (_WIDGET_HANDLE, "bogus_edge"),
        ],
    )
    async def test_unsupported_has_no_supported_markers(
        self, analyzer: JediAnalyzer, handle: str, edge: str
    ) -> None:
        result = await expand(handle, edge, analyzer)
        assert result["unsupported"] is True
        assert "stubs" not in result
        assert "unresolved_call_sites" not in result


# ---------------------------------------------------------------------------
# Task 4.1 — imported_by wiring (the three distinct paths, #345/#332)
# ---------------------------------------------------------------------------


class TestExpandImportedBySupported:
    """``expand`` over ``imported_by`` for a MODULE returns the supported shape.

    The resolver (Phase 3 ``resolve_imported_by``) is async and returns an
    ``EdgeResult`` for a module handle.  ``expand`` awaits it and builds a stub
    per importer; every importer stub is a module (``kind == "module"``).  This
    is the callees-free supported branch — ``unresolved_call_sites`` is ABSENT
    (the resolver carries it as ``None`` for this edge).
    """

    @pytest.mark.asyncio
    async def test_module_imported_by_supported_shape(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_MODULE_WITH_IMPORTERS_HANDLE, "imported_by", analyzer)
        # Supported branch — never unsupported.
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "imported_by"
        assert isinstance(result["source"], str)
        assert isinstance(result["stubs"], list)
        # imported_by is an inbound edge, NOT callees — no unresolved_call_sites.
        assert "unresolved_call_sites" not in result
        assert "cursor" not in result

    @pytest.mark.asyncio
    async def test_module_imported_by_stubs_are_module_stubs(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_MODULE_WITH_IMPORTERS_HANDLE, "imported_by", analyzer)
        assert result["stubs"], "widgets module has known importers → non-empty stubs"
        for stub in result["stubs"]:
            _assert_is_stub(stub)
            # Each importer is itself a module.
            assert stub["kind"] == "module", f"importer stub should be a module: {stub}"


class TestExpandImportedByNonModuleUnsupported:
    """A NON-MODULE handle → unsupported ``not_yet_implemented`` (NOT empty).

    The resolver returns ``None`` for a non-module handle (a class/function CAN
    be imported, so claiming ``stubs: []`` would be the #332 "measured zero"
    lie).  ``expand`` must surface that ``None`` as the UNSUPPORTED branch with a
    KIND-SPECIFIC ``detail`` — distinct from the source-not-found graceful-empty
    path and from the module measured-empty path.
    """

    @pytest.mark.asyncio
    async def test_class_imported_by_is_unsupported(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "imported_by", analyzer)
        # Unsupported branch — wrong kind for this edge.
        assert result["unsupported"] is True
        assert result["reason"] == "not_yet_implemented"
        assert result["edge"] == "imported_by"
        # Mutually exclusive: an unsupported result NEVER carries stubs.
        assert "stubs" not in result
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_class_imported_by_detail_names_kind(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_WIDGET_HANDLE, "imported_by", analyzer)
        detail = result["detail"]
        assert isinstance(detail, str) and detail, "detail must be a non-empty str"
        # Kind-specific: Widget is a class, so the detail must name the kind.
        assert "class" in detail, f"detail must name the handle's kind (class): {detail!r}"
        assert "imported_by" in detail, f"detail should name the edge: {detail!r}"


class TestExpandImportedByModuleNoImportersSupported:
    """A MODULE that nobody imports → supported ``stubs: []`` (measured none).

    This pins the #332 distinction at the operation layer: ``module_forms`` IS a
    module (the edge applies), so the resolver returns ``EdgeResult([])`` — a
    MEASURED empty — and ``expand`` returns the SUPPORTED branch with
    ``stubs: []``.  This is DISTINCT from the non-module unsupported branch.
    """

    @pytest.mark.asyncio
    async def test_module_no_importers_is_supported_empty(self, analyzer: JediAnalyzer) -> None:
        result = await expand(_MODULE_NO_IMPORTERS_HANDLE, "imported_by", analyzer)
        assert result["stubs"] == [], "module_forms is imported by nobody → measured []"
        # Supported branch — measured-empty is NOT unsupported (the #332 line).
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "imported_by"
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_no_importers_distinct_from_non_module(self, analyzer: JediAnalyzer) -> None:
        # The crux of #332: module-with-no-importers (supported empty) and
        # non-module (unsupported) must be DIFFERENT shapes.
        empty_module = await expand(_MODULE_NO_IMPORTERS_HANDLE, "imported_by", analyzer)
        non_module = await expand(_WIDGET_HANDLE, "imported_by", analyzer)
        assert "unsupported" not in empty_module
        assert non_module["unsupported"] is True
        # And they are genuinely different shapes (stubs vs reason).
        assert "stubs" in empty_module and "stubs" not in non_module
        assert "reason" not in empty_module and "reason" in non_module


# ---------------------------------------------------------------------------
# Task 2.1 — subclasses wiring (#348): wrong-kind → measured-empty, never None
# ---------------------------------------------------------------------------


class TestExpandSubclassesSupported:
    """``expand`` over ``subclasses`` for a CLASS returns the supported shape.

    The resolver (``resolve_subclasses``) is async and returns an ``EdgeResult``
    of canonical CLASS handles for the full project subclass closure (direct +
    indirect, including subclasses defined in non-importable root scripts).
    ``expand`` awaits it and builds a class stub per subclass.  This is a
    callees-free supported branch — ``unresolved_call_sites`` is ABSENT (the
    resolver carries it as ``None`` for this edge).
    """

    @pytest.mark.asyncio
    async def test_class_subclasses_supported_shape(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
        # Supported branch — never unsupported.
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "subclasses"
        assert isinstance(result["source"], str)
        assert isinstance(result["stubs"], list)
        assert "cursor" not in result

    @pytest.mark.asyncio
    async def test_class_subclasses_stubs_are_class_stubs(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
        assert result["stubs"], "Animal has known project subclasses → non-empty stubs"
        for stub in result["stubs"]:
            _assert_is_stub(stub)
            # Each adjacent is itself a class.
            assert stub["kind"] == "class", f"subclass stub should be a class: {stub}"

    @pytest.mark.asyncio
    async def test_class_subclasses_full_closure_present(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # include_indirect=True → the full project subclass closure: the direct
        # subclass (Mammal), the indirect grandchild (Dog), AND the subclass in a
        # non-importable root script (Lizard, preserved by file-based stub build).
        result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
        handles = {stub["handle"] for stub in result["stubs"]}
        assert handles == {_MAMMAL_HANDLE, _DOG_HANDLE, _LIZARD_HANDLE}, f"got {handles}"

    @pytest.mark.asyncio
    async def test_class_subclasses_omits_unresolved_call_sites(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # unresolved_call_sites is callees-specific — it must be ABSENT for the
        # subclasses edge (the resolver carries it as None).
        result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
        assert "unresolved_call_sites" not in result


class TestExpandSubclassesClassNoSubclassesSupported:
    """A CLASS with no project subclasses → supported ``stubs: []`` (measured none).

    ``Loner`` IS a class (the edge applies), so the resolver returns a MEASURED
    empty ``EdgeResult([])`` and ``expand`` returns the SUPPORTED branch with
    ``stubs: []`` — NOT the unsupported branch.
    """

    @pytest.mark.asyncio
    async def test_class_no_subclasses_is_supported_empty(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        result = await expand(_LONER_HANDLE, "subclasses", subclasses_analyzer)
        assert result["stubs"] == [], "Loner is subclassed by nobody → measured []"
        assert "unsupported" not in result
        assert "reason" not in result
        assert result["edge"] == "subclasses"
        assert "unresolved_call_sites" not in result


class TestExpandSubclassesNonClassMeasuredEmpty:
    """A NON-CLASS handle → SUPPORTED ``stubs: []`` — NOT the unsupported branch.

    This is the DEFINING behavior of the slice (decision 1): only a class CAN be
    subclassed, so ``[]`` for a function/variable/module is true BY DEFINITION —
    exactly the ``members``/``callees`` measured-empty route, NOT the
    ``imported_by`` ``None``/``not_yet_implemented`` route.  ``resolve_subclasses``
    returns ``EdgeResult([])`` (never ``None``) for the wrong kind, so ``expand``
    lands on the supported branch and needs NO change.  The explicit "no
    ``unsupported``, no ``reason``" assertions are what prove the resolver did not
    regress to the ``None`` path.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handle",
        [_MAKE_WIDGET_HANDLE, _DEFAULT_NAME_HANDLE, _MODULE_HANDLE],
        ids=["function", "variable", "module"],
    )
    async def test_non_class_is_supported_measured_empty(
        self, analyzer: JediAnalyzer, handle: str
    ) -> None:
        result = await expand(handle, "subclasses", analyzer)
        # Measured-empty: stubs present and empty.
        assert result["stubs"] == [], f"non-class {handle!r} → measured [] subclasses"
        assert result["edge"] == "subclasses"
        # The crux: this is the SUPPORTED branch, explicitly NOT the unsupported
        # branch (which is what the imported_by None path would have produced).
        assert (
            "unsupported" not in result
        ), f"non-class subclasses must NOT be unsupported: {result}"
        assert "reason" not in result, f"non-class subclasses must NOT carry a reason: {result}"
        # subclasses never reports unresolved_call_sites (callees-only).
        assert "unresolved_call_sites" not in result

    @pytest.mark.asyncio
    async def test_non_class_distinct_from_imported_by_non_module(
        self, analyzer: JediAnalyzer
    ) -> None:
        # Contrast with imported_by: a non-module imported_by IS unsupported
        # (None path), but a non-class subclasses is SUPPORTED measured-empty.
        # This pins that the two wrong-kind designs are genuinely different.
        subclasses_wrong_kind = await expand(_MAKE_WIDGET_HANDLE, "subclasses", analyzer)
        imported_by_wrong_kind = await expand(_WIDGET_HANDLE, "imported_by", analyzer)
        assert "unsupported" not in subclasses_wrong_kind
        assert "stubs" in subclasses_wrong_kind
        assert imported_by_wrong_kind["unsupported"] is True
        assert "stubs" not in imported_by_wrong_kind


class TestExpandSubclassesCountListConsistency:
    """Progressive-disclosure contract: len(stubs) == inspect.edge_counts.subclasses.

    The resolver and ``inspect._count_subclasses`` share the EXACT call shape
    (``scope="main"``, ``include_indirect=True``, ``show_hierarchy=False``), so
    the number of subclass stubs ``expand`` produces MUST equal the count
    ``inspect`` reports for the same class.  This is the contract that justifies
    the shared call shape; if it diverges, the resolver's enumeration or dedup
    has drifted from ``find_subclasses``' result list (reconcile, don't relax).
    """

    @pytest.mark.asyncio
    async def test_expand_len_equals_inspect_count(self, subclasses_analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.inspect import inspect

        expand_result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
        inspect_result = await inspect(_ANIMAL_HANDLE, subclasses_analyzer)

        stub_count = len(expand_result["stubs"])
        edge_count = inspect_result["edge_counts"]["subclasses"]
        assert stub_count == edge_count, (
            f"len(expand subclasses stubs)={stub_count} must equal "
            f"inspect edge_counts['subclasses']={edge_count} (shared call shape)"
        )
        # The fixture's known closure is exactly 3 (Mammal, Dog, Lizard); pin it
        # so a fixture-topology change can't silently make this a 0==0 tautology.
        assert stub_count == 3, f"fixture Animal closure should be 3 subclasses; got {stub_count}"

    @pytest.mark.asyncio
    async def test_no_subclasses_consistency_holds_at_zero(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # The contract also holds for the measured-empty class case: 0 == 0.
        from pyeye.mcp.operations.inspect import inspect

        expand_result = await expand(_LONER_HANDLE, "subclasses", subclasses_analyzer)
        inspect_result = await inspect(_LONER_HANDLE, subclasses_analyzer)
        assert len(expand_result["stubs"]) == inspect_result["edge_counts"]["subclasses"] == 0
