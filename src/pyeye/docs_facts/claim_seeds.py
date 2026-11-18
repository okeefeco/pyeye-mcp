"""The honest-claims rule's seeds: unbacked claims that predate it (D12, #844).

Each page's claims, keyed on the exact finding message (the claim and the
prose line it's on, one entry per occurrence), so a seed covers that claim in
that sentence and nothing else. They are an allow-list that only
shrinks: #830 binds each claim to a fact or a record, or deletes it, and
removes its entry here in the same PR. Never add one.
"""

from __future__ import annotations

SEEDS: dict[str, tuple[str, ...]] = {
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
