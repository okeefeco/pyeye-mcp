"""Byte-identical guard for the #405 ``find_subclasses`` resolution rewrite.

Pins the FULL subclass closure of ``pkg.core.Root`` across every base-resolution
form — direct / aliased / dotted / re-export / indirect. This must stay GREEN
through the cold-build rewrite: it's the safety net proving the AST-first
resolver reproduces Jedi's resolution on the paths the ``subclasses_edge``
fixture does not cover.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_resolution"
_ROOT_HANDLE = "pkg.core.Root"
_EXPECTED_CLOSURE = {
    "consumers.Direct",  # direct-name base, direct import
    "consumers.Aliased",  # `as R` alias
    "consumers.Dotted",  # `core.Root` dotted reference
    "consumers.ViaReexport",  # base via `pkg.Root` re-export
    "consumers.GrandChild",  # indirect, through the resolved Direct child
}


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """Analyzer pointed at the dedicated resolution-forms fixture."""
    return JediAnalyzer(str(_FIXTURE))


@pytest.mark.asyncio
async def test_root_closure_covers_all_resolution_forms(analyzer: JediAnalyzer) -> None:
    result = await expand(_ROOT_HANDLE, "subclasses", analyzer)
    handles = {stub["handle"] for stub in result["stubs"]}
    assert handles == _EXPECTED_CLOSURE, f"got {handles}"
