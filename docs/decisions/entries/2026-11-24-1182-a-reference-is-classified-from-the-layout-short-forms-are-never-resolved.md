---
date: "2026-11-24"
title: "A decision's references are classified from the layout; a short form is never resolved (#1182)"
issues: [1182, 1178]
anchors: ["pyeye.decision_sites.refs", "pyeye.decision_sites.resolve_sites", "pyeye.decision_sites.top_level_names", "pyeye.decision_sites.external_top_level_names", "tests/test_decision_sites.py"]
status: "active"
amends: ["2026-11-23-1178-decision-sites-resolve-through-pyeye.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — A decision's references are classified from the layout; a short form is never resolved (#1182)

**Friction:** #1182 measured `decision_sites` over this repo's 121 active entries (dev01, one cold process, 22.6 s). 158 of the references in `Anchor` and `Applies-to` didn't resolve, but only 14 were stale.

- 140 were **short forms**, such as `JediAnalyzer.find_importers`, `outline._is_package` and `edges.resolve_imports`. They name something real, but aren't written from a package root, so only a guess turns them into a handle.
- Some short forms share a first segment with a standard-library module: `inspect._count_submodules` and `trace.trace` mean pyeye's `mcp/operations/inspect.py` and `trace.py`. Resolved as written, they look like stale references.
- An external's private name (`jedi.Project._get_sys_path`) doesn't resolve either.

Reported as stale, they would bury the 14 real ones. Both callers (`decisions check`, and #1178's area matching) need one rule, so it is decided here, once.

**Decision:** assigned by coordinator-3 (2026-11-24), agreed with designer.

- **Classified from the layout, never by resolving.** With the project's top-level names, `refs` gives a dotted name a kind from its first segment:
  - `handle`: rooted at a project top-level package or module (`top_level_names`: the entries of the project root and of its `src/` layout). Only a handle can be stale.
  - `external`: rooted at a standard-library or environment top-level name (`external_top_level_names`: `sys.stdlib_module_names` and the project environment's site directories). It is resolved and keeps the resolver's answer.
  - `short_form`: rooted at neither. It is never resolved, and its site's reason is `short_form`.
  - A project name wins over a standard-library one of the same spelling.
- **Reported apart, never silently:** callers count and list short forms, and externals that don't resolve, separately from stale references. `decisions check --resolve` fails a short form only in entries dated on or after its gate date (#1182's own entry). #1178's engine reports them as sites it can't place.
- **Unchanged without the layout:** a caller that passes no `tops` gets the original two kinds, `handle` and `path`.
- **Rejected:**
  - resolving short forms by their last segment, a guess the original entry already refused for single words;
  - treating a stdlib-rooted name as stale when it doesn't resolve, which `inspect._count_submodules` shows is wrong.

**Anchor:** `pyeye.decision_sites.refs`, `pyeye.decision_sites.resolve_sites`, `pyeye.decision_sites.top_level_names`, `pyeye.decision_sites.external_top_level_names`; `tests/test_decision_sites.py`; #1182, #1178.

**Applies-to:**

- every caller that classifies a decision's references: `decisions check --resolve` (#1182) and the architecture-review engine's area matching (#1178). Both pass `pyeye.decision_sites.top_level_names` and `pyeye.decision_sites.external_top_level_names` to `pyeye.decision_sites.refs` / `pyeye.decision_sites.resolve_sites`. The engine adopts the new kinds after this lands (worker, #1178).

**Verify:** gold. `uv run pytest tests/test_decision_sites.py` passes. It checks:

- a project-rooted name is a `handle`, and a stdlib- or environment-rooted one an `external`;
- an unrooted one is a `short_form`, and a project name wins over a stdlib one;
- a short form is never resolved, and an external keeps the resolver's answer;
- without `tops` the classification is the original one;
- `top_level_names` reads the root and a `src/` layout, and `external_top_level_names` reads the standard library and the environment's site directory.
