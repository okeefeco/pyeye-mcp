---
date: "2026-06-21"
title: "edge-stub `scope` reconciles to the project definition site (#454)"
issues: [454]
anchors: ["pyeye.mcp.operations.stubs.build_stub", "pyeye.mcp.operations.stubs._names_project_module"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-15-623-one-canonical-handle-resolver-every-tool-echoes-the.md"]
superseded_by: []
---

## 2026-06-21 — edge-stub `scope` reconciles to the project definition site (#454)

**Friction:** Dogfooding the `namespace-jaraco` scenario, `resolve("jaraco.context.ExceptionTrap")` reported `scope:"project"` (the sibling repo registered via `.pyeye.json`) while the `imports`/`callees` edges reported `scope:"external"` for the SAME canonical handle. Jedi's `goto(follow_imports=True)` follows the environment `sys.path`, where the *pip-installed* copy of the package outranks the namespace `added_sys_path`, so the forward-goto edges landed on the installed copy; `resolve`/`inspect` instead anchor via `find_module_file` (the project boundary) and call it project. Same handle, two definition sites, two scopes — a canonical-handle/scope-consistency violation that only appears when a namespace sibling is *also* installed.
**Decision:** `build_stub` reconciles `scope` to `"project"` when an externally-classified target's canonical handle names a project module — `_names_project_module` calls `find_module_file` over the SAME boundary `classify_scope` treats as project (`source_roots` + `project_path` + `additional_paths`, excluding `added_sys_path`/env), so stdlib/pure-external handles return `None` and stay external. Only `scope` is reconciled (the stub carries no file; line spans stay as Jedi reported them — they match for the common same-version case). Fixes `imports` AND `callees` since both flow through `build_stub`. Rejected: changing the Jedi project's `sys_path` precedence (no prepend API; broad blast radius across all resolution) and per-stub `find_symbol` re-resolution (the multi-file-inference perf cost the redesign avoids). The `find_module_file` probe is gated behind a non-empty `additional_paths` (sibling roots): the split needs a registered sibling that is *also* installed, so with no sibling roots the per-external-stub filesystem probe is pure waste and is skipped — keeping the common single-project `callees`/`imports` expansion I/O-free. Knowingly skips one pathological case: a non-editable duplicate install of a project's own `source_roots`/`project_path` package (editable installs resolve to the real path via `classify_scope`'s symlink-first rule, #338).
**Anchor:** `pyeye.mcp.operations.stubs.build_stub`, `pyeye.mcp.operations.stubs._names_project_module`; #454.
**Verify:** gold — `tests/integration/test_namespace_import_scope.py`: a project-handle edge target whose Jedi `module_path` is external yields `scope=="project"`, while a stdlib handle (`os.path.join`) stays `"external"`; the `module`-kind and single-component predicate branches and the `additional_paths` perf short-circuit are covered directly. Confirmed end-to-end in-process on the real `namespace-jaraco` repos (`resolve` and `expand(imports)` both report `project`).
