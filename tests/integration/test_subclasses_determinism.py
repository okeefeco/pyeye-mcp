"""Cross-process determinism guard for ``find_subclasses`` base resolution (#419).

``find_subclasses`` resolves each class base AST-first (``resolve_base`` —
deterministic) and falls back to Jedi forward ``goto`` only when the AST cannot
commit. Jedi ``goto`` is known to return *different* targets across fresh
processes for some bases (conditional imports, package re-exports) — a
hash-seed / cache-state dependence (#419), distinct from the reverse-reference
non-determinism behind the Pyright backend (#333).

This pins the property that, on a fixture exercising BOTH paths — ``ChildAst``
(top-level import → AST) and ``ChildGoto`` (``TYPE_CHECKING`` import → ``goto``
fallback) — the subclass set is identical across processes started with
different ``PYTHONHASHSEED``.

It is a regression guard: today the property holds (project bases that fall back
to ``goto`` still resolve to a stable in-project target), so the test passes. A
future change that makes resolution order- or seed-dependent fails here. The bug
is cross-*process*, so the runs are real subprocesses — in-process re-runs share
the interpreter's hash seed and Jedi's inference cache and would not catch it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "determinism_subclasses"
_BASE = "pkg.base.Base"
_EXPECTED = ["pkg.child_ast.ChildAst", "pkg.child_goto.ChildGoto"]

# Runs find_subclasses and prints the sorted subclass FQNs as a single JSON line.
# Executed in a fresh interpreter so each invocation gets its own hash seed and
# Jedi cache state.
_RUNNER = """
import asyncio, json, sys
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.config import ProjectConfig


async def main():
    project, base = sys.argv[1], sys.argv[2]
    analyzer = JediAnalyzer(project, config=ProjectConfig(project))
    res = await analyzer.find_subclasses(base, scope="main", include_indirect=True)
    print("RESULT:" + json.dumps(sorted(s["full_name"] for s in res["subclasses"])))


asyncio.run(main())
"""


def _run_in_subprocess(hashseed: str) -> list[str]:
    """Run the fixture query in a fresh interpreter with a fixed PYTHONHASHSEED."""
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    proc = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(_FIXTURE), _BASE],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, f"runner failed (PYTHONHASHSEED={hashseed}):\n{proc.stderr}"
    line = next(line for line in proc.stdout.splitlines() if line.startswith("RESULT:"))
    return json.loads(line[len("RESULT:") :])


def test_find_subclasses_stable_across_process_hash_seeds() -> None:
    """The subclass set is identical across processes with different hash seeds.

    Asserts both the expected membership (so the test fails loudly if resolution
    breaks entirely) AND equality across seeds (the determinism property #419).
    ``ChildGoto`` is the load-bearing case: it is attributed only via the Jedi
    ``goto`` fallback, the path prone to cross-process drift.
    """
    results = {seed: _run_in_subprocess(seed) for seed in ("0", "1", "424242")}

    for seed, subs in results.items():
        assert subs == _EXPECTED, f"unexpected subclasses (PYTHONHASHSEED={seed}): {subs}"

    distinct = {tuple(subs) for subs in results.values()}
    assert len(distinct) == 1, f"non-deterministic across hash seeds: {results}"
