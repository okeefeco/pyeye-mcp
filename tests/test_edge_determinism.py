"""Edge determinism conformance, driven by the registry (#452).

Every implemented edge declares a tier in ``edges.EDGE_DETERMINISM``, and this
module holds it to that tier's contract (``edges.DETERMINISM_MEANINGS``):

1. **Registry**: every edge in ``EDGE_RESOLVERS`` has a tier and every tier a
   meaning, so a new edge can't ship without saying how deterministic it is.
2. **Rebuild**: each edge gives the same full result after every cache and
   index is dropped and a fresh analyzer is built (the #445 trigger).
3. **No Jedi**: the ``filesystem`` and ``ast`` edges give the same adjacents
   with Jedi's lookups made to raise while the resolver runs, so neither can
   start re-deriving its adjacents through Jedi (the #445 pattern).
4. **Cross-process**: two fresh interpreters with different ``PYTHONHASHSEED``
   give the same results: everything for ``filesystem``, ``ast`` and
   ``jedi_local``; the project-scope stubs for ``goto``, whose external
   targets may differ (#419).
5. **Symmetry**: ``C`` is in ``subclasses(B)`` exactly when ``B`` is in
   ``superclasses(C)``.

The fixture, ``tests/fixtures/determinism_traps``, gives every edge a source and
holds the two known traps (its README). ``subclasses`` falls into both today
(#1057): the project-shim case is a strict expected failure below, and the
stdlib-shim case, which passes in some processes, is excluded from the
rebuild and cross-process comparisons in :data:`_KNOWN_1057`. Fixing #1057 turns the strict
case green and must empty that set.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from inspect import isawaitable
from pathlib import Path
from typing import Any

import jedi
import pytest

from pyeye import file_artifact_cache
from pyeye.analyzers import project_graph
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations import edges
from pyeye.mcp.operations.edges import (
    DETERMINISM_MEANINGS,
    EDGE_DETERMINISM,
    EDGE_RESOLVERS,
)
from pyeye.mcp.operations.expand import expand

_FIXTURE = Path(__file__).parent / "fixtures" / "determinism_traps"

#: Every source the checks expand, each along every edge (wrong kinds answer
#: ``not_applicable``, which must repeat too).
_SOURCES = (
    "pkg",
    "pkg.core",
    "pkg.core.Widget",
    "pkg.core.Widget.grow",
    "pkg.core.Widget.size",
    "pkg.core.helper",
    "pkg._fast",
    "pkg._fast.Local",
    "pkg._slow",
    "pkg._slow.Local",
    "pkg.shim",
    "pkg.users",
    "pkg.users.ThreadState",
    "pkg.users.ShimChild",
    "pkg.users.Gadget",
    "pkg.users.make",
    "pkg.sub",
    "pkg.sub.leaf",
    "_threading_local.local",
)

#: Probes ``subclasses`` gets wrong today (#1057): their bases are named
#: through a try/except shim, and the class graph keys each through whichever
#: branch Jedi's goto picks, which can change on a rebuild in the same process,
#: not only between processes. The rebuild and cross-process checks skip them.
#: Fixing #1057 empties it.
_KNOWN_1057 = frozenset(
    {
        ("pkg._fast.Local", "subclasses"),
        ("pkg._slow.Local", "subclasses"),
        ("_threading_local.local", "subclasses"),
    }
)

_BASES = ("pkg.core.Widget", "pkg._fast.Local", "pkg._slow.Local", "_threading_local.local")


def _fresh_analyzer() -> JediAnalyzer:
    """An analyzer with every cache and index dropped, as a new session has."""
    file_artifact_cache.invalidate_all()
    project_graph.invalidate()
    return JediAnalyzer(_FIXTURE.as_posix())


async def _expand_all(analyzer: JediAnalyzer) -> dict[str, Any]:
    return {
        f"{source}|{edge}": await expand(source, edge, analyzer)
        for source in _SOURCES
        for edge in EDGE_RESOLVERS
    }


def _handles(result: dict[str, Any]) -> list[str]:
    return [s["handle"] for s in result.get("stubs") or []]


# ---------------------------------------------------------------------------
# 1. Registry
# ---------------------------------------------------------------------------


def test_every_edge_has_a_tier_and_every_tier_a_meaning() -> None:
    assert set(EDGE_DETERMINISM) == set(EDGE_RESOLVERS)
    assert set(EDGE_DETERMINISM.values()) == set(DETERMINISM_MEANINGS)


def test_known_1057_skip_set_only_shrinks() -> None:
    """The skip set holds exactly #1057's shim probes; nothing else may hide in it.

    A ratchet: adding an unrelated flaky probe to quiet the rebuild or
    cross-process check fails here. #1057's fix deletes every entry and this
    expected set with them.
    """
    assert {
        ("pkg._fast.Local", "subclasses"),
        ("pkg._slow.Local", "subclasses"),
        ("_threading_local.local", "subclasses"),
    } == _KNOWN_1057


async def test_every_edge_is_exercised_by_the_fixture() -> None:
    """Each edge has a source with stubs, so no check below passes vacuously."""
    results = await _expand_all(_fresh_analyzer())
    empty = [e for e in EDGE_RESOLVERS if not any(_handles(results[f"{s}|{e}"]) for s in _SOURCES)]
    assert empty == []


# ---------------------------------------------------------------------------
# 2. Rebuild
# ---------------------------------------------------------------------------


async def test_every_edge_repeats_after_a_cache_rebuild() -> None:
    first = await _expand_all(_fresh_analyzer())
    second = await _expand_all(_fresh_analyzer())
    differ = sorted(
        k for k in first if first[k] != second[k] and tuple(k.split("|")) not in _KNOWN_1057
    )
    assert differ == []


# ---------------------------------------------------------------------------
# 3. No Jedi for the filesystem and ast tiers
# ---------------------------------------------------------------------------

_JEDI_LOOKUPS = (
    (jedi.Script, "goto"),
    (jedi.Script, "infer"),
    (jedi.Script, "get_names"),
    (jedi.Script, "search"),
    (jedi.Script, "complete"),
    (jedi.Script, "get_context"),
    (jedi.api.classes.BaseName, "goto"),
    (jedi.api.classes.BaseName, "infer"),
    (jedi.api.classes.BaseName, "parent"),
    (jedi.api.classes.Name, "defined_names"),
)


class _JediCalled(AssertionError):
    """A Jedi lookup ran inside a resolver that must not use Jedi."""


@contextmanager
def _no_jedi(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    with monkeypatch.context() as patch:
        for owner, name in _JEDI_LOOKUPS:

            def refuse(*_args: Any, _name: str = name, **_kwargs: Any) -> Any:
                raise _JediCalled(f"Jedi {_name}() called")

            patch.setattr(owner, name, refuse)
        yield


_NO_JEDI_EDGES = sorted(e for e, tier in EDGE_DETERMINISM.items() if tier in {"filesystem", "ast"})


@pytest.mark.parametrize("edge", _NO_JEDI_EDGES)
async def test_filesystem_and_ast_edges_need_no_jedi(
    edge: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver runs with Jedi's lookups refusing; its stubs don't change.

    Only the resolver call is guarded: resolving the source handle and building
    each stub may use Jedi, but which adjacents exist may not.
    """
    analyzer = _fresh_analyzer()
    expected = {s: _handles(await expand(s, edge, analyzer)) for s in _SOURCES}
    original = EDGE_RESOLVERS[edge]

    async def guarded(jedi_name: Any, an: JediAnalyzer) -> edges.EdgeResult:
        with _no_jedi(monkeypatch):
            raw = original(jedi_name, an)
            return await raw if isawaitable(raw) else raw

    monkeypatch.setitem(EDGE_RESOLVERS, edge, guarded)
    analyzer = _fresh_analyzer()
    got = {s: _handles(await expand(s, edge, analyzer)) for s in _SOURCES}
    assert got == expected
    assert any(expected.values()), f"{edge} produced no stubs to compare"


def test_no_jedi_guard_catches_a_jedi_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard itself works: a lookup inside it raises."""
    script = jedi.Script("x = 1\n")
    with _no_jedi(monkeypatch), pytest.raises(_JediCalled):
        script.get_names()


# ---------------------------------------------------------------------------
# 4. Cross-process
# ---------------------------------------------------------------------------

#: Expands every probe in a fresh interpreter and prints the results as JSON.
_RUNNER = """
import asyncio, json, logging, sys
logging.disable(logging.CRITICAL)
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp.operations.expand import expand


async def main():
    root, probes = sys.argv[1], json.loads(sys.argv[2])
    analyzer = JediAnalyzer(root)
    out = {f"{s}|{e}": await expand(s, e, analyzer) for s, e in probes}
    print("RESULT:" + json.dumps(out, sort_keys=True))


asyncio.run(main())
"""


def _run_in_subprocess(hashseed: str) -> dict[str, Any]:
    probes = [(s, e) for s in _SOURCES for e in EDGE_RESOLVERS]
    proc = subprocess.run(
        [sys.executable, "-c", _RUNNER, _FIXTURE.as_posix(), json.dumps(probes)],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONHASHSEED=hashseed),
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, f"runner failed (PYTHONHASHSEED={hashseed}):\n{proc.stderr}"
    line = next(x for x in proc.stdout.splitlines() if x.startswith("RESULT:"))
    return json.loads(line[len("RESULT:") :])  # type: ignore[no-any-return]


def _contract_view(edge: str, result: dict[str, Any]) -> Any:
    """The part of *result* its edge's tier guarantees across processes."""
    if EDGE_DETERMINISM[edge] != "goto" or not result.get("stubs"):
        return result
    return [s for s in result["stubs"] if s.get("scope") == "project"]


@pytest.fixture(scope="module")
def two_processes() -> tuple[dict[str, Any], dict[str, Any]]:
    return _run_in_subprocess("0"), _run_in_subprocess("1")


def test_every_edge_meets_its_tier_across_processes(
    two_processes: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    first, second = two_processes
    assert set(first) == set(second)
    differ = []
    for key in sorted(first):
        source, edge = key.split("|")
        if (source, edge) in _KNOWN_1057:
            continue
        if _contract_view(edge, first[key]) != _contract_view(edge, second[key]):
            differ.append(key)
    assert differ == []


def test_cross_process_check_sees_project_stubs(
    two_processes: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    """Each tier compares real stubs, so the check above isn't vacuous for goto."""
    first, _ = two_processes
    for tier in DETERMINISM_MEANINGS:
        tier_edges = [e for e, t in EDGE_DETERMINISM.items() if t == tier]
        views = [
            _contract_view(e, first[f"{s}|{e}"])
            for s in _SOURCES
            for e in tier_edges
            if (s, e) not in _KNOWN_1057
        ]
        assert any(v.get("stubs") if isinstance(v, dict) else v for v in views), tier


# ---------------------------------------------------------------------------
# 5. Symmetry of subclasses and superclasses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        "pkg.core.Widget",
        "pkg.users.Gadget",
        pytest.param(
            "pkg.users.ShimChild",
            marks=pytest.mark.xfail(
                strict=True,
                reason="#1057: subclasses keys the shim base through one goto branch",
            ),
        ),
    ],
)
async def test_subclasses_and_superclasses_agree(cls: str) -> None:
    """``cls`` is under ``subclasses(B)`` exactly when ``B`` is in ``superclasses(cls)``.

    ``ShimChild`` fails in every process: its superclasses are unresolved, yet
    the class graph files it under one of the two ``Local`` classes. The stdlib
    case, ``ThreadState``, isn't here: it agrees in some processes, so it would
    pass a strict expected failure by chance (it's in :data:`_KNOWN_1057`).
    """
    analyzer = _fresh_analyzer()
    supers = set(_handles(await expand(cls, "superclasses", analyzer)))
    under = {b for b in _BASES if cls in _handles(await expand(b, "subclasses", analyzer))}
    assert under == supers & set(_BASES)
