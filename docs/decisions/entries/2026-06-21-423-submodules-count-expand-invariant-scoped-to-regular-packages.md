---
date: "2026-06-21"
title: "submodules count==expand invariant scoped to regular packages"
issues: [423, 443, 444]
anchors: ["inspect._count_submodules", "inspect._build_edge_counts", "resolve._is_top_level_package", "resolve._select_root_package"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-21 — submodules count==expand invariant scoped to regular packages

**Friction:** The `submodules` edge advertised `inspect(pkg).edge_counts["submodules"] == len(expand(pkg,"submodules").stubs)` **unconditionally**, but a PEP 420 namespace package surfaces (via Jedi) as `kind=="namespace"`/`scope=="external"` and never reaches inspect's `kind=="module"` counting branch — so inspect omitted the count while `expand` still enumerated children. Verified live during the PR #443 review: `expand("acme.plugins","submodules")` → 2 stubs, `inspect("acme.plugins")` → `edge_counts: {}`. The stated invariant was false for namespace packages.
**Decision:** Scope the count==expand guarantee to **regular** packages (anchored on `__init__.py`); defer namespace-package anchoring through `resolve`/`inspect` to #444 rather than widening inspect's gate now (which would require that anchoring work). Also removed the dead, unreachable directory-anchored PEP 420 clause in `resolve._is_top_level_package` (namespace candidates carry an empty `location.file`, so it never fired). Rejected: widening inspect's gate to `is_dir()` — would re-introduce an external/namespace count path that cannot be reliably anchored yet.
**Anchor:** `inspect._count_submodules` / `inspect._build_edge_counts` submodules gate; `resolve._is_top_level_package` / `resolve._select_root_package`; design spec §4 + §7.2; #423, PR #443, refs #444.
**Verify:** PARTIAL — gold: for a regular package `inspect(pkg).edge_counts["submodules"] == len(expand(pkg,"submodules").stubs)` (`tests/test_submodules_integration.py`, `tests/test_inspect_submodules_count.py`). The namespace boundary (inspect omits the count while `expand` enumerates) is checkable today only at the enumerator level; a real-pipeline namespace assertion through `resolve`/`inspect` is deferred to #444.
