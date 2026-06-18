"""Tests for the edge-resolver registry and ``members`` resolver — Tasks 2.1+2.2.

The edge registry is the single source of truth for which edges ``expand``
supports.  Every edge name MUST classify into exactly one status:

- ``"implemented"`` — ``members``, ``callees``, ``imported_by``, ``subclasses``,
  ``superclasses``, ``imports``, ``enclosing_scope``
- ``"not_yet_implemented"`` — *(currently empty — all recognised edges are now
  implemented, as of #370 / enclosing_scope)*
- ``"deferred_reference_backend"`` — the inbound / reference edges
  (``callers``, ``references``, ``read_by``, ``written_by``, ``passed_by``,
  ``overrides``, ``overridden_by``, ``decorated_by``, ``decorates``)
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
    resolve_imports,
    resolve_members,
    resolve_subclasses,
    resolve_superclasses,
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

# superclasses fixtures (issue #361): a dedicated fixture project with a known
# direct-base topology. Tests cover single/multiple/external/no-base class cases.
_SUPERCLASSES_FIXTURE = (
    Path(__file__).parent.parent.parent.parent / "fixtures" / "superclasses_edge"
)
_BASE_HANDLE = "pkg.bases.Base"  # class with NO superclasses (measured-empty)
_MIXIN_HANDLE = (
    "pkg.bases.Mixin"  # second project-internal base; used for multiple-inheritance tests
)
_CHILD_HANDLE = "pkg.derived.Child"  # one project superclass: pkg.bases.Base
_MULTI_CHILD_HANDLE = "pkg.derived.MultiChild"  # two project superclasses
_EXTERNAL_CHILD_HANDLE = "pkg.derived.ExternalChild"  # one external superclass
_GRANDCHILD_HANDLE = "pkg.derived.GrandChild"  # one direct superclass: Child (not Base)
_FUNCTION_HANDLE = "pkg.derived.function_in_module"  # function (wrong-kind)
_VAR_HANDLE = "pkg.derived.VAR_IN_MODULE"  # variable (wrong-kind)
_WEIRD_HANDLE = "pkg.derived.Weird"  # class with unresolvable base (drop-and-diverge path)


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

    def test_superclasses_is_implemented(self) -> None:
        # superclasses moves from not_yet_implemented to implemented (#361): its
        # resolver (resolve_superclasses) uses AST ClassDef.bases + forward goto —
        # no reverse symbol search, so it belongs with members/callees/subclasses.
        assert edge_status("superclasses") == "implemented"

    def test_imports_is_implemented(self) -> None:
        # imports moves from not_yet_implemented to implemented (#367): its
        # resolver (resolve_imports) uses top-level AST import nodes + forward
        # goto — no reverse symbol search, so it belongs with the other implemented edges.
        assert edge_status("imports") == "implemented"

    def test_enclosing_scope_is_implemented(self) -> None:
        # enclosing_scope moves from not_yet_implemented to implemented (#370):
        # its resolver (resolve_enclosing_scope) uses Jedi parent() — no reverse
        # symbol search, so it belongs with the other implemented edges.
        assert edge_status("enclosing_scope") == "implemented"

    def test_not_yet_implemented_category_is_empty(self) -> None:
        # All recognised structural edges are now implemented.  The
        # _NOT_YET_IMPLEMENTED_EDGES set is retained for the 4-status taxonomy
        # but is intentionally empty after #370.
        from pyeye.mcp.operations.edges import _NOT_YET_IMPLEMENTED_EDGES

        assert (
            frozenset() == _NOT_YET_IMPLEMENTED_EDGES
        ), f"_NOT_YET_IMPLEMENTED_EDGES must be empty; got {_NOT_YET_IMPLEMENTED_EDGES!r}"

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
        # surface it (the single-hop subclasses edge intentionally returns the
        # full project closure; subclasses is expand-only, #392).
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
        # find_subclasses iterates a Python set, so its order is
        # PYTHONHASHSEED-dependent. The resolver sorts adjacents by canonical
        # handle string, so the ORDERED list must equal the sorted FQNs of the
        # fixture's subclasses — pin that exact order (a same-process re-run
        # comparison would pass even with the bug, since set order is fixed
        # within a process). Run under multiple PYTHONHASHSEED values to prove
        # cross-process stability.
        expected_order = sorted([_MAMMAL_HANDLE, _DOG_HANDLE, _LIZARD_HANDLE])
        first = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        second = await _subclasses_for(_ANIMAL_HANDLE, subclasses_analyzer)
        assert [str(h) for h in first.handles] == expected_order
        assert [str(h) for h in second.handles] == expected_order


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


# ---------------------------------------------------------------------------
# Issue #361 — superclasses resolver: direct-base AST + forward goto
# ---------------------------------------------------------------------------


@pytest.fixture
def superclasses_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the dedicated superclasses_edge fixture."""
    return JediAnalyzer(str(_SUPERCLASSES_FIXTURE))


def _superclasses_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult:
    """Resolve *handle* to a Jedi name and return its ``superclasses`` result.

    ``superclasses`` is synchronous (AST walk + goto are sync) and NEVER
    returns ``None`` — a non-class handle yields a measured-empty
    ``EdgeResult([])`` (only a class CAN have superclasses, so ``[]`` for the
    wrong kind is true by definition — the ``members``/``callees`` case).
    """
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return resolve_superclasses(jedi_name, analyzer)


class TestResolveSuperclassesSingleProjectBase:
    """``superclasses`` = the DIRECT base classes of a class, as canonical handles.

    ``Child`` has exactly one project-internal superclass: ``pkg.bases.Base``.
    """

    def test_returns_edgeresult(self, superclasses_analyzer: JediAnalyzer) -> None:
        result = _superclasses_for(_CHILD_HANDLE, superclasses_analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    def test_project_base_present(self, superclasses_analyzer: JediAnalyzer) -> None:
        handles = {str(h) for h in _superclasses_for(_CHILD_HANDLE, superclasses_analyzer).handles}
        assert _BASE_HANDLE in handles, f"expected {_BASE_HANDLE!r} in superclasses; got {handles}"

    def test_exact_superclass_set_single(self, superclasses_analyzer: JediAnalyzer) -> None:
        handles = {str(h) for h in _superclasses_for(_CHILD_HANDLE, superclasses_analyzer).handles}
        assert handles == {_BASE_HANDLE}, f"expected exactly {{Base}}; got {handles}"

    def test_adjacents_are_handle_name_pairs(self, superclasses_analyzer: JediAnalyzer) -> None:
        # Each adjacent is a (Handle, Jedi Name) pair whose Name is the goto def.
        result = _superclasses_for(_CHILD_HANDLE, superclasses_analyzer)
        assert result.adjacents, "Child should have superclasses"
        for handle, name in result.adjacents:
            assert isinstance(handle, Handle)
            # The goto def has a full_name matching the handle
            assert name.full_name == str(handle)

    def test_unresolved_call_sites_is_none(self, superclasses_analyzer: JediAnalyzer) -> None:
        # The unresolved-call-site notion is callees-only; superclasses never reports it.
        result = _superclasses_for(_CHILD_HANDLE, superclasses_analyzer)
        assert result.unresolved_call_sites is None


class TestResolveSuperclassesMultipleBases:
    """``MultiChild`` has two project-internal superclasses: ``Base`` and ``Mixin``."""

    def test_both_bases_present(self, superclasses_analyzer: JediAnalyzer) -> None:
        handles = {
            str(h) for h in _superclasses_for(_MULTI_CHILD_HANDLE, superclasses_analyzer).handles
        }
        assert _BASE_HANDLE in handles, f"Base missing from MultiChild superclasses: {handles}"
        assert _MIXIN_HANDLE in handles, f"Mixin missing from MultiChild superclasses: {handles}"

    def test_exact_superclass_set_multiple(self, superclasses_analyzer: JediAnalyzer) -> None:
        handles = {
            str(h) for h in _superclasses_for(_MULTI_CHILD_HANDLE, superclasses_analyzer).handles
        }
        assert handles == {_BASE_HANDLE, _MIXIN_HANDLE}, f"got {handles}"

    def test_deduplicated(self, superclasses_analyzer: JediAnalyzer) -> None:
        # No handle should appear twice, even if the AST has a duplicate base (edge case).
        handles = [
            str(h) for h in _superclasses_for(_MULTI_CHILD_HANDLE, superclasses_analyzer).handles
        ]
        assert len(handles) == len(set(handles)), f"duplicates found: {handles}"

    def test_deterministic_order(self, superclasses_analyzer: JediAnalyzer) -> None:
        # Order must be stable across repeated calls (sorted by handle string).
        first = _superclasses_for(_MULTI_CHILD_HANDLE, superclasses_analyzer)
        second = _superclasses_for(_MULTI_CHILD_HANDLE, superclasses_analyzer)
        assert [str(h) for h in first.handles] == [str(h) for h in second.handles]
        # Verify it's the sorted order (the resolver sorts by handle string).
        handles = [str(h) for h in first.handles]
        assert handles == sorted(handles), f"not sorted by handle string: {handles}"


class TestResolveSuperclassesExternalBase:
    """``ExternalChild`` extends ``pathlib.PurePosixPath`` — an external stdlib class.

    External bases must be INCLUDED in the ``superclasses`` edge result.
    The handle is the resolved canonical dotted name of the external class.
    """

    def test_external_base_present(self, superclasses_analyzer: JediAnalyzer) -> None:
        handles = {
            str(h) for h in _superclasses_for(_EXTERNAL_CHILD_HANDLE, superclasses_analyzer).handles
        }
        # pathlib.PurePosixPath is the external superclass
        assert any(
            "PurePosixPath" in h for h in handles
        ), f"PurePosixPath external base missing; got {handles}"

    def test_external_base_is_handle_instance(self, superclasses_analyzer: JediAnalyzer) -> None:
        result = _superclasses_for(_EXTERNAL_CHILD_HANDLE, superclasses_analyzer)
        assert result.handles, "ExternalChild must have at least one superclass"
        assert all(isinstance(h, Handle) for h in result.handles)


class TestResolveSuperclassesMeasuredEmpty:
    """A class with NO bases → ``EdgeResult([])`` (measured none).

    ``pkg.bases.Base`` has no explicit superclasses — the empty list is the
    correct measured result (NOT wrong-kind ``None``).
    """

    def test_class_with_no_bases_is_measured_empty(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        result = _superclasses_for(_BASE_HANDLE, superclasses_analyzer)
        assert isinstance(result, EdgeResult)
        assert result.handles == [], f"Base has no superclasses; got {result.handles}"

    def test_measured_empty_is_not_none(self, superclasses_analyzer: JediAnalyzer) -> None:
        result = _superclasses_for(_BASE_HANDLE, superclasses_analyzer)
        assert result is not None
        assert result == EdgeResult(adjacents=[])


class TestResolveSuperclassesNonClass:
    """A non-class handle → measured-empty ``EdgeResult([])`` — NEVER ``None``.

    Only a class CAN have superclasses, so ``[]`` for a function/variable is
    true BY DEFINITION (the ``members``/``callees`` case, NOT the
    absence-vs-zero lie that forced ``imported_by``'s ``None`` path).
    Because this resolver never returns ``None``, ``expand.py`` needs no change.
    """

    def test_function_handle_is_measured_empty(self, superclasses_analyzer: JediAnalyzer) -> None:
        result = _superclasses_for(_FUNCTION_HANDLE, superclasses_analyzer)
        assert result is not None, "non-class must NOT be wrong-kind None"
        assert isinstance(result, EdgeResult)
        assert result.handles == []

    def test_variable_handle_is_measured_empty(self, superclasses_analyzer: JediAnalyzer) -> None:
        result = _superclasses_for(_VAR_HANDLE, superclasses_analyzer)
        assert result is not None
        assert result.handles == []

    def test_non_class_is_not_none(self, superclasses_analyzer: JediAnalyzer) -> None:
        # The load-bearing distinction: superclasses never uses the None wrong-kind
        # signal, so expand.py's hardcoded module-only None branch stays correct.
        result = _superclasses_for(_FUNCTION_HANDLE, superclasses_analyzer)
        assert result is not None
        assert result == EdgeResult(adjacents=[])


class TestResolveSuperclassesNeverReverseSearch:
    """superclasses NEVER calls Jedi reverse search (it is forward AST + goto only).

    Mirrors the callees/subclasses spies: patch ``get_references`` to explode if
    touched, run the resolver over the fixture, then assert it completed (real
    superclass present) AND the spy was never called.
    """

    def test_get_references_not_called(self, superclasses_analyzer: JediAnalyzer) -> None:
        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on superclasses path"))
        with patch.object(jedi.Script, "get_references", spy):
            result = _superclasses_for(_CHILD_HANDLE, superclasses_analyzer)
        assert _BASE_HANDLE in {str(h) for h in result.handles}
        spy.assert_not_called()


class TestResolveSuperclassesCountConsistency:
    """Count-consistency: ``len(expand stubs) == inspect.edge_counts.superclasses``.

    The progressive-disclosure contract requires the edge resolver count and the
    ``inspect`` edge_counts value to agree.  ``_count_superclasses`` now delegates
    to ``resolve_superclasses`` so equality holds BY CONSTRUCTION (the same
    resolver runs for both).  This test pins that contract as an integration check.
    """

    @pytest.mark.asyncio
    async def test_single_base_count_equals_resolve_count(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``Child`` has one resolvable base: resolver count == 1."""
        from pyeye.mcp.operations.inspect import _count_superclasses

        jedi_name = _find_jedi_name_for_handle(_CHILD_HANDLE, superclasses_analyzer)
        assert jedi_name is not None
        resolver_count = len(resolve_superclasses(jedi_name, superclasses_analyzer).handles)
        counter_count = await _count_superclasses(jedi_name, superclasses_analyzer)
        assert (
            resolver_count == counter_count == 1
        ), f"resolver={resolver_count}, counter={counter_count}; expected both == 1"

    @pytest.mark.asyncio
    async def test_multi_base_count_equals_resolve_count(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``MultiChild`` has two resolvable bases: resolver count == 2."""
        from pyeye.mcp.operations.inspect import _count_superclasses

        jedi_name = _find_jedi_name_for_handle(_MULTI_CHILD_HANDLE, superclasses_analyzer)
        assert jedi_name is not None
        resolver_count = len(resolve_superclasses(jedi_name, superclasses_analyzer).handles)
        counter_count = await _count_superclasses(jedi_name, superclasses_analyzer)
        assert (
            resolver_count == counter_count == 2
        ), f"resolver={resolver_count}, counter={counter_count}; expected both == 2"

    @pytest.mark.asyncio
    async def test_no_base_count_is_zero(self, superclasses_analyzer: JediAnalyzer) -> None:
        """``Base`` has no superclasses: both resolver count and counter are 0."""
        from pyeye.mcp.operations.inspect import _count_superclasses

        jedi_name = _find_jedi_name_for_handle(_BASE_HANDLE, superclasses_analyzer)
        assert jedi_name is not None
        resolver_count = len(resolve_superclasses(jedi_name, superclasses_analyzer).handles)
        counter_count = await _count_superclasses(jedi_name, superclasses_analyzer)
        assert (
            resolver_count == counter_count == 0
        ), f"resolver={resolver_count}, counter={counter_count}; expected both == 0"


# ---------------------------------------------------------------------------
# Gap 1 — direct-bases-not-MRO regression guard
# ---------------------------------------------------------------------------


class TestResolveSuperclassesDirectNotMRO:
    """``resolve_superclasses`` returns DIRECT bases only — NOT the full MRO/ancestor closure.

    Topology: ``GrandChild(Child)`` → ``Child(Base)`` → ``Base``

    When ``resolve_superclasses(GrandChild)`` is called it MUST return only
    ``Child`` (the one direct parent).  ``Base`` is an ancestor via the MRO but
    is NOT a direct base of ``GrandChild`` and therefore MUST NOT appear.

    This test class is the load-bearing guard against a future regression that
    accidentally walks the full MRO instead of reading ``ast.ClassDef.bases``.
    """

    def test_grandchild_direct_base_is_child(self, superclasses_analyzer: JediAnalyzer) -> None:
        """``GrandChild`` has exactly one direct superclass: ``pkg.derived.Child``."""
        handles = {
            str(h) for h in _superclasses_for(_GRANDCHILD_HANDLE, superclasses_analyzer).handles
        }
        assert (
            _CHILD_HANDLE in handles
        ), f"direct base Child missing from GrandChild superclasses; got {handles}"

    def test_grandchild_does_not_include_grandparent(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``Base`` is a transitive ancestor but NOT a direct base — must be absent."""
        handles = {
            str(h) for h in _superclasses_for(_GRANDCHILD_HANDLE, superclasses_analyzer).handles
        }
        assert (
            _BASE_HANDLE not in handles
        ), f"transitive ancestor Base must NOT appear in GrandChild superclasses; got {handles}"

    def test_grandchild_exact_superclass_set(self, superclasses_analyzer: JediAnalyzer) -> None:
        """Exact set check: ``GrandChild`` → exactly ``{pkg.derived.Child}``."""
        handles = {
            str(h) for h in _superclasses_for(_GRANDCHILD_HANDLE, superclasses_analyzer).handles
        }
        assert handles == {_CHILD_HANDLE}, f"expected exactly {{pkg.derived.Child}}; got {handles}"


# ---------------------------------------------------------------------------
# Gap 2 — count-consistency through the full public inspect() path
# ---------------------------------------------------------------------------


class TestResolveSuperclassesCountConsistencyViaInspect:
    """Count-consistency via the FULL public ``inspect()`` API (not just the helper).

    This exercises the real production path:
        ``inspect(handle, analyzer)`` → ``_build_edge_counts``
        → ``_count_superclasses`` → ``resolve_superclasses``

    The assertion is non-vacuous: it uses a class with a positive base count
    (``Child`` has 1 base, ``MultiChild`` has 2) so an accidentally zero count
    would be caught.  The private-helper tests in
    ``TestResolveSuperclassesCountConsistency`` already cover the helpers in
    isolation; these tests cover the public surface.
    """

    @pytest.mark.asyncio
    async def test_child_count_via_inspect_matches_resolver(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``Child`` has 1 direct base: inspect edge_counts and resolver agree."""
        from pyeye.mcp.operations.inspect import inspect

        jedi_name = _find_jedi_name_for_handle(_CHILD_HANDLE, superclasses_analyzer)
        assert jedi_name is not None
        resolver_count = len(resolve_superclasses(jedi_name, superclasses_analyzer).handles)
        node = await inspect(_CHILD_HANDLE, superclasses_analyzer)
        inspect_count = node["edge_counts"]["superclasses"]
        assert resolver_count == inspect_count, (
            f"resolver={resolver_count}, inspect.edge_counts.superclasses={inspect_count}; "
            "must agree"
        )
        assert (
            inspect_count > 0
        ), "non-vacuous: Child has bases, so the count must be > 0 for this test to be meaningful"

    @pytest.mark.asyncio
    async def test_multi_child_count_via_inspect_matches_resolver(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``MultiChild`` has 2 direct bases: inspect edge_counts and resolver agree."""
        from pyeye.mcp.operations.inspect import inspect

        jedi_name = _find_jedi_name_for_handle(_MULTI_CHILD_HANDLE, superclasses_analyzer)
        assert jedi_name is not None
        resolver_count = len(resolve_superclasses(jedi_name, superclasses_analyzer).handles)
        node = await inspect(_MULTI_CHILD_HANDLE, superclasses_analyzer)
        inspect_count = node["edge_counts"]["superclasses"]
        assert resolver_count == inspect_count, (
            f"resolver={resolver_count}, inspect.edge_counts.superclasses={inspect_count}; "
            "must agree"
        )
        assert inspect_count > 0, "non-vacuous: MultiChild has bases, so the count must be > 0"


# ---------------------------------------------------------------------------
# Gap 3 — unresolvable-base field-vs-count divergence
# ---------------------------------------------------------------------------


class TestResolveSuperclassesUnresolvableBaseDivergence:
    """``Weird(NotDefinedAnywhere)`` exercises the drop-and-diverge path.

    ``resolve_superclasses`` drops bases that goto cannot resolve (no
    ``full_name`` → can't build an expand stub), so ``edge_counts.superclasses``
    is 0.  ``_get_superclasses`` / the ``superclasses`` field keeps ALL declared
    bases via ``ast.unparse`` fallback, so ``"NotDefinedAnywhere"`` still appears
    in the field.

    This is the intentional field-vs-count divergence documented in
    ``_get_superclasses`` and ``_count_superclasses``.
    """

    def test_unresolvable_base_dropped_by_resolver(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``resolve_superclasses(Weird)`` must return an empty handle list.

        Confirms that goto genuinely cannot resolve ``NotDefinedAnywhere`` in
        this fixture, making the test non-vacuous.
        """
        jedi_name = _find_jedi_name_for_handle(_WEIRD_HANDLE, superclasses_analyzer)
        assert jedi_name is not None, f"Could not find Jedi name for {_WEIRD_HANDLE!r}"
        result = resolve_superclasses(jedi_name, superclasses_analyzer)
        assert result.handles == [], (
            f"unresolvable base must be dropped; got {result.handles}. "
            "If Jedi resolves NotDefinedAnywhere, use a more unresolvable construct."
        )

    @pytest.mark.asyncio
    async def test_field_vs_count_divergence_end_to_end(
        self, superclasses_analyzer: JediAnalyzer
    ) -> None:
        """``Weird`` divergence via the full public ``inspect()`` path.

        Asserts all three aspects of the documented divergence:
        - ``edge_counts.superclasses == 0``  (resolver dropped the unresolvable base)
        - ``"NotDefinedAnywhere" in node["superclasses"]``  (field kept the fallback string)
        - ``len(node["superclasses"]) >= 1``  (non-vacuous: the field is not empty)
        """
        from pyeye.mcp.operations.inspect import inspect

        node = await inspect(_WEIRD_HANDLE, superclasses_analyzer)
        edge_count = node["edge_counts"]["superclasses"]
        field = node["superclasses"]

        assert edge_count == 0, (
            f"edge_counts.superclasses must be 0 for Weird (unresolvable base dropped); "
            f"got {edge_count}"
        )
        assert "NotDefinedAnywhere" in field, (
            f"superclasses field must contain the ast.unparse fallback 'NotDefinedAnywhere'; "
            f"got {field!r}"
        )
        assert (
            len(field) >= 1
        ), "non-vacuous: the superclasses field must be non-empty (contains the fallback string)"


# ---------------------------------------------------------------------------
# Issue #367 — imports resolver: top-level AST import nodes + forward goto
# ---------------------------------------------------------------------------

# Fixture: ``mypackage._core.imports_fixture`` (added for this edge)
# Top-level imports:
#   import os                          → module ``os`` (stdlib, ast.Import form)
#   from .widgets import make_widget   → function ``mypackage._core.widgets.make_widget``
#                                        (project symbol, ast.ImportFrom form)
# No top-level function/class definitions → members edge returns [] (disjoint from imports).
_IMPORTS_FIXTURE_HANDLE = "mypackage._core.imports_fixture"
_OS_MODULE_HANDLE = "os"
_MAKE_WIDGET_FROM_IMPORTS_HANDLE = "mypackage._core.widgets.make_widget"

# ``mypackage.helpers`` has NO top-level imports — only a class definition.
# Verified: helpers.py body starts with ``class Widget:``; no import statements.
_HELPERS_MODULE_HANDLE = "mypackage.helpers"


def _imports_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult | None:
    """Resolve *handle* to a Jedi name and return its ``imports`` result.

    Returns the raw resolver result so tests can distinguish ``None`` (wrong
    kind — a non-module handle) from ``EdgeResult([])`` (a module that has no
    top-level imports — measured none).
    """
    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return resolve_imports(jedi_name, analyzer)


class TestResolveImportsModule:
    """``imports`` = the top-level imports of a module as canonical handles.

    The fixture ``mypackage._core.imports_fixture`` imports:
    - ``import os``                        → adjacent module ``os``
    - ``from .widgets import make_widget`` → adjacent function handle
    """

    def test_returns_edgeresult(self, analyzer: JediAnalyzer) -> None:
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert isinstance(result, EdgeResult)
        assert all(isinstance(h, Handle) for h in result.handles)

    def test_stdlib_import_present(self, analyzer: JediAnalyzer) -> None:
        """``import os`` resolves to the ``os`` module handle."""
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        assert _OS_MODULE_HANDLE in handles, f"stdlib import 'os' missing; got {handles}"

    def test_project_from_import_present(self, analyzer: JediAnalyzer) -> None:
        """``from .widgets import make_widget`` resolves to the function handle."""
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        assert (
            _MAKE_WIDGET_FROM_IMPORTS_HANDLE in handles
        ), f"project symbol make_widget missing; got {handles}"

    def test_adjacents_are_handle_name_pairs(self, analyzer: JediAnalyzer) -> None:
        """Each adjacent is a (Handle, Jedi Name) pair — the Name carries goto info."""
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        assert result.adjacents, "imports_fixture should have adjacents"
        for handle, name in result.adjacents:
            assert isinstance(handle, Handle)
            # The goto def has a full_name matching the handle
            assert name.full_name == str(handle)

    def test_unresolved_call_sites_is_none(self, analyzer: JediAnalyzer) -> None:
        """The unresolved-call-site notion is callees-only; imports never reports it."""
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        assert result.unresolved_call_sites is None

    def test_deterministic_across_runs(self, analyzer: JediAnalyzer) -> None:
        """Results are deduplicated and sorted by handle string for stability."""
        first = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        second = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert first is not None and second is not None
        assert [str(h) for h in first.handles] == [str(h) for h in second.handles]
        # Verify it is the SORTED order (resolver sorts by handle string).
        handles = [str(h) for h in first.handles]
        assert handles == sorted(handles), f"not sorted by handle string: {handles}"

    def test_no_duplicates(self, analyzer: JediAnalyzer) -> None:
        """Dedup is enforced: no handle appears twice."""
        result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        handles = [str(h) for h in result.handles]
        assert len(handles) == len(set(handles)), f"duplicates found: {handles}"


class TestResolveImportsMeasuredEmpty:
    """A module with NO top-level imports → ``EdgeResult([])`` (measured none).

    This is the absence-vs-zero invariant: a module IS the right kind for this
    edge, but if it has no top-level imports the measured result is an empty
    adjacency — NOT the wrong-kind ``None`` signal.
    """

    def test_no_imports_module_is_measured_empty(self, analyzer: JediAnalyzer) -> None:
        # ``mypackage.helpers`` has NO top-level imports — only a class definition.
        # Verified by reading helpers.py: no ``import`` or ``from ... import`` lines.
        # This is the absence-vs-zero invariant: the module IS the right kind for
        # the ``imports`` edge, so we get a MEASURED empty ``EdgeResult([])`` — NOT
        # the wrong-kind ``None`` sentinel.
        result = _imports_for(_HELPERS_MODULE_HANDLE, analyzer)
        assert result is not None, "helpers module (right kind) must return EdgeResult, not None"
        assert (
            result.handles == []
        ), f"helpers has no top-level imports → measured empty; got {result.handles}"

    def test_measured_empty_is_not_none(self, analyzer: JediAnalyzer) -> None:
        """A module handle (even with imports) returns EdgeResult, NOT None."""
        # The critical distinction: any module must return an EdgeResult (not None).
        result = _imports_for(_MODULE_HANDLE, analyzer)
        assert result is not None, "module handle must NOT return wrong-kind None"
        assert isinstance(result, EdgeResult)


class TestResolveImportsNonModule:
    """A non-module handle → wrong-kind ``None`` (NOT ``EdgeResult([])``).

    This is the load-bearing #332 distinction (mirroring ``imported_by``): a
    function/class CAN have local imports, so returning ``EdgeResult([])`` would
    be the "measured zero" lie.  ``None`` signals "this edge does not apply to
    this kind" and becomes ``not_yet_implemented`` downstream in ``expand``.
    """

    def test_class_handle_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A class handle returns ``None`` (wrong kind for the imports edge)."""
        result = _imports_for(_WIDGET_HANDLE, analyzer)
        assert result is None, f"non-module handle must return None, got {result!r}"

    def test_function_handle_returns_none(self, analyzer: JediAnalyzer) -> None:
        """A function handle returns ``None`` (wrong kind for the imports edge)."""
        result = _imports_for(_MAKE_WIDGET_HANDLE, analyzer)
        assert result is None, f"non-module handle must return None, got {result!r}"

    def test_none_is_distinct_from_measured_empty(self, analyzer: JediAnalyzer) -> None:
        """The two empty-looking outcomes must be machine-distinguishable."""
        wrong_kind = _imports_for(_WIDGET_HANDLE, analyzer)
        # widgets module itself IS a module — returns EdgeResult (possibly with imports)
        module_result = _imports_for(_MODULE_HANDLE, analyzer)
        assert wrong_kind is None
        assert module_result is not None
        # They must differ: None vs EdgeResult
        assert wrong_kind != module_result


class TestResolveImportsNeverReverseSearch:
    """imports NEVER calls Jedi reverse search (forward goto only).

    Mirrors the callees/imported_by/subclasses/superclasses spies: patch
    ``get_references`` to explode if touched, run the resolver, then assert it
    completed (real imports present) AND the spy was never called.
    """

    def test_get_references_not_called(self, analyzer: JediAnalyzer) -> None:
        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on imports path"))
        with patch.object(jedi.Script, "get_references", spy):
            result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        assert result is not None
        assert _OS_MODULE_HANDLE in {str(h) for h in result.handles}
        spy.assert_not_called()


class TestResolveImportsMembersDisjoint:
    """The ``imports`` and ``members`` edges are disjoint for a module.

    ``_module_members`` deliberately excludes import-bound names (spec §3.3) so
    that ``members`` and ``imports`` don't overlap.  This test pins that contract
    for the ``imports_fixture`` module.
    """

    def test_imports_and_members_have_no_overlap(self, analyzer: JediAnalyzer) -> None:
        """No handle appears in BOTH the imports and members edge for the same module."""
        import_result = _imports_for(_IMPORTS_FIXTURE_HANDLE, analyzer)
        members_result = resolve_members(
            _find_jedi_name_for_handle(_IMPORTS_FIXTURE_HANDLE, analyzer),
            analyzer,
        )
        assert import_result is not None
        import_handles = {str(h) for h in import_result.handles}
        member_handles = {str(h) for h in members_result.handles}
        overlap = import_handles & member_handles
        assert not overlap, f"imports and members overlap for imports_fixture: {overlap}"


# ``direct_importer`` does ``import mypackage._core.widgets`` — a 3-component
# dotted import that exercises the rightmost-identifier column arithmetic.
_DIRECT_IMPORTER_HANDLE = "mypackage._core.direct_importer"
_WIDGETS_MODULE_HANDLE = "mypackage._core.widgets"

# ``wildcard_fixture`` pairs ``from .widgets import *`` (skipped) with
# ``import os`` (kept) — see its module docstring.
_WILDCARD_FIXTURE_HANDLE = "mypackage._core.wildcard_fixture"


class TestResolveImportsDottedPath:
    """``import a.b.c`` resolves to the RIGHTMOST module, not the top package.

    ``direct_importer`` does ``import mypackage._core.widgets`` (a 3-component
    dotted import).  The resolver's column arithmetic must land goto on the
    rightmost identifier (``widgets``) so it resolves to the full module path —
    a naive ``alias.col_offset`` would land on ``mypackage`` and resolve to the
    top package instead.
    """

    def test_dotted_resolves_to_rightmost_module(self, analyzer: JediAnalyzer) -> None:
        """The dotted import yields the FULL module handle, not the top package."""
        result = _imports_for(_DIRECT_IMPORTER_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        assert (
            _WIDGETS_MODULE_HANDLE in handles
        ), f"dotted import must resolve to full module path; got {handles}"

    def test_dotted_not_top_package(self, analyzer: JediAnalyzer) -> None:
        """Broken column arithmetic would land on ``mypackage`` (the first component)."""
        result = _imports_for(_DIRECT_IMPORTER_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        assert (
            "mypackage" not in handles
        ), f"dotted import wrongly resolved to top package; got {handles}"


class TestResolveImportsWildcard:
    """``from x import *`` is SKIPPED — wildcard targets are not enumerable.

    Pinned against ``wildcard_fixture``, which has ONE wildcard import and ONE
    ordinary import so both halves of the contract are checkable: the wildcard
    contributes nothing, yet the ordinary import is still measured.
    """

    def test_wildcard_targets_absent(self, analyzer: JediAnalyzer) -> None:
        """None of the names ``from .widgets import *`` binds appear as handles."""
        result = _imports_for(_WILDCARD_FIXTURE_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        leaked = {h for h in handles if h.startswith(f"{_WIDGETS_MODULE_HANDLE}.")}
        assert not leaked, f"wildcard target leaked into imports: {leaked}"

    def test_nonwildcard_import_still_resolved(self, analyzer: JediAnalyzer) -> None:
        """The ordinary ``import os`` proves the resolver ran past the wildcard."""
        result = _imports_for(_WILDCARD_FIXTURE_HANDLE, analyzer)
        assert result is not None
        handles = {str(h) for h in result.handles}
        assert _OS_MODULE_HANDLE in handles, f"ordinary import dropped; got {handles}"


# ---------------------------------------------------------------------------
# enclosing_scope resolver (#370) — Jedi parent() navigation, sync
# ---------------------------------------------------------------------------

# Fixture: nested_class_inspect/pkg/mod.py
# Topology:
#   pkg.mod (module)
#   pkg.mod.top_level_function    → enclosing scope: pkg.mod (module)
#   pkg.mod.Outer                 → enclosing scope: pkg.mod (module)
#   pkg.mod.Outer.outer_method    → enclosing scope: pkg.mod.Outer (class)
#   pkg.mod.Outer.Inner           → enclosing scope: pkg.mod.Outer (class)
#   pkg.mod.Outer.Inner.inner_method → enclosing scope: pkg.mod.Outer.Inner (class)
_NESTED_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "nested_class_inspect"

_TOP_LEVEL_FUNC_HANDLE = "pkg.mod.top_level_function"
_OUTER_CLASS_HANDLE = "pkg.mod.Outer"
_OUTER_METHOD_HANDLE = "pkg.mod.Outer.outer_method"
_INNER_CLASS_HANDLE = "pkg.mod.Outer.Inner"
_INNER_METHOD_HANDLE = "pkg.mod.Outer.Inner.inner_method"
_NESTED_MODULE_HANDLE = "pkg.mod"


@pytest.fixture
def nested_analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the nested_class_inspect fixture."""
    return JediAnalyzer(str(_NESTED_FIXTURE))


def _enclosing_scope_for(handle: str, analyzer: JediAnalyzer) -> EdgeResult:
    """Resolve *handle* to a Jedi name and return its ``enclosing_scope`` result.

    ``enclosing_scope`` is synchronous (Jedi ``parent()`` + ``Handle`` construction
    are sync) and NEVER returns ``None`` — a non-module has a lexical enclosing
    scope; a module has none (``EdgeResult([])``) but still not ``None``.
    """
    from pyeye.mcp.operations.edges import resolve_enclosing_scope

    jedi_name = _find_jedi_name_for_handle(handle, analyzer)
    assert jedi_name is not None, f"Could not find Jedi name for handle {handle!r}"
    return resolve_enclosing_scope(jedi_name, analyzer)


class TestResolveEnclosingScopeMethod:
    """A method → its enclosing class handle (the direct lexical parent)."""

    def test_outer_method_scope_is_outer_class(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod.Outer.outer_method → enclosing scope pkg.mod.Outer."""
        result = _enclosing_scope_for(_OUTER_METHOD_HANDLE, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert len(result.handles) == 1
        assert str(result.handles[0]) == _OUTER_CLASS_HANDLE

    def test_inner_method_scope_is_inner_class(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod.Outer.Inner.inner_method → enclosing scope pkg.mod.Outer.Inner."""
        result = _enclosing_scope_for(_INNER_METHOD_HANDLE, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert len(result.handles) == 1
        assert (
            str(result.handles[0]) == _INNER_CLASS_HANDLE
        )  # immediate parent only — NOT the grandparent Outer

    def test_adjacent_is_handle_name_pair(self, nested_analyzer: JediAnalyzer) -> None:
        """The adjacent must be a (Handle, Name) pair (not just a handle)."""
        result = _enclosing_scope_for(_OUTER_METHOD_HANDLE, nested_analyzer)
        assert len(result.adjacents) == 1
        h, name = result.adjacents[0]
        assert isinstance(h, Handle)
        # The Jedi Name must carry a type attribute (it's a real Name, not a stub).
        assert getattr(name, "type", None) is not None


class TestResolveEnclosingScopeNestedClass:
    """A nested class → its enclosing class handle."""

    def test_inner_class_scope_is_outer_class(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod.Outer.Inner → enclosing scope pkg.mod.Outer (its parent class)."""
        result = _enclosing_scope_for(_INNER_CLASS_HANDLE, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert len(result.handles) == 1
        assert str(result.handles[0]) == _OUTER_CLASS_HANDLE


class TestResolveEnclosingScopeTopLevel:
    """A top-level def/class → its enclosing module handle."""

    def test_top_level_function_scope_is_module(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod.top_level_function → enclosing scope pkg.mod (the module)."""
        result = _enclosing_scope_for(_TOP_LEVEL_FUNC_HANDLE, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert len(result.handles) == 1
        assert str(result.handles[0]) == _NESTED_MODULE_HANDLE

    def test_outer_class_scope_is_module(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod.Outer → enclosing scope pkg.mod (the module)."""
        result = _enclosing_scope_for(_OUTER_CLASS_HANDLE, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert len(result.handles) == 1
        assert str(result.handles[0]) == _NESTED_MODULE_HANDLE


class TestResolveEnclosingScopeModule:
    """A module → EdgeResult([]) (no enclosing lexical scope)."""

    def test_module_has_no_enclosing_scope(self, nested_analyzer: JediAnalyzer) -> None:
        """pkg.mod has no lexical enclosing scope → EdgeResult([])."""
        from pyeye._module_sentinel import ModuleSentinel
        from pyeye.mcp.operations.edges import resolve_enclosing_scope

        # Build a ModuleSentinel for the module handle — the resolver gates on
        # _normalise_kind, which returns "module" for a sentinel.
        fixture_file = _NESTED_FIXTURE / "pkg" / "mod.py"
        sentinel = ModuleSentinel(fixture_file, _NESTED_MODULE_HANDLE, nested_analyzer)
        result = resolve_enclosing_scope(sentinel, nested_analyzer)
        assert isinstance(result, EdgeResult)
        assert (
            result.handles == []
        ), f"module has no enclosing lexical scope → EdgeResult([]); got {result.handles}"

    def test_module_returns_edgeresult_not_none(self, nested_analyzer: JediAnalyzer) -> None:
        """resolver NEVER returns None — module yields EdgeResult([]), not None."""
        from pyeye._module_sentinel import ModuleSentinel
        from pyeye.mcp.operations.edges import resolve_enclosing_scope

        fixture_file = _NESTED_FIXTURE / "pkg" / "mod.py"
        sentinel = ModuleSentinel(fixture_file, _NESTED_MODULE_HANDLE, nested_analyzer)
        result = resolve_enclosing_scope(sentinel, nested_analyzer)
        assert result is not None, "resolver must never return None"


class TestResolveEnclosingScopeNeverReverseSearch:
    """enclosing_scope NEVER calls Jedi reverse search (parent() only).

    Mirrors the callees/imported_by/subclasses/superclasses/imports spies:
    patch ``get_references`` to explode if touched, run the resolver on a
    method (which has a real enclosing scope), then assert it completed AND the
    spy was never called.
    """

    def test_get_references_not_called(self, nested_analyzer: JediAnalyzer) -> None:
        from pyeye.mcp.operations.edges import resolve_enclosing_scope

        assert hasattr(jedi.Script, "get_references")
        spy = Mock(side_effect=AssertionError("get_references called on enclosing_scope path"))
        with patch.object(jedi.Script, "get_references", spy):
            jedi_name = _find_jedi_name_for_handle(_OUTER_METHOD_HANDLE, nested_analyzer)
            assert jedi_name is not None
            result = resolve_enclosing_scope(jedi_name, nested_analyzer)
        # The resolver must have run (method → its class) and never touched reverse search.
        assert len(result.handles) == 1
        assert str(result.handles[0]) == _OUTER_CLASS_HANDLE
        spy.assert_not_called()


class TestResolveEnclosingScopeParentNoneDefensive:
    """Defensive branch: ``parent()`` returning ``None`` yields ``EdgeResult([])``.

    This test exercises the explicit ``if parent is None`` guard in
    ``resolve_enclosing_scope`` (edges.py).  The guard is defensive — it handles
    a Jedi API failure mode where ``parent()`` returns ``None`` for a non-module
    symbol.  A Mock is used to force the branch deterministically; the happy
    paths already use real fixtures.
    """

    def test_parent_returns_none_yields_empty_edgeresult(self) -> None:
        """When ``parent()`` returns ``None``, resolver returns ``EdgeResult([])`` — never raises."""
        from unittest.mock import MagicMock

        from pyeye.mcp.operations.edges import resolve_enclosing_scope

        # Construct a mock Jedi Name with a non-module kind so the module gate
        # does not short-circuit before reaching the parent() call.
        mock_jedi_name = MagicMock()
        mock_jedi_name.type = "function"
        mock_jedi_name.parent.return_value = None  # force the defensive branch

        result = resolve_enclosing_scope(mock_jedi_name, analyzer=MagicMock())
        assert isinstance(result, EdgeResult)
        assert result.adjacents == []  # empty, not None
        assert result is not None  # resolver NEVER returns None
