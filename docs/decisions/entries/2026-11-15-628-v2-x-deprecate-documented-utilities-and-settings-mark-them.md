---
date: "2026-11-15"
title: "v2.x deprecation: documented Python utilities and settings are deprecated, not deleted, and stay in the docs only on lines marked deprecated (#628)"
issues: [628, 629, 592]
anchors: ["pyeye.settings.DEPRECATED_ENV_VARS", "pyeye.scope_utils._warn_deprecated_class", "tests/test_documented_env_vars.py", "tests/integration/test_scope_configuration.py::TestDeprecatedScopeUtilities"]
status: "amended"
amends: ["2026-11-15-629-v2-x-release-classification-contract-conforming-corrections.md"]
supersedes: []
amended_by: ["2026-11-24-1182-anchors-that-drifted-are-carried-to-their-current-sites.md"]
superseded_by: []
---

## 2026-11-15 — v2.x deprecation: documented Python utilities and settings are deprecated, not deleted, and stay in the docs only on lines marked deprecated (#628)

**Friction:** The #628 slice 2 plan said to delete `ScopeValidator`, `ScopeDebugger` and `LazyNamespaceLoader` as unused, but `docs/namespace-packages.md` and `docs/migration-guide.md` show users importing them. The amended entry names fields, tools, arguments and documented settings, but not documented Python utilities. Separately, deprecating the pool settings left them unused but still documented, and `test_documented_env_vars` fails on any documented variable that has no effect. That pushed toward deleting their docs, which the v2.x rule forbids.
**Decision:** This amends the v2.x release classification:

- A Python class or function that user docs show being imported or called counts as a documented interface. In v2.x it gets a `DeprecationWarning` (or, for a setting, a startup warning when set) and is deleted only in a major. One that only tests use and no doc mentions may be deleted (`ScopedCache.invalidate_scope` and `get_stats`).
- A deprecated environment variable stays in the docs, and every doc line that names it must say "deprecated". `settings.DEPRECATED_ENV_VARS` is the list. The same rule applies to doc sections on deprecated utilities, but only by review.

Rejected: deleting the documented utilities, which removes an interface in a minor; dropping deprecated settings from the docs, which hides a warning's cause from users who set them.
**Anchor:** `pyeye.settings.DEPRECATED_ENV_VARS`, `PerformanceSettings._warn_deprecated`; `pyeye.scope_utils._warn_deprecated_class`; `tests/test_documented_env_vars.py`; #628, #592, #629; PR #694.
**Applies-to:** env vars: `tests/test_documented_env_vars.py` (`test_every_documented_env_var_takes_effect`, `test_deprecated_env_vars_are_documented_as_deprecated`) and `tests/unit/core/test_settings.py::TestDeprecatedSettings`. Utilities: `ScopeValidator`, `ScopeDebugger` and `LazyNamespaceLoader`, warned in `tests/integration/test_scope_configuration.py::TestDeprecatedScopeUtilities`.
**Verify:** PARTIAL — gold: `uv run pytest tests/test_documented_env_vars.py tests/unit/core/test_settings.py::TestDeprecatedSettings tests/integration/test_scope_configuration.py::TestDeprecatedScopeUtilities` passes. Unverifiable without review: whether a deleted symbol was really undocumented, and whether doc sections on deprecated utilities say so (the doc-line check covers env vars only).
