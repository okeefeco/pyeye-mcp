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

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.handle import Handle
from pyeye.mcp.operations.edges import (
    EdgeResult,
    edge_status,
    resolve_callees,
    resolve_members,
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
        ["superclasses", "subclasses", "imports", "enclosing_scope"],
    )
    def test_not_yet_implemented_edges(self, edge: str) -> None:
        assert edge_status(edge) == "not_yet_implemented"

    @pytest.mark.parametrize(
        "edge",
        [
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
