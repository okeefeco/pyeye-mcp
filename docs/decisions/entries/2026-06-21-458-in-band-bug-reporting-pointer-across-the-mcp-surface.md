---
date: "2026-06-21"
title: "In-band bug-reporting pointer across the MCP surface (#458)"
issues: [458]
anchors: ["pyeye.mcp.meta.issues_url", "meta.about", "meta.server_instructions", "pyeye.mcp.server.get_about", "expand", "trace"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-06-21 — In-band bug-reporting pointer across the MCP surface (#458)

**Friction:** An agent that hit a pyeye limitation had no in-band way to find where to report it — it had to guess the repo slug, fail, and be handed `okeefeco/pyeye-mcp` out-of-band (#458). The limitation moments pyeye is unusually honest about were producing high-signal bug reports that evaporated.
**Decision:** Surface the canonical issues URL in three places, all sourced from one helper (`pyeye.mcp.meta`, which reads `[project.urls]` from package metadata with a hardcoded fallback — single source of truth, no duplicated URL): (1) the FastMCP `instructions=` block; (2) a `report_issues` key on every `expand` unsupported branch and on a `trace` response whenever `unsupported_edges` is non-empty (top-level, conditional — not duplicated per entry, absent on clean results to avoid noise); (3) a new `pyeye://about` resource returning version + repo + issues. Deliberately NOT added to `resolve`'s ~15 `not_found` payloads — a miss there is usually a recoverable user typo, not a pyeye defect, so a "report a bug" nudge would be noise.
**Anchor:** `pyeye.mcp.meta.issues_url` / `meta.about` / `meta.server_instructions`; `pyeye.mcp.server.get_about`; `expand`/`trace` unsupported branches; #458.
**Verify:** gold — `expand("<class handle>", "imported_by", analyzer)["report_issues"] == meta.issues_url()`; `trace("<handle>", ["members","callers"], analyzer)["report_issues"]` present while `trace("<handle>", ["members"], analyzer)` has no `report_issues` key; `json.loads(pyeye.mcp.server.get_about())` has keys `{name,version,repository,issues}`; `pyeye.mcp.server.mcp.instructions == meta.server_instructions()`. (See tests in `tests/unit/mcp/test_meta.py`, `test_server_meta.py`, `test_expand.py::TestExpandUnsupportedCarriesReportIssues`, `test_trace.py::TestTraceReportIssuesPointer`.)
