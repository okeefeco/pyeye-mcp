---
date: "2026-11-19"
title: "find_django_views follows project subclasses of class views through the shared class graph (#942)"
issues: [942, 941, 664, 397]
anchors: ["pyeye.plugins.django.DjangoPlugin.find_views", "pyeye.plugins.django.DjangoPlugin._indirect_class_views", "tests/unit/plugins/test_django_views.py"]
status: "active"
amends: ["2026-11-18-941-a-django-view-base-must-come-from-django.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — find_django_views follows project subclasses of class views through the shared class graph (#942)

**Friction:** #941 left `class Indirect(Base)`, where `Base(ListView)`, unreported. A project's own base view is the usual way Django apps share behaviour, so the direct-only answer missed real views.

**Decision:**

- After the direct scan (#941), every top-level direct class view is a seed. `DjangoPlugin._indirect_class_views` walks `JediAnalyzer.find_subclasses` from the seeds, breadth first, by definition site. That's the shared class graph (#397), as `find_pydantic_models` walks it (#664).
- A subclass in any module counts, not only in views files.
- A class found both ways is reported once, keyed by file (`path_to_key`) and line.
- Cycles terminate.
- Indirect views follow the direct ones, ordered by file, then line.
- **Always on (A), not opt-in:** it's the complete answer, it matches `find_pydantic_models`, and the graph is shared with `expand(subclasses)`.
  - **Cost:** the first call builds the graph.
    - The pyeye repo: 603 files, 12.0 s.
    - The django scenario repo: 2,922 files including tests, 118.9 s and up to 1.6 GB RSS. Before this, it was 4.5 s.
    - A walk step after the first is a dict lookup.
    - A project with no direct class views never builds the graph.
    - The docstring and `docs/api/django-tools.md` state the cost.
  - **Rejected:**
    - an `include_indirect` flag (B), which would hide views by default and add a contract parameter;
    - walking only when the graph is already built (C), which would make the answer depend on cache state.
- **Not changed:** nested direct class views are reported but aren't seeds, because a nested class has no module-level handle to walk from. Also, DRF bases still don't count (#947).

**Anchor:** `pyeye.plugins.django.DjangoPlugin.find_views` / `_indirect_class_views`; `tests/unit/plugins/test_django_views.py`; #942.

**Applies-to:**

- `pyeye.plugins.django.DjangoPlugin.find_views`, `_class_handle` and `_indirect_class_views`.
- `docs/api/django-tools.md` (find_django_views).

**Verify:** gold — `uv run pytest tests/unit/plugins/test_django_views.py` passes. It checks:

- subclasses at depth 2 in another module;
- a class found both ways is reported once;
- `find_subclasses` is never called without a class view;
- a cyclic hierarchy terminates;
- the cold cost on a 150-module fixture is within `FIND_VIEWS_COLD`.
