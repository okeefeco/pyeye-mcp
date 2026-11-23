---
date: "2026-11-24"
title: "The architecture review lists the sites it can't place apart: stale, short form, external (#1178)"
issues: [1178, 1182, 1188]
anchors: ["pyeye.docs_facts.architecture.plan", "pyeye.docs_facts.architecture.report", "tests/test_architecture_review_engine.py"]
status: "active"
amends: ["2026-11-24-1178-the-architecture-review-engine-contract.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — The architecture review lists the sites it can't place apart: stale, short form, external (#1178)

**Friction:** #1178's engine listed every decision site without a handle as `unresolved_sites`. worker-2 measured this repository's entries for #1182: 113 of 476 unique handles are short forms such as `edges.resolve_imports`, not qualified from a package root. The engine's list would have been mostly noise that read as stale. #1188 added the shared rule to `pyeye.decision_sites`: a reference is classified from the project layout as `handle`, `external` or `short_form`, and a short form is never resolved (`2026-11-24-1182-a-reference-is-classified-from-the-layout-short-forms-are-never-resolved.md`).

**Decision:** assigned by coordinator-3 (2026-11-24), the engine follow-up to #1188.

- `plan` passes the project's top-level names and the external ones (`top_level_names`, `external_top_level_names`, read once per run) to `resolve_sites`.
- A site with no handle goes into one of three lists, in the packet and the report:
  - **`unresolved_sites`:** a project handle or a path that doesn't resolve. That is stale.
  - **`short_form_sites`:** never resolved.
  - **`external_sites`:** a standard-library or environment name, which no area holds.
- Each is counted and listed. None is ever treated as "not in this area", and none is silently dropped.
- A decision whose other sites are in the area is still a candidate.

**Anchor:** `pyeye.docs_facts.architecture.plan`, `pyeye.docs_facts.architecture.report`; `tests/test_architecture_review_engine.py`; #1178, #1188.

**Applies-to:**

- the engine's decision pass and report: `pyeye.docs_facts.architecture.plan` and `pyeye.docs_facts.architecture.report`. `decisions check` (#1182) classifies with the same rule in `pyeye.decision_sites`.

**Verify:** gold. `uv run pytest tests/test_architecture_review_engine.py` passes. On the fixture, a short form is listed under `short_form_sites` and an external name under `external_sites`, never under `unresolved_sites`. Only the stale project handle is unresolved. The decision is still a candidate on its in-area handle, and the report carries all three lists.
