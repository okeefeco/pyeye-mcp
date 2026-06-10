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
