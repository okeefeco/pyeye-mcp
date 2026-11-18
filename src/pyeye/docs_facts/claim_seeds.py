"""The honest-claims rule's seeds: unbacked claims that predate it (D12, #844).

Each page's claims, keyed on the exact finding message (the claim and the
prose line it's on, one entry per occurrence), so a seed covers that claim in
that sentence and nothing else. They are an allow-list that only
shrinks: #830 binds each claim to a fact or a record, or deletes it, and
removes its entry here in the same PR. Never add one.
"""

from __future__ import annotations

SEEDS: dict[str, tuple[str, ...]] = {}
