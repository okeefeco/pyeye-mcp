---
date: "2026-11-07"
title: "Remove `configure_packages`' standalone-scan options rather than wire them up (#513, #253)"
issues: [513, 253, 505]
anchors: ["pyeye.mcp.server.configure_packages", "ProjectConfig.get_standalone_config", "get_ignored_standalone_keys", "tests/test_standalone_options_removed.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-07 — Remove `configure_packages`' standalone-scan options rather than wire them up (#513, #253)

**Friction:** #505 kept `JediAnalyzer._discover_standalone_files` as "the only implementation of the `standalone` config contract", provisional on #513. That contract never ran: `configure_packages` persisted `recursive` / `file_pattern` / `exclude_patterns`, but the method had no caller after `find_references` went, and it read `exclude_patterns` only from a parameter, never from config. A user could set an exclusion, get a saved config and no error, and see it silently ignored, on the shipped 2.0 tool surface.
**Decision:** Remove the three options from `configure_packages`, stop persisting them, and delete `_discover_standalone_files` (#513 option 2). Standalone dirs stay scanned in full. This also brings the tool to 4 parameters, resolving #253 without its proposed `StandaloneConfig` dataclass. Compatibility: legacy keys in `.pyeye.json` are ignored with a warning and reported in the response's `warnings` (absent when none); removed arguments from old clients are ignored, not rejected. Rejected: wiring it up (#513 option 1). That would keep 7 parameters, needing #253's separate breaking change, and would revive a never-exercised path just before the tag. Fine-grained standalone filtering can return later as a non-breaking 2.x addition. Supersedes the "Also kept: `_discover_standalone_files`" clause of the #505 entry.
**Anchor:** `pyeye.mcp.server.configure_packages`; `ProjectConfig.get_standalone_config` / `get_ignored_standalone_keys`; `tests/test_standalone_options_removed.py`; #513, #253, #505.
**Verify:** gold — `uv run pytest tests/test_standalone_options_removed.py` passes: the signature is exactly `packages, namespaces, standalone_dirs, save`; saved `standalone` is `{"dirs": [...]}` only; legacy keys produce a `warnings` entry; a `call_tool` with `recursive`/`exclude_patterns` succeeds and applies nothing; `JediAnalyzer` has no `_discover_standalone_files`.
