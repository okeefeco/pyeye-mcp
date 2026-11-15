---
date: "2026-11-16"
title: "Namespace registrations belong to one project; an unscoped one applies nowhere (#748)"
issues: [748, 618, 667]
anchors: ["pyeye.namespace_resolver.NamespaceResolver.register_namespace", "namespaces_for", "pyeye.project_manager.ProjectManager.get_analyzer", "pyeye.mcp.server.configure_packages"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — Namespace registrations belong to one project; an unscoped one applies nowhere (#748)

**Friction:** `ProjectManager.get_analyzer` merged every namespace on the manager's single, process-wide `NamespaceResolver` into each new analyzer. That merge exists so `configure_packages(..., save=False)`, whose namespaces live only in memory, reaches the rebuilt analyzer. But the registry wasn't keyed by project, so a server that had served project A (namespace `shared`) gave project B's analyzer A's namespace: on its sys_path, in `scope="all"` and in the class graph. B's tools could return A's code. #664's fresh-checkout run found it as another test's `SharedModel`.

**Decision:**

- `NamespaceResolver.register_namespace(namespace, paths, project=...)` stores each registration under its project root, keyed through `path_utils.path_to_key`.
- `get_analyzer` merges only `namespaces_for(<its root>)`, so a project sees its own config plus what was registered *for it*.
- Both `src` callers pass the root: `ProjectManager.get_analyzer`'s config bridge and `configure_packages`.
- A registration without a project (the pre-#748 call shape) is recorded but applies to no analyzer, and logs a warning naming the namespace.
- `namespace_paths` stays as an all-registrations diagnostic view and is never merged into an analyzer.
- Rejected: keeping the old global behaviour for `project=None`, which would keep the leak for any caller that forgot the argument.
- This is internal API (`register_namespace` isn't in user docs), so it's a v2.x Fixed.

**Anchor:** `pyeye.namespace_resolver.NamespaceResolver.register_namespace`, `namespaces_for`; `pyeye.project_manager.ProjectManager.get_analyzer`; `pyeye.mcp.server.configure_packages`; #748.
**Applies-to:**

- the registry: `pyeye.namespace_resolver.NamespaceResolver.register_namespace` / `namespaces_for`;
- its merge into each analyzer: `pyeye.project_manager.ProjectManager.get_analyzer`;
- the callers that register: `ProjectManager.get_analyzer`'s config bridge and `pyeye.mcp.server.configure_packages`;
- the tests `tests/test_namespaces_per_project.py`, which include the guard that no `src` caller registers unscoped.

**Verify:** gold. `uv run pytest tests/test_namespaces_per_project.py tests/integration/test_multirepo_namespace_scenario.py` passes:

- two projects on one manager see only their own namespaces in either order, with no foreign path in `scope="all"` or on `added_sys_path`;
- an in-memory registration reaches only its project;
- an unscoped registration warns with its name and applies nowhere;
- no `register_namespace` call in `src` lacks `project=`;
- #667's multirepo scenario still passes.
