---
date: "2026-11-16"
title: "A re-export is a public binding (package __init__, __all__, or a public facade over a private module), found from the AST import table (#712)"
issues: [712, 393, 629, 704]
anchors: ["pyeye.canonicalization.collect_re_exports", "pyeye.canonicalization._scan_package_for_handle", "pyeye.canonicalization._is_public_binding", "pyeye.analyzers.base_resolution.build_import_table"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — A re-export is a public binding (package __init__, __all__, or a public facade over a private module), found from the AST import table (#712)

**Friction:** `collect_re_exports` counted every module-level binding of a symbol as a re-export. On this repo, `pyeye.handle.Handle` listed six modules that merely `from pyeye.handle import Handle`, which `imported_by` already reports; on a large codebase the list approaches "every importer". The documented contract is "all public dotted paths". Separately, the scan matched on Jedi's `full_name`, which follows only absolute imports, so a package `__init__`'s `from .core import X` (the common form) was never found at all.
**Decision:** This follows the user's decision on #712. A binding of `S` at `M.S` is reported as a re-export only when one of these holds:

1. `M` is a package `__init__.py`;
2. `S` is in `M`'s statically readable `__all__` (`=` or `+=` of a literal);
3. `M` is public (no `_`-prefixed part; dunders aren't private), and it binds `S` from a private module.

- The BFS still follows every binding and only filters what it reports, so a public re-export reached through an internal hop is found.
- One-hop edges come from `base_resolution.build_import_table`, the shared deterministic AST table: relative imports are resolved and aliases are kept. Jedi names and `goto` are not used: goto lands on the final definition, not the next hop, and it is non-deterministic across processes (#419).
- A file the scan can't read or parse propagates its error (#704), so `re_exports` is left absent (unknown).
- Classified Fixed (#629): the output now matches the documented contract.

Rejected: filtering the walk itself, which loses re-exports behind an internal hop (coordinator's review); resolving each binding with goto (#419).
**Anchor:** `pyeye.canonicalization.collect_re_exports`, `_scan_package_for_handle`, `_is_public_binding`; `pyeye.analyzers.base_resolution.build_import_table`; #712, #393, #704.
**Applies-to:** `canonicalization.collect_re_exports` (via `_scan_package_for_handle` and `_is_public_binding`), which is the one collector behind `inspect`'s `re_exports` field and behind the planned #393 `re_exports` expand edge. Both read the same definition, so they agree.
**Verify:** gold: `uv run pytest tests/test_public_reexports.py` passes. It covers each rule, aliases, a plain internal import not being reported, a private module's own bindings not being reported, both through-an-internal-hop chains, `inspect` agreeing, and this repo's `Handle` having no internal-import entries.
