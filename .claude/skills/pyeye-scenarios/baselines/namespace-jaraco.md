---
date: 2026-06-22
command: pyeye-verify probe suite on scenario namespace-jaraco (pyeye-scenarios skill), project_path <TARGET>/jaraco.text; the §1b round-trip on 2026-11-15
commit: 406783dd6
machine: not recorded
---

# `namespace-jaraco` scenario baseline (stale: re-capture before use)

A dated record, moved verbatim from the pyeye-scenarios skill (#830, design C18). Its numbers are as captured; nothing was re-measured. Record a new baseline as a new record rather than editing this one.

## Probe suite + recorded baseline *(captured 2026-06-22, build `dev416+g406783dd6` = main incl. #423/#444/#454, `project_path = .../jaraco.text`; row 5 re-recorded 2026-11-08. The other rows predate #623 and #712: re-capture before relying on exact values)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("jaraco.context.ExceptionTrap")` | `kind:class`, `scope:project`, file in `../jaraco.context` | ✅ **cross-repo resolution** — sibling repo resolves as project |
| 2 | `expand("jaraco.text", "imports")` (and `trace(... ["imports"])`) | the three `jaraco.*` targets (`context.ExceptionTrap`, `functools.compose`, `functools.method_cache`) report **`scope:project`**; stdlib targets stay `external` | ✅ **cross-repo edge scope** — **#454** (edges agree with `resolve`) |
| 3 | `resolve("jaraco")` | `kind:module`, `scope:project`, anchored at `jaraco.text/jaraco` | ✅ **#444** namespace cold-start anchoring |
| 4 | `inspect("jaraco")` | `is_package:true`, `edge_counts:{members:0, submodules:3}` | ✅ **#444 / #423** |
| 5 | `outline("jaraco")` | `module`/`project` with 3 submodule children: `context` and `functools` `truncated:survey_leaf` (members, no submodules), `text` `truncated:max_depth`; no `children:[]` anywhere | ✅ **#444 / #423** depth-1 survey; **#596** (re-recorded 2026-11-08, PR for #596 — the 2026-06-22 capture's `children:[]` on `context`/`functools` was the #596 bug, mis-recorded as expected) |
| 6 | `resolve("jaraco.text")` (child contrast) | `kind:module`, `scope:project` | ✅ child handle resolves |
| 7 | `expand("jaraco", "submodules")` | 3 stubs: `jaraco.context`, `jaraco.functools`, `jaraco.text` (all `project`) | ✅ **#423 / #444** namespace union across sibling repos |

**Round-trip probe** ([[pyeye-verify]] §1b) *(captured 2026-11-15, build
`2.0.1.dev10+gd615b3a5a` = main @ `d615b3a`)*, module `jaraco.text`.
**STALE:** #623 closed after this capture (2026-11-15T11:09Z), so these numbers
predate its fix. Re-capture with [[pyeye-verify]] before treating a value as
the baseline; until then, don't call a difference a regression.

| Measure | Baseline | Tracking |
|---------|----------|----------|
| stubs from `expand("jaraco.text", "imports")` | 32 | |
| don't round-trip | **22** | #623 (one canonical resolver), #602 |
| inspect miss / resolve miss | 21 / 20 | all `scope: external` (stdlib and typing: `os`, `typing.Callable`, `__future__.annotations`, …) |
| disagree | 1: `functools` (resolve finds it, inspect doesn't) | #602: the bare `functools` vs `jaraco.functools` shadowing |
| handle mismatch | 1: `_typing.TypeVar` | #623 |

All three `jaraco.*` stubs round-trip. Every miss is external. Any
`project`-scoped miss is a regression.

Rows 2–5 + 7 are the **#423 / #444 / #454** acceptance check, and now pass. Against the
*earlier* stale build (the 2026-06-21 global server, pre-#423/#444/#454) row 2's `jaraco.*`
edges came back `external`, `resolve("jaraco")` was ambiguous-external (`kind:variable`,
`file:""`), `inspect`/`outline` were empty, and `submodules` was unknown/empty — so this
scenario doubles as the regression guard for all three fixes.

> ⚠️ **Baselines are build-tagged.** The table above was captured against an up-to-date
> build (`dev416+g406783dd6`, main incl. #423/#444/#454) on 2026-06-22. An earlier capture
> against the stale globally-installed server (2026-06-21) showed the pre-fix behaviour —
> `jaraco.*` import edges `external`, `resolve("jaraco")` ambiguous, `submodules`
> unknown/empty. Same probes, different build: that divergence is the
> regression-vs-environment **signal**, not a bug. Always re-record against the build under
> test and note which build (see the `pyeye-verify` classification).
