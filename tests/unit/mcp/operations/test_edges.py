"""Tests for the edge-resolver registry and ``members`` resolver — Tasks 2.1+2.2.

The edge registry is the single source of truth for which edges ``expand``
supports.  Every edge name MUST classify into exactly one status:

- ``"implemented"`` — ``members``, ``callees``
- ``"not_yet_implemented"`` — ``superclasses``, ``subclasses``, ``imports``,
  ``enclosing_scope``
- ``"deferred_reference_backend"`` — the inbound / reference edges
  (``callers``, ``references``, ``read_by``, ``written_by``, ``passed_by``,
  ``imported_by``, ``overrides``, ``overridden_by``, ``decorated_by``,
  ``decorates``)
- ``"unknown_edge"`` — any unrecognised name

The status string values ARE the ``reason`` strings ``expand`` emits, so the
four cases must be machine-distinguishable.

The ``members`` resolver returns the adjacent canonical handles for a container:

- class → direct methods / nested classes / class-level attributes (no inherited)
- module → top-level definitions enumerated via Jedi ``get_names(all_scopes=False)``
  MINUS names bound by top-level import statements (spec §3.3).  The ONLY
  divergence from the legacy ``inspect._count_module_members`` count is import
  exclusion — tuple-unpacking, annotated vars, guarded defs, etc. are all included.
- non-container → ``[]`` (measured: genuinely no members)

Fixture facts (``mypackage/_core/widgets.py``):
- imports ``ClassVar`` (``from typing import ClassVar``) — must NOT appear in
  module members
- defines (top level): ``DEFAULT_NAME`` (var), ``Widget`` (class),
  ``Config`` (class), ``make_widget`` (function), ``Premium`` (class),
  ``Deluxe`` (class) → module members MUST be exactly those 6.

Fixture ``mypackage/_core/module_forms.py`` exercises the forms that the old
AST hand-walk MISSED (spec §3.3 gap closure):
- ``ALPHA, BETA = 1, 2``  ← tuple-unpacking (missed by old walk)
- ``GAMMA: Final[int] = 3``  ← annotated var (covered by both old and new)
- ``some_function``, ``SomeClass``  ← normal def/class
- ``from typing import Final``  ← import (must be EXCLUDED)
"""

from pathlib import Path
from unittest.mock import Mock, patch

import jedi
import pytest

from pyeye._module_sentinel import ModuleSentinel
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.handle import Handle
from pyeye.mcp.operations.edges import (
    EdgeResult,
    edge_status,
    resolve_callees,
    resolve_imported_by,
    resolve_members,
    resolve_subclasses,
)
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

_WIDGET_HANDLE = "mypackage._core.widgets.Widget"
_CONFIG_HANDLE = "mypackage._core.widgets.Config"
_MODULE_HANDLE = "mypackage._core.widgets"
_MAKE_WIDGET_HANDLE = "mypackage._core.widgets.make_widget"

_MODULE_FORMS_HANDLE = "mypackage._core.module_forms"

_CALLEES_MODULE_HANDLE = "mypackage._core.callees_fixture"
_ORCHESTRATE_HANDLE = "mypackage._core.callees_fixture.orchestrate"
_PROCESSOR_RUN_HANDLE = "mypackage._core.callees_fixture.Processor.run"

# imported_by fixtures: ``widgets`` is imported by several mypackage modules
# AND by the non-package ``script_importer`` (a standalone script at the
# fixture root). ``module_forms`` is a leaf module that nobody imports.
_SCRIPT_IMPORTER_HANDLE = "script_importer"
_DIRECT_IMPORTER_HANDLE = "mypackage._core.direct_importer"
_REL_IMPORTER_HANDLE = "mypackage._core.rel_importer"
_USAGE_IMPORTER_HANDLE = "mypackage.usage"

# subclasses fixtures (issue #348): a dedicated fixture project with a known
# direct + indirect + non-importable-file topology. ``Animal`` is the base under
# test; ``Loner`` is a sibling base nobody subclasses (measured-empty case).
_SUBCLASSES_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_edge"
_ANIMAL_HANDLE = "pkg.base.Animal"
_LONER_HANDLE = "pkg.base.Loner"
_MAMMAL_HANDLE = "pkg.middle.Mammal"  # direct subclass (importable module)
_DOG_HANDLE = "pkg.middle.Dog"  # indirect (grandchild) subclass
_LIZARD_HANDLE = "script_animal.Lizard"  # direct subclass in a non-importable script


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


def _members_for(handle: str, analyzer: JediAnalyzer) -> list[Handle]:
    """Resolve *handle* to a Jedi name and return its member handles.

    ``resolve_members`` now returns an :class:`EdgeResult`; the member tests
    operate on the ``.handles`` list (its ``unresolved_call_sites`` is always
    ``None`` for the members edge — that notion is callees-only).
    """
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    result = resolve_members(jedi_name, analyzer)
    assert result.unresolved_call_sites is None, "members never reports call-site counts"
    return result.handles


def _callees_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult:
    """Resolve *handle* to a Jedi name and return its callees ``EdgeResult``."""
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return resolve_callees(jedi_name, analyzer)


# ---------------------------------------------------------------------------
# Task 2.1 — status model
# ---------------------------------------------------------------------------


class TestEdgeStatusModel:
    """The four-way classification matrix is the single source of edge support."""

    def test_members_is_implemented(self) -> None:
        assert edge_status("members") == "implemented"

    def test_callees_is_implemented(self) -> None:
        # callees is classified implemented even though its resolver lands in
        # Phase 3 — status and resolver-registry are deliberately separate.
        assert edge_status("callees") == "implemented"

    @pytest.mark.parametrize(
        "edge",
        ["superclasses", "imports", "enclosing_scope"],
    )
    def test_not_yet_implemented_edges(self, edge: str) -> None:
        assert edge_status(edge) == "not_yet_implemented"

    def test_imported_by_is_implemented(self) -> None:
        # imported_by moves from deferred_reference_backend to implemented in
        # Phase 3: its resolver (resolve_imported_by) builds on the pure-AST
        # find_importers scan — no indexed reference backend needed.
        assert edge_status("imported_by") == "implemented"

    def test_subclasses_is_implemented(self) -> None:
        # subclasses moves from not_yet_implemented to implemented (#348): its
        # resolver (resolve_subclasses) reuses the forward-only AST class-graph
        # walk in find_subclasses — no reverse symbol search, so it belongs with
        # members/callees/imported_by.
        assert edge_status("subclasses") == "implemented"

    @pytest.mark.parametrize(
        "edge",
        [
            "callers",
            "references",
            "read_by",
            "written_by",
            "passed_by",
            "overrides",
            "overridden_by",
            "decorated_by",
            "decorates",
        ],
    )
    def test_deferred_reference_backend_edges(self, edge: str) -> None:
        assert edge_status(edge) == "deferred_reference_backend"

    @pytest.mark.parametrize("edge", ["no_such_edge", "", "Members", "MEMBERS", "foo.bar"])
    def test_unknown_edge(self, edge: str) -> None:
        assert edge_status(edge) == "unknown_edge"

    def test_every_status_value_is_one_of_four(self) -> None:
        # The status value strings ARE the reason strings expand emits; they
        # must be machine-distinguishable and limited to the four cases.
        allowed = {
            "implemented",
            "not_yet_implemented",
            "deferred_reference_backend",
            "unknown_edge",
        }
        for edge in (
            "members",
            "callees",
            "superclasses",
            "subclasses",
            "imports",
            "enclosing_scope",
            "callers",
            "references",
            "read_by",
            "written_by",
            "passed_by",
            "imported_by",
            "overrides",
            "overridden_by",
            "decorated_by",
            "decorates",
            "nonsense",
        ):
            assert edge_status(edge) in allowed


# ---------------------------------------------------------------------------
# Task 2.1/2.2 — members resolver: class container
# ---------------------------------------------------------------------------


class TestResolveMembersClass:
    """Class members = direct methods / nested classes / attributes (no inherited)."""

    def test_widget_direct_members_present(self, analyzer: JediAnalyzer) -> None:
        members = {str(h) for h in _members_for(_WIDGET_HANDLE, analyzer)}
        # Known direct members of Widget.
        expected_present = {
            f"{_WIDGET_HANDLE}.greet",
            f"{_WIDGET_HANDLE}.slow_greet",
            f"{_WIDGET_HANDLE}.default",
            f"{_WIDGET_HANDLE}.normalize",
            f"{_WIDGET_HANDLE}.display_name",
            f"{_WIDGET_HANDLE}.color",
        }
        missing = expected_present - members
        assert not missing, f"expected direct members missing: {missing}"

    def test_members_are_handles(self, analyzer: JediAnalyzer) -> None:
        members = _members_for(_WIDGET_HANDLE, analyzer)
        assert members, "Widget should have members"
        assert all(isinstance(h, Handle) for h in members)

    def test_excludes_members_of_other_class(self, analyzer: JediAnalyzer) -> None:
        members = {str(h) for h in _members_for(_WIDGET_HANDLE, analyzer)}
        # Config.host belongs to a DIFFERENT class — must not appear.
        assert f"{_CONFIG_HANDLE}.host" not in members
        assert f"{_CONFIG_HANDLE}.debug" not in members

    def test_depth_check_excludes_deeper_symbols(self, analyzer: JediAnalyzer) -> None:
        members = {str(h) for h in _members_for(_WIDGET_HANDLE, analyzer)}
        # Direct-only: a parameter / local of a method is deeper than depth+1
        # and must NOT appear (e.g. Widget.greet.<anything>).
        deeper = {m for m in members if m.startswith(f"{_WIDGET_HANDLE}.greet.")}
        assert not deeper, f"deeper-than-direct members leaked: {deeper}"
        # Every member is exactly one component deeper than the class handle.
        depth = len(_WIDGET_HANDLE.split("."))
        for m in members:
            assert len(m.split(".")) == depth + 1, f"non-direct member: {m}"


# ---------------------------------------------------------------------------
# Task 2.1/2.2 — members resolver: module container
# ---------------------------------------------------------------------------


class TestResolveMembersModule:
    """Module members = top-level DEFINED classes/functions/variables (imports excluded)."""

    def test_module_members_exact_set(self, analyzer: JediAnalyzer) -> None:
        members = {str(h) for h in _members_for(_MODULE_HANDLE, analyzer)}
        expected = {
            f"{_MODULE_HANDLE}.DEFAULT_NAME",
            f"{_MODULE_HANDLE}.Widget",
            f"{_MODULE_HANDLE}.Config",
            f"{_MODULE_HANDLE}.make_widget",
            f"{_MODULE_HANDLE}.Premium",
            f"{_MODULE_HANDLE}.Deluxe",
        }
        assert members == expected

    def test_module_members_exclude_imports(self, analyzer: JediAnalyzer) -> None:
        # ClassVar is imported (`from typing import ClassVar`) and appears in the
        # module's top-level get_names — it MUST be excluded so `members` stays
        # disjoint from the `imports` edge.
        members = {str(h) for h in _members_for(_MODULE_HANDLE, analyzer)}
        assert f"{_MODULE_HANDLE}.ClassVar" not in members
        assert not any(m.endswith(".ClassVar") for m in members)

    def test_module_members_are_handles(self, analyzer: JediAnalyzer) -> None:
        members = _members_for(_MODULE_HANDLE, analyzer)
        assert members
        assert all(isinstance(h, Handle) for h in members)


# ---------------------------------------------------------------------------
# Task 2.1/2.2 — members resolver: non-container
# ---------------------------------------------------------------------------


class TestResolveMembersNonContainer:
    """A non-container (function/method/variable/...) has empty members."""

    def test_function_has_no_members(self, analyzer: JediAnalyzer) -> None:
        members = _members_for(_MAKE_WIDGET_HANDLE, analyzer)
        assert members == []


# ---------------------------------------------------------------------------
# Spec §3.3 gap-closure — module_forms fixture
# ---------------------------------------------------------------------------


class TestResolveMembersModuleForms:
    """Module members via Jedi get_names includes all definition forms (spec §3.3).

    Verifies that the fixed ``_module_members`` implementation — which uses Jedi
    ``get_names(all_scopes=False)`` minus import-bound names — captures forms
    that the old AST hand-walk silently missed:

    - tuple-unpacking assignment (``ALPHA, BETA = 1, 2``)
    - annotated variable (``GAMMA: Final[int] = 3``)
    - normal def/class (sanity)

    Also verifies that the imported name (``Final`` from ``typing``) is
    excluded, so import-exclusion is preserved for this fixture too.
    """

    def test_tuple_unpacked_names_present(self, analyzer: JediAnalyzer) -> None:
        """ALPHA and BETA from ``ALPHA, BETA = 1, 2`` must appear in members."""
        members = {str(h) for h in _members_for(_MODULE_FORMS_HANDLE, analyzer)}
        assert (
            f"{_MODULE_FORMS_HANDLE}.ALPHA" in members
        ), "ALPHA (tuple-unpacking) should be a module member"
        assert (
            f"{_MODULE_FORMS_HANDLE}.BETA" in members
        ), "BETA (tuple-unpacking) should be a module member"

    def test_annotated_var_present(self, analyzer: JediAnalyzer) -> None:
        """GAMMA (annotated assignment) must appear in members."""
        members = {str(h) for h in _members_for(_MODULE_FORMS_HANDLE, analyzer)}
        assert (
            f"{_MODULE_FORMS_HANDLE}.GAMMA" in members
        ), "GAMMA (annotated assignment) should be a module member"

    def test_def_and_class_present(self, analyzer: JediAnalyzer) -> None:
        """Normal function and class definitions must appear in members."""
        members = {str(h) for h in _members_for(_MODULE_FORMS_HANDLE, analyzer)}
        assert (
            f"{_MODULE_FORMS_HANDLE}.some_function" in members
        ), "some_function (def) should be a module member"
        assert (
            f"{_MODULE_FORMS_HANDLE}.SomeClass" in members
        ), "SomeClass (class) should be a module member"

    def test_import_excluded(self, analyzer: JediAnalyzer) -> None:
        """``Final`` (imported from typing) must NOT appear in members."""
        members = {str(h) for h in _members_for(_MODULE_FORMS_HANDLE, analyzer)}
        assert (
            f"{_MODULE_FORMS_HANDLE}.Final" not in members
        ), "Final is an imported name and must be excluded from members"
        assert not any(m.endswith(".Final") for m in members)

    def test_members_are_handles(self, analyzer: JediAnalyzer) -> None:
        """All returned members must be Handle instances."""
        members = _members_for(_MODULE_FORMS_HANDLE, analyzer)
        assert members, "module_forms should have at least one member"
        assert all(isinstance(h, Handle) for h in members)


# ---------------------------------------------------------------------------
# Task 3.1/3.2 — callees resolver (forward goto, never reverse search)
# ---------------------------------------------------------------------------


class TestResolveCalleesContract:
    """``callees`` = forward resolution of each call site to a canonical handle.

    Contract is "≥ these handles, plus N unresolved" — NOT exact equality —
    because Jedi may resolve incidental builtins.  We pin the resolvable project
    and stdlib callees, dedup, the unresolved count, nested-scope exclusion, and
    the non-function empty case.

    Fixture ``orchestrate`` call inventory:
    - ``make_widget("alpha")`` and ``make_widget("beta")`` → ONE callee (dedup)
    - ``math.sqrt(2)`` → external-scope callee ``math.sqrt``
    - ``cb()`` → dynamic, UNRESOLVABLE → unresolved_call_sites >= 1
    - ``_inner()`` is a nested def; its ``len(...)`` call is NOT orchestrate's
    """

    def test_returns_edgeresult(self, analyzer: JediAnalyzer) -> None:
        result = _callees_for(_ORCHESTRATE_HANDLE, analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    def test_project_callee_present(self, analyzer: JediAnalyzer) -> None:
        callees = {str(h) for h in _callees_for(_ORCHESTRATE_HANDLE, analyzer).handles}
        assert _MAKE_WIDGET_HANDLE in callees, f"project callee make_widget missing; got {callees}"

    def test_stdlib_callee_present(self, analyzer: JediAnalyzer) -> None:
        callees = {str(h) for h in _callees_for(_ORCHESTRATE_HANDLE, analyzer).handles}
        # math.sqrt is an external-scope callee; its attribute target must goto
        # the rightmost identifier (sqrt), not the receiver (math).
        assert "math.sqrt" in callees, f"stdlib callee math.sqrt missing; got {callees}"

    def test_duplicate_call_deduped(self, analyzer: JediAnalyzer) -> None:
        # make_widget is called twice in the body; it must appear exactly once.
        handles = [str(h) for h in _callees_for(_ORCHESTRATE_HANDLE, analyzer).handles]
        assert (
            handles.count(_MAKE_WIDGET_HANDLE) == 1
        ), f"make_widget should be deduped to one entry; got {handles}"

    def test_unresolved_call_sites_counted(self, analyzer: JediAnalyzer) -> None:
        # The dynamic ``cb()`` call cannot be resolved by goto.
        result = _callees_for(_ORCHESTRATE_HANDLE, analyzer)
        assert (
            result.unresolved_call_sites is not None and result.unresolved_call_sites >= 1
        ), f"expected >=1 unresolved call site, got {result.unresolved_call_sites}"

    def test_nested_scope_call_excluded(self, analyzer: JediAnalyzer) -> None:
        # ``len`` is called only inside the nested ``_inner`` function; it must
        # NOT be attributed to orchestrate's callees.
        callees = {str(h) for h in _callees_for(_ORCHESTRATE_HANDLE, analyzer).handles}
        assert not any(
            c.endswith(".len") or c == "len" or c.endswith("builtins.len") for c in callees
        ), f"nested-scope call ``len`` leaked into orchestrate callees: {callees}"

    def test_deterministic_across_runs(self, analyzer: JediAnalyzer) -> None:
        first = _callees_for(_ORCHESTRATE_HANDLE, analyzer)
        second = _callees_for(_ORCHESTRATE_HANDLE, analyzer)
        assert [str(h) for h in first.handles] == [str(h) for h in second.handles]
        assert first.unresolved_call_sites == second.unresolved_call_sites


class TestResolveCalleesMethodSource:
    """Spec §5.2 "function/method": a METHOD source also produces callees.

    Jedi reports methods (instance, class, static) with ``type="function"``,
    so ``_normalise_kind`` returns ``"function"`` for them.  The ``"function"``
    gate in ``resolve_callees`` therefore intentionally INCLUDES methods — they
    are NOT excluded.  This class provides the regression test that was missing.

    Fixture: ``Processor.run`` (``mypackage._core.callees_fixture.Processor.run``)
    calls ``make_widget("processed")`` — one statically resolvable callee.
    """

    def test_method_source_returns_edgeresult(self, analyzer: JediAnalyzer) -> None:
        result = _callees_for(_PROCESSOR_RUN_HANDLE, analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    def test_method_source_has_project_callee(self, analyzer: JediAnalyzer) -> None:
        """``Processor.run`` calls ``make_widget`` — that handle must appear.

        This is the load-bearing assertion: if methods were gated out by the
        ``"function"`` check, handles would be empty and this would fail.
        """
        result = _callees_for(_PROCESSOR_RUN_HANDLE, analyzer)
        callees = {str(h) for h in result.handles}
        assert (
            _MAKE_WIDGET_HANDLE in callees
        ), f"method source Processor.run should have make_widget as a callee; got {callees}"

    def test_method_source_has_zero_unresolved(self, analyzer: JediAnalyzer) -> None:
        """``make_widget`` is fully resolvable; no dynamic call sites in run's body."""
        result = _callees_for(_PROCESSOR_RUN_HANDLE, analyzer)
        assert result.unresolved_call_sites == 0, (
            f"expected 0 unresolved call sites for Processor.run; "
            f"got {result.unresolved_call_sites}"
        )


class TestResolveCalleesNonFunction:
    """A non-function source has no callees: empty handles, zero unresolved."""

    def test_class_is_empty(self, analyzer: JediAnalyzer) -> None:
        result = _callees_for(_WIDGET_HANDLE, analyzer)
        assert result.handles == []
        assert result.unresolved_call_sites == 0

    def test_module_is_empty(self, analyzer: JediAnalyzer) -> None:
        result = _callees_for(_CALLEES_MODULE_HANDLE, analyzer)
        assert result.handles == []
        assert result.unresolved_call_sites == 0

    def test_variable_is_empty(self, analyzer: JediAnalyzer) -> None:
        result = _callees_for(f"{_MODULE_HANDLE}.DEFAULT_NAME", analyzer)
        assert result.handles == []
        assert result.unresolved_call_sites == 0


class TestResolveCalleesNeverReverseSearch:
    """The load-bearing trust constraint: callees NEVER calls reverse search.

    ``get_references`` is the non-deterministic reverse-search path.  Patch it to
    explode if touched, then run the resolver over the fixture and assert it
    completes AND the spy was never called.
    """

    def test_get_references_not_called(self, analyzer: JediAnalyzer) -> None:
        # Sanity: the patch target must actually be the method Jedi exposes,
        # otherwise this test is a no-op.
        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on callees path"))
        with patch.object(jedi.Script, "get_references", spy):
            result = _callees_for(_ORCHESTRATE_HANDLE, analyzer)
        # Resolver completed without touching reverse search.
        assert _MAKE_WIDGET_HANDLE in {str(h) for h in result.handles}
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# Task 3.1/3.2 — imported_by resolver (pure-AST reverse import scan, async)
# ---------------------------------------------------------------------------


async def _imported_by_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult | None:
    """Resolve *handle* to a Jedi name and await its ``imported_by`` result.

    Returns the raw resolver result so tests can distinguish ``None`` (wrong
    kind — a non-module handle) from ``EdgeResult([])`` (a module nobody
    imports — measured none).
    """
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return await resolve_imported_by(jedi_name, analyzer)


class TestResolveImportedByModule:
    """``imported_by`` = the modules that import a target module (reverse scan).

    Contract is "≥ these known importers" — a SUBSET assertion, not exact
    equality — so the test stays robust as the fixture grows. The non-package
    ``script_importer`` is pinned explicitly: it lives outside ``mypackage`` and
    is the case that the file-based scan (not Jedi reference resolution) buys.
    """

    @pytest.mark.asyncio
    async def test_returns_edgeresult(self, analyzer: JediAnalyzer) -> None:
        result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    @pytest.mark.asyncio
    async def test_known_importers_present(self, analyzer: JediAnalyzer) -> None:
        result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        importers = {str(h) for h in result.handles}
        expected_present = {
            _DIRECT_IMPORTER_HANDLE,
            _REL_IMPORTER_HANDLE,
            _USAGE_IMPORTER_HANDLE,
        }
        missing = expected_present - importers
        assert not missing, f"expected importers missing: {missing}; got {importers}"

    @pytest.mark.asyncio
    async def test_non_package_script_importer_present(self, analyzer: JediAnalyzer) -> None:
        # script_importer.py lives at the fixture root, OUTSIDE mypackage, so its
        # handle is the path-derived ``script_importer``. Building the importer's
        # Name from its FILE (not by re-resolving the handle) is what makes this
        # case work — re-resolution fails for non-package scripts.
        result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        importers = {str(h) for h in result.handles}
        assert (
            _SCRIPT_IMPORTER_HANDLE in importers
        ), f"non-package script importer missing; got {importers}"

    @pytest.mark.asyncio
    async def test_adjacents_are_handle_name_pairs_building_module_stubs(
        self, analyzer: JediAnalyzer
    ) -> None:
        # Each adjacent is a (Handle, Name) pair whose Name is a module
        # sentinel (kind == "module") built from the importer's own file.
        result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        assert result.adjacents, "widgets should have importers"
        for handle, name in result.adjacents:
            assert isinstance(handle, Handle)
            assert isinstance(name, ModuleSentinel)
            assert name.type == "module"
            # The Name's handle matches the adjacent handle (built from file).
            assert name.full_name == str(handle)

    @pytest.mark.asyncio
    async def test_unresolved_call_sites_is_none(self, analyzer: JediAnalyzer) -> None:
        # The unresolved-call-site notion is callees-only; imported_by never
        # reports it.
        result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        assert result.unresolved_call_sites is None


class TestResolveImportedByMeasuredEmpty:
    """A module that nobody imports → ``EdgeResult([])`` (measured none).

    This is the absence-vs-zero invariant: ``module_forms`` IS a module (the
    kind is correct, so the edge applies), but no other file imports it, so the
    measured result is an empty adjacency — NOT the wrong-kind ``None`` signal.
    """

    @pytest.mark.asyncio
    async def test_leaf_module_is_measured_empty(self, analyzer: JediAnalyzer) -> None:
        result = await _imported_by_for(_MODULE_FORMS_HANDLE, analyzer)
        assert result is not None, "module_forms is a module — must NOT be wrong-kind None"
        assert isinstance(result, EdgeResult)
        assert result.handles == [], f"module_forms is imported by nobody; got {result.handles}"


class TestResolveImportedByNonModule:
    """A non-module handle → wrong-kind ``None`` (NOT ``EdgeResult([])``).

    This is the load-bearing #332 distinction: a class/function CAN be imported,
    so returning ``[]`` would be the "measured zero" lie. ``None`` signals "this
    edge does not apply to this kind" and becomes ``not_yet_implemented``
    downstream in Phase 4 — it must be distinguishable from the measured-empty
    module case above.
    """

    @pytest.mark.asyncio
    async def test_class_handle_returns_none(self, analyzer: JediAnalyzer) -> None:
        # Widget is a class — imported_by does not apply to a symbol kind.
        result = await _imported_by_for(_WIDGET_HANDLE, analyzer)
        assert result is None, f"non-module handle must return None, got {result!r}"

    @pytest.mark.asyncio
    async def test_function_handle_returns_none(self, analyzer: JediAnalyzer) -> None:
        # make_widget is a function — also a symbol kind, also None.
        result = await _imported_by_for(_MAKE_WIDGET_HANDLE, analyzer)
        assert result is None, f"non-module handle must return None, got {result!r}"

    @pytest.mark.asyncio
    async def test_none_is_distinct_from_measured_empty(self, analyzer: JediAnalyzer) -> None:
        # The two empty-looking outcomes must be machine-distinguishable.
        wrong_kind = await _imported_by_for(_WIDGET_HANDLE, analyzer)
        measured_empty = await _imported_by_for(_MODULE_FORMS_HANDLE, analyzer)
        assert wrong_kind is None
        assert measured_empty == EdgeResult(adjacents=[])
        assert wrong_kind != measured_empty


class TestResolveImportedByNeverReverseSearch:
    """imported_by NEVER calls Jedi reverse search (it is pure-AST).

    Mirrors ``TestResolveCalleesNeverReverseSearch``: patch ``get_references`` to
    explode if touched, await the resolver over the fixture, then assert it
    completed (real importers present) AND the spy was never called.
    """

    @pytest.mark.asyncio
    async def test_get_references_not_called(self, analyzer: JediAnalyzer) -> None:
        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on imported_by path"))
        with patch.object(jedi.Script, "get_references", spy):
            result = await _imported_by_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        assert _SCRIPT_IMPORTER_HANDLE in {str(h) for h in result.handles}
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# Task 1.1/1.2 — subclasses resolver (#348): forward AST class-graph walk
# ---------------------------------------------------------------------------


@pytest.fixture
def subclasses_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the dedicated subclasses_edge fixture."""
    return JediAnalyzer(str(_SUBCLASSES_FIXTURE))


async def _subclasses_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult:
    """Resolve *handle* to a Jedi name and await its ``subclasses`` result.

    Unlike ``imported_by``, ``subclasses`` NEVER returns ``None`` — a non-class
    handle yields a measured-empty ``EdgeResult([])`` (only a class CAN be
    subclassed, so ``[]`` for the wrong kind is true by definition, not the
    absence-vs-zero lie that forced imported_by's None path).
    """
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return await resolve_subclasses(jedi_name, analyzer)


class TestResolveSubclassesClass:
    """``subclasses`` = the project classes that subclass a base, as canonical handles.

    The resolver reuses ``find_subclasses(scope="main", include_indirect=True)``,
    so the result is the full project subclass closure (direct + indirect). The
    dedicated fixture pins a known topology:

    - ``pkg.middle.Mammal``     — DIRECT subclass (importable module)
    - ``pkg.middle.Dog``        — INDIRECT (grandchild) via Mammal
    - ``script_animal.Lizard``  — DIRECT subclass in a NON-importable root script
    """

    @pytest.mark.asyncio
    async def test_returns_edgeresult(self, subclasses_analyzer: JediAnalyzer) -> None:
        result = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    @pytest.mark.asyncio
    async def test_direct_subclass_present(self, subclasses_analyzer: JediAnalyzer) -> None:
        handles = {
            str(h) for h in (await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)).handles
        }
        assert _MAMMAL_HANDLE in handles, f"direct subclass Mammal missing; got {handles}"

    @pytest.mark.asyncio
    async def test_indirect_grandchild_subclass_present(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # Dog(Mammal) is a grandchild of Animal — include_indirect=True must
        # surface it (the single-hop edge intentionally returns the full closure
        # so len(stubs) == inspect.edge_counts.subclasses).
        handles = {
            str(h) for h in (await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)).handles
        }
        assert _DOG_HANDLE in handles, f"indirect subclass Dog missing; got {handles}"

    @pytest.mark.asyncio
    async def test_non_importable_file_subclass_present(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # Lizard lives in script_animal.py at the project root (no importable
        # dotted path). scope="main" finds it, and file-based Name production
        # (not handle re-resolution) is what keeps it in the result.
        handles = {
            str(h) for h in (await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)).handles
        }
        assert (
            _LIZARD_HANDLE in handles
        ), f"non-importable-file subclass Lizard missing; got {handles}"

    @pytest.mark.asyncio
    async def test_exact_subclass_handle_set(self, subclasses_analyzer: JediAnalyzer) -> None:
        # The full project subclass closure of Animal is exactly these three.
        handles = {
            str(h) for h in (await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)).handles
        }
        assert handles == {_MAMMAL_HANDLE, _DOG_HANDLE, _LIZARD_HANDLE}, f"got {handles}"

    @pytest.mark.asyncio
    async def test_adjacents_are_handle_name_pairs_building_class_stubs(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        # Each adjacent is a (Handle, Jedi Name) pair whose Name is a real class
        # name built from the subclass's OWN file, so expand can build a class
        # stub without re-resolving. The Name's full_name matches the handle.
        result = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert result.adjacents, "Animal should have subclasses"
        for handle, name in result.adjacents:
            assert isinstance(handle, Handle)
            assert name.type == "class"
            assert name.full_name == str(handle)

    @pytest.mark.asyncio
    async def test_unresolved_call_sites_is_none(self, subclasses_analyzer: JediAnalyzer) -> None:
        # The unresolved-call-site notion is callees-only; subclasses never reports it.
        result = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert result.unresolved_call_sites is None

    @pytest.mark.asyncio
    async def test_deterministic_across_runs(self, subclasses_analyzer: JediAnalyzer) -> None:
        first = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        second = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert [str(h) for h in first.handles] == [str(h) for h in second.handles]


class TestResolveSubclassesMeasuredEmpty:
    """A class with NO project subclasses → ``EdgeResult([])`` (measured none)."""

    @pytest.mark.asyncio
    async def test_class_with_no_subclasses_is_measured_empty(
        self, subclasses_analyzer: JediAnalyzer
    ) -> None:
        result = await _subclasses_for(_LONER_HANDLE, subclasses_analyzer)
        assert isinstance(result, EdgeResult)
        assert result.handles == [], f"Loner is subclassed by nobody; got {result.handles}"


class TestResolveSubclassesNonClass:
    """A non-class handle → measured-empty ``EdgeResult([])`` — NEVER ``None``.

    This is the defining decision of the slice: only a class CAN be subclassed,
    so ``[]`` for a function/variable/module is true BY DEFINITION (the
    members/callees case), NOT the absence-vs-zero lie that forced imported_by's
    ``None`` path. Returning ``EdgeResult([])`` (not ``None``) is what keeps
    ``expand.py`` untouched.
    """

    @pytest.mark.asyncio
    async def test_function_handle_is_measured_empty(self, analyzer: JediAnalyzer) -> None:
        result = await _subclasses_for(_MAKE_WIDGET_HANDLE, analyzer)
        assert result is not None, "non-class must NOT be wrong-kind None"
        assert isinstance(result, EdgeResult)
        assert result.handles == []

    @pytest.mark.asyncio
    async def test_variable_handle_is_measured_empty(self, analyzer: JediAnalyzer) -> None:
        result = await _subclasses_for(f"{_MODULE_HANDLE}.DEFAULT_NAME", analyzer)
        assert result is not None
        assert result.handles == []

    @pytest.mark.asyncio
    async def test_module_handle_is_measured_empty(self, analyzer: JediAnalyzer) -> None:
        result = await _subclasses_for(_MODULE_HANDLE, analyzer)
        assert result is not None
        assert result.handles == []

    @pytest.mark.asyncio
    async def test_non_class_is_not_none(self, analyzer: JediAnalyzer) -> None:
        # The load-bearing distinction: subclasses never uses the None wrong-kind
        # signal, so expand.py's hardcoded module-only None branch stays correct.
        result = await _subclasses_for(_MAKE_WIDGET_HANDLE, analyzer)
        assert result is not None
        assert result == EdgeResult(adjacents=[])


class TestResolveSubclassesNeverReverseSearch:
    """subclasses NEVER calls Jedi reverse search (it is forward AST + goto only).

    Mirrors the callees/imported_by spies: patch ``get_references`` to explode if
    touched, await the resolver over the fixture, then assert it completed (real
    subclasses present) AND the spy was never called.
    """

    @pytest.mark.asyncio
    async def test_get_references_not_called(self, subclasses_analyzer: JediAnalyzer) -> None:
        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on subclasses path"))
        with patch.object(jedi.Script, "get_references", spy):
            result = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert _MAMMAL_HANDLE in {str(h) for h in result.handles}
        spy.assert_not_called()
