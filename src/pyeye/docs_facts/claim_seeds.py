"""The honest-claims rule's seeds: unbacked claims that predate it (D12, #844).

Each page's claims, keyed on the exact finding message (the claim and the
prose line it's on, one entry per occurrence), so a seed covers that claim in
that sentence and nothing else. They are an allow-list that only
shrinks: #830 binds each claim to a fact or a record, or deletes it, and
removes its entry here in the same PR. Never add one.
"""

from __future__ import annotations

SEEDS: dict[str, tuple[str, ...]] = {
    ".claude/skills/pyeye-scenarios/SKILL.md": (
        "unbacked size '350 KB': SHA. The jaraco repos are ~350 KB each (free), so a per-worktree clone is trivial.",
        "unbacked size '366 MB': django is ~366 MB — to avoid re-downloading it per worktree, clone with",
        "unbacked size '366 MB': | size | ~366 MB — clone with ** ** (or set to a shared cache) to avoid a full per-worktree downl...",
        "unbacked size '333 MB': ### Probe suite + recorded baseline *(re-captured 2026-11-16, build = main @ after #782, ; caches...",
        "unbacked duration '21 s': All five are identical on an in-process repeat. Timings on (main @ , after PR #805): the first ta...",
        "unbacked duration '31 s': All five are identical on an in-process repeat. Timings on (main @ , after PR #805): the first ta...",
        "unbacked duration '0.4 s': All five are identical on an in-process repeat. Timings on (main @ , after PR #805): the first ta...",
        "unbacked size '335 MB': caches as the probes above, max RSS 335 MB, 1m23s wall time including the",
        "unbacked duration '0.04 s': - **Project stubs** (51): has a median of 0.04 s, 8.2 s in total. The",
        "unbacked duration '8.2 s': - **Project stubs** (51): has a median of 0.04 s, 8.2 s in total. The",
        "unbacked duration '2.95 s': slowest is at 2.95 s; the next is",
        "unbacked duration '0.39 s': at 0.39 s. is",
        "unbacked duration '0.19 s': ≤0.19 s.",
        "unbacked duration '0.97 s': - **External stubs** (6): is ≤0.97 s ( ).",
        "unbacked duration '10 s': - On every project stub took 8–10 s, because the",
        "unbacked duration '0.5 s': above ~0.5 s, if any single project stub exceeds ~5 s, or if the round-trip's",
        "unbacked duration '5 s': above ~0.5 s, if any single project stub exceeds ~5 s, or if the round-trip's",
        "unbacked duration '5 min': wall time exceeds ~5 min. Any of these most likely means #795's or #803's cost is back:",
        "unbacked duration '3 s': (#803's profile). 's ~3 s is today's ceiling, and it isn't profiled. For",
        "unbacked duration '1.2 s': at 0.5–1.2 s, most of it Jedi inference.",
    ),
    "docs/architecture/resolution.md": (
        "unbacked percentage '7%': roughly 7% of bases on Django (#419).",
    ),
    "scripts/claude_hooks/README.md": (
        "unbacked duration '7 days': Period: Last 7 days",
        "unbacked percentage '87.2%': 🎯 MCP Adoption Rate: 87.2%",
        "unbacked percentage '30%': - **Week 1**: Establish baseline, >30% MCP usage ✅",
        "unbacked percentage '50%': - **Week 2**: >50% MCP usage ✅",
        "unbacked percentage '70%': - **Week 3**: >70% MCP usage ✅",
        "unbacked percentage '80%': - **Week 4**: >80% MCP usage 🎯",
    ),
}
