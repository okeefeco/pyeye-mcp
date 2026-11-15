"""pyeye's policy for parso's in-memory parse cache (#684).

parso keeps every parsed module in ``parso.cache.parser_cache``. Once that holds
``_CACHED_SIZE_TRIGGER`` (600) files, each new insert first drops every entry
whose ``last_used`` is more than 10 minutes old. ``last_used`` starts at the
FILE's mtime, not the parse time, so a stdlib or typeshed file (old mtime) is
dropped at the next insert after its own. Jedi still holds those modules and
reads them back with ``jedi.parser_utils.get_parso_cache_node``, which raises
``KeyError``. The resolver turned that into "unresolved": ``asyncio.Queue``
stopped resolving whenever 600+ files had been parsed, which a real project
reaches in normal use.

Correctness must not depend on cache size (the invariant #457 set for the name
index), so pyeye switches that GC off. The cache is keyed by path and replaced
when a file's mtime changes, so it is bounded by the distinct files Jedi touches.

This pins a parso private. ``tests/unit/test_parso_cache_gc.py`` asserts it still
exists, so a parso upgrade that renames it fails CI instead of quietly bringing
#684 back.
"""

from __future__ import annotations

import sys

import parso.cache


def disable_parso_cache_gc() -> None:
    """Never garbage-collect parso's in-memory parse cache. Idempotent.

    ``_CACHED_SIZE_TRIGGER`` is module-global, so this covers every thread,
    including the Jedi worker thread (#650).
    """
    parso.cache._CACHED_SIZE_TRIGGER = sys.maxsize
