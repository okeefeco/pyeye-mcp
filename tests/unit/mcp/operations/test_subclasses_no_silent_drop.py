"""``expand(subclasses)`` must not silently drop find_subclasses results (#445).

``resolve_subclasses`` used to re-derive a Jedi ``Name`` per subclass (via
``get_script``/``get_names`` + ``full_name`` match) and drop any subclass whose
``Name`` it could not rebuild. Under a warm/partial Jedi inference state (cache
thrash on a large project) ``full_name`` comes back differently or ``None``, so
the match failed and ~half the results were silently dropped — non-deterministic
across result-cache rebuilds. ``find_subclasses`` already returns the
deterministic AST FQN + file + line, so the resolver now builds the stub from
that directly (a ``ClassSentinel``) and never drops.

These guards encode the fix's contract: full parity with ``find_subclasses`` and
no drop even when per-subclass Jedi resolution is unavailable.
"""

from pathlib import Path

import pytest

import pyeye.file_artifact_cache as file_artifact_cache
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.edges import resolve_subclasses
from pyeye.mcp.operations.expand import expand
from pyeye.mcp.operations.inspect import _find_jedi_name_for_handle
from pyeye.mcp.operations.trace import trace

_SUBCLASSES_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "subclasses_edge"
_ANIMAL_HANDLE = "pkg.base.Animal"


@pytest.fixture
def subclasses_analyzer() -> JediAnalyzer:
    return JediAnalyzer(str(_SUBCLASSES_FIXTURE))


def _fake_subclass(full_name: str, rel_file: str, line: int) -> dict:
    """A find_subclasses-shaped subclass dict."""
    return {
        "name": full_name.split(".")[-1],
        "full_name": full_name,
        "file": (_SUBCLASSES_FIXTURE / rel_file).as_posix(),
        "line": line,
        "column": 0,
        "end_line": line + 2,
        "direct_parent": "Animal",
        "is_direct": True,
    }


@pytest.mark.asyncio
async def test_resolve_subclasses_keeps_all_when_jedi_name_unavailable(
    subclasses_analyzer: JediAnalyzer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No subclass is dropped even when per-symbol Jedi resolution fails.

    Stubs ``find_subclasses`` to a fixed, known set (the deterministic ground
    truth) and forces the Jedi ``get_script`` path to raise — simulating the
    warm-state drift / cache thrash that made the old re-derivation return
    ``None``. The old code dropped every adjacency here; the sentinel-based
    resolver must return the full set.
    """
    jedi_name = _find_jedi_name_for_handle(_ANIMAL_HANDLE, subclasses_analyzer)
    assert jedi_name is not None

    ground_truth = [
        _fake_subclass("pkg.middle.Mammal", "pkg/middle.py", 5),
        _fake_subclass("pkg.middle.Reptile", "pkg/middle.py", 12),
        _fake_subclass("script_animal.Lizard", "script_animal.py", 3),
    ]

    async def fake_find_subclasses(*_args: object, **_kwargs: object) -> dict:
        return {"ambiguous": False, "subclasses": ground_truth}

    monkeypatch.setattr(subclasses_analyzer, "find_subclasses", fake_find_subclasses)

    def boom(*_args: object, **_kwargs: object):
        raise RuntimeError("simulated get_script rebuild failure (warm-state drift)")

    # Patch the symbol edges.py resolves through (it does `from pyeye import
    # file_artifact_cache`), so only the post-filter's Jedi path is degraded.
    monkeypatch.setattr(file_artifact_cache, "get_script", boom)

    result = await resolve_subclasses(jedi_name, subclasses_analyzer)
    handles = sorted(str(h) for h, _ in result.adjacents)

    assert handles == [
        "pkg.middle.Mammal",
        "pkg.middle.Reptile",
        "script_animal.Lizard",
    ], "every find_subclasses result must survive; none silently dropped (#445)"


@pytest.mark.asyncio
async def test_expand_subclasses_matches_find_subclasses_set(
    subclasses_analyzer: JediAnalyzer,
) -> None:
    """expand(subclasses) returns exactly the find_subclasses direct set (parity)."""
    ground_truth = await subclasses_analyzer.find_subclasses(
        _ANIMAL_HANDLE, scope="main", include_indirect=False
    )
    gt_handles = {s["full_name"] for s in ground_truth["subclasses"]}

    result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
    expand_handles = {stub["handle"] for stub in result["stubs"]}

    assert expand_handles == gt_handles, (
        f"expand(subclasses) must equal find_subclasses set; "
        f"missing={gt_handles - expand_handles} extra={expand_handles - gt_handles}"
    )


@pytest.mark.asyncio
async def test_expand_subclasses_stable_across_artifact_cache_clear(
    subclasses_analyzer: JediAnalyzer,
) -> None:
    """Membership is identical across an artifact-cache rebuild (#445 criterion 2)."""
    first = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
    file_artifact_cache.invalidate_all()
    second = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)

    assert [s["handle"] for s in first["stubs"]] == [s["handle"] for s in second["stubs"]]


@pytest.mark.asyncio
async def test_subclass_stub_carries_real_end_line(
    subclasses_analyzer: JediAnalyzer,
) -> None:
    """A subclass stub's line_end is the class's real end line, not collapsed (#445)."""
    result = await expand(_ANIMAL_HANDLE, "subclasses", subclasses_analyzer)
    assert result["stubs"], "Animal has subclasses"
    for stub in result["stubs"]:
        assert stub["line_end"] >= stub["line_start"]
    # At least one multi-line subclass should report a span (end strictly past start).
    assert any(
        stub["line_end"] > stub["line_start"] for stub in result["stubs"]
    ), "expected at least one subclass to carry a real multi-line span"


@pytest.mark.asyncio
async def test_trace_subclasses_depth_2_round_trips_the_sentinel(
    subclasses_analyzer: JediAnalyzer,
) -> None:
    """trace(subclasses, depth=2) reaches the grandchild — the ClassSentinel
    must round-trip as a RESOLVER INPUT at hop 2 (#445).

    ``_single_hop`` carries each hop's adjacent ``Name`` forward as the input to
    the next hop's resolver. ``resolve_subclasses`` reads ``.type`` and
    ``.full_name`` off it to recurse, so a sentinel that built a valid stub but
    did NOT round-trip would silently return nothing past depth 1 — a new
    firehose-of-emptiness the expand-only tests can't see. The grandchild
    ``pkg.middle.Dog`` is reachable only if the hop-1 sentinel for ``Mammal`` is
    accepted as a resolver input.
    """
    result = await trace(
        _ANIMAL_HANDLE, ["subclasses"], subclasses_analyzer, max_depth=2, max_nodes=100
    )
    nodes = set(result["nodes"])
    assert "pkg.middle.Mammal" in nodes, "direct subclass at depth 1"
    assert "pkg.middle.Dog" in nodes, (
        "grandchild reachable only if the hop-1 ClassSentinel round-trips as a "
        "resolver input (#445)"
    )
