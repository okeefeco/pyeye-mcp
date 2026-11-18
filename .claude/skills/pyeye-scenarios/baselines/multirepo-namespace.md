---
date: 2026-11-15
command: pyeye-verify probe suite on scenario multirepo-namespace (pyeye-scenarios skill), project_path <TARGET>/multirepo_namespace/app
commit: 9c00bbe
machine: not recorded
---

# `multirepo-namespace` scenario baseline

A dated record, moved verbatim from the pyeye-scenarios skill (#830, design C18). Its numbers are as captured; nothing was re-measured. Record a new baseline as a new record rather than editing this one.

## Probe suite + recorded baseline *(captured 2026-11-15, build `2.0.1.dev34+g9c00bbe2f` = #623 slice 3 @ `9c00bbe`)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("corp.tools.Base")` | `corp.core.models.Base`, `class`, `project` | re-export collapses across repos |
| 2 | `inspect("corp.tools.widgets.Widget")` | `superclasses: ["corp.core.models.Base"]`, `edge_counts: {members: 2, superclasses: 1}` | cross-repo base |
| 3 | `expand("corp", "submodules")` | `corp.core`, `corp.tools`, `corp.web`, all `project` | namespace union; configured namespaces and packages are `project` (#623 decision 7) |
| 4 | `expand("corp.tools.widgets.Widget", "superclasses")` | `corp.core.models.Base` (`project`) | ✅ |
| 5 | `expand("corp.core.models.Base", "subclasses")` | `corp.tools.widgets.Widget` | ✅ **#669** (re-recorded on `main` after #676; was `[]`) |
| 6 | `expand("corp.core.models", "imported_by")` | `app.main`, `corp.tools`, `corp.tools.widgets`, `corp.web.views` | ✅ **#668** (re-recorded after #676; `corp.web.views` was missing) |
| 7 | `resolve("Shared")` | ambiguous: `corp.core.models.Shared`, `corp.tools.widgets.Shared` | ✅ **#668** (re-recorded after #676; was a silent single answer) |
| 8 | `expand("corp.web.views.render", "callees")` | `corp.core.models.Base.describe`, `corp.core.models.make`, `corp.tools.sub.helper.shout`, `corp.tools.widgets.Widget`; `unresolved_call_sites: 0` | calls into two other repos |
| 9 | `outline("corp")` | 3 children, each `truncated: max_depth` | namespace survey |
| 10 | `expand("app.main", "imports")` | the 4 `corp.*` targets `project`, `sys` `external` | cross-repo edge scope |

Before #623 slice 3, rows 1–4 and 8 failed too: `corp.core` and `corp.web` reported
`external`, and `inspect`/`outline`/`expand` couldn't find them (the #653 regression).
Rows 5–7 were re-recorded on build `2.0.1.dev44` (main after #675 and #676), and every
row now passes; the integration test pins them all.
