---
date: "2026-11-20"
title: "`_names_path` compares Jedi's own name; #814's respelling is retired (#971)"
issues: [971, 814, 857, 858, 714]
anchors: ["pyeye.resolver._names_path", "pyeye.resolver._place_definition", "pyeye.resolver._place_in_namespace_stubs", "tests/test_names_path_no_respelling.py"]
status: "active"
amends: ["2026-11-19-858-every-configured-package-is-on-jedis-sys-path-in-one-root-order.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-20 — `_names_path` compares Jedi's own name; #814's respelling is retired (#971)

**Friction:** #814 made `resolver._names_path` respell a candidate's Jedi `full_name` through the file → module mapper (`handle_for_anchor`) before comparing it with the requested path. Jedi named a configured package nested in the project from the project root (`.hidden.upstream.clonepkg.thing.X`), while the mapper names it from the package's own root. A qualname-suffix pre-check kept the respelling cheap. #858 (PR #966) found the cause and put every configured package on Jedi's own `sys_path`, but left the respelling alone as a follow-up.

**Decision:** assigned by coordinator-3 (2026-11-20), after checking the premise.

- **Measured first.** The respelling was disabled, recording each case where it would have matched.
  - The full suite (6113 passed) recorded **0** matches. Its one failure was the docs-facts security check seeing the probe's own log write.
  - On django, `resolve` over `django.db.models.base`'s 57 imports plus five public names made 14,620 `_names_path` calls, again with **0** matches.
  - The line was reached in normal runs (it's covered), but its answer never differed from the plain comparison.
- **Retired:** `_names_path(name, path)` is now `name.name` matching the leaf and `full_name == path`. The respelling, the qualname pre-check and the two parameters only they used are gone.
- **Kept, after the audit:** `handle_for_anchor` and `_canonical_of`. They are #714's general Jedi-name → handle rule: a module part from the mapper for a file whose spelling differs from its roots (`src.pkg.mod.X`, an unplaced `__main__.X`). They aren't #814-only. #857's binding rules (`_anchor_on_bindings`) choose among a module's bindings and never depended on the respelling, which matched nothing.
- **If a divergence comes back** (a nested directory that isn't configured, or a root-is-package project): the existing tests for those cases pass without the respelling. A new divergence would show as a name not found, and the fix then belongs in Jedi's roots (#858), not in a respelling.

**Anchor:** `pyeye.resolver._names_path`; `tests/test_names_path_no_respelling.py`; #971.

**Applies-to:**

- `pyeye.resolver._names_path` and its callers `pyeye.resolver._place_definition` and `pyeye.resolver._place_in_namespace_stubs` (#1004's stub namespace members, which merged after this began: 12 calls in its tests, 0 respelling matches).

**Verify:** gold — `uv run pytest tests/test_names_path_no_respelling.py tests/test_configured_packages_on_jedi_path.py tests/test_resolve_nonidentifier_package_dirs.py tests/integration/test_multirepo_namespace_scenario.py` passes. It checks:

- a candidate matches on its own name;
- another spelling of the same qualname is a plain mismatch, never a mapper call;
- a different leaf or a missing `full_name` doesn't match;
- configured nested packages, non-identifier package directories and the multirepo namespace scenario still resolve.
