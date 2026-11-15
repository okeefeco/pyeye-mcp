---
date: "2026-10-29"
title: "Shipped prose is guarded against teaching removed tools; core primitives are documented in one place (#509)"
issues: [509, 505]
anchors: ["tests/test_mcp_surface_conformance.py::TestNoShippedProseTeachesRemovedTools", "GONE_ENTIRELY", "SURVIVES_AS_INTERNAL_METHOD", "PROSE_ALLOWLIST"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-10-29 — Shipped prose is guarded against teaching removed tools; core primitives are documented in one place (#509)

**Friction:** #505 guarded only packaged code (`mcp__pyeye__*` in `src/`). Prose had no guard, so `docs/api/` and `DOCUMENTATION.md` kept documenting the v1 surface as live through three removal passes. Of the 15 tools in `docs/api/` core pages, only `configure_packages` existed, and even its page was wrong (a nonexistent `auto_discovered` result).
**Decision:** Retire the hand-kept core-tool pages instead of rewriting them. The primitives are documented only in the README "Core Tools" section and the `python-explore` skill (already conformance-tested), and other docs point there. Plugin pages stay because those tools are live. Enforce with a two-tier check: names with no implementation left (`GONE_ENTIRELY`) must not appear in any shipped `.md`/`.json`; names that survive as `JediAnalyzer` methods (`SURVIVES_AS_INTERNAL_METHOD`) may appear in prose but not as an API heading. Deliberate mentions go in `PROSE_ALLOWLIST`, each with a reason. Rejected: a single-tier ban, which flags correct prose about internal methods, and the issue's `README.md` exclusion, which would also have skipped `docs/api/README.md`.
**Anchor:** #509 ; `tests/test_mcp_surface_conformance.py::TestNoShippedProseTeachesRemovedTools` ; `GONE_ENTIRELY` / `SURVIVES_AS_INTERNAL_METHOD` / `PROSE_ALLOWLIST` ; supersedes the "mechanical guard over shipped prose … does not exist yet" residue in the 2026-08-09 #505 entry.
**Verify:** gold — `uv run pytest tests/test_mcp_surface_conformance.py -k Prose` passes, and fails when a probe `.md` containing `find_references` or `## find_symbol` is added under `docs/` (checked at authoring time). PARTIAL residue: whether an allowlisted file's mentions are still deliberate needs human review. The guard doesn't check response shapes or plugin tool names (#555).
