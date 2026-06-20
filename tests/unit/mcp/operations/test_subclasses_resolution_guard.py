"""Byte-identical guard for the #405 ``find_subclasses`` resolution rewrite.

Pins the subclass resolution of ``pkg.core.Root`` across every base-resolution
form — direct / aliased / dotted / re-export / indirect. This must stay GREEN
through the cold-build rewrite: it's the safety net proving the AST-first
resolver reproduces Jedi's resolution on the paths the ``subclasses_edge``
fixture does not cover.

Since #422 the ``subclasses`` edge is DIRECT-only, so the guard is split: the
edge pins the five DIRECT resolution forms, and ``trace`` (which now owns the
transitive closure) pins the full set including the INDIRECT grandchild — every
form stays covered, on the surface where it now lives.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.trace import trace

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_resolution"
_ROOT_HANDLE = "pkg.core.Root"
#: The five DIRECT (depth-1) subclasses of Root, one per base-resolution form.
_EXPECTED_DIRECT = {
    "consumers.Direct",  # direct-name base, direct import
    "consumers.Aliased",  # `as R` alias (top-level)
    "consumers.Dotted",  # `core.Root` dotted reference
    "consumers.ViaReexport",  # base via `pkg.Root` re-export
    "conditional.ConditionalAlias",  # `as` alias imported under try/except (Jedi-fallback path)
}
#: The full closure adds the one INDIRECT form (grandchild through Direct).
_EXPECTED_CLOSURE = _EXPECTED_DIRECT | {"consumers.GrandChild"}


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """Analyzer pointed at the dedicated resolution-forms fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.mark.asyncio
async def test_root_direct_covers_all_direct_resolution_forms(analyzer: JediAnalyzer) -> None:
    # The direct-only edge resolves every DIRECT base form; the indirect
    # grandchild is excluded (it is reached via trace — see below).
    result = await expand(_ROOT_HANDLE, "subclasses", analyzer)
    handles = {stub["handle"] for stub in result["stubs"]}
    assert handles == _EXPECTED_DIRECT, f"got {handles}"


@pytest.mark.asyncio
async def test_root_closure_covers_all_resolution_forms(analyzer: JediAnalyzer) -> None:
    # trace owns the transitive closure (#422); a generous depth must reproduce
    # the full #405 set INCLUDING the indirect grandchild form.
    result = await trace(_ROOT_HANDLE, ["subclasses"], analyzer, max_depth=5, max_nodes=100)
    # The start handle is part of the subgraph nodes; the closure is the rest.
    handles = set(result["nodes"]) - {_ROOT_HANDLE}
    assert handles == _EXPECTED_CLOSURE, f"got {handles}"
