---
date: 2026-11-17
command: pyeye-verify probe suite and the §1b round-trip on scenario django (pyeye-scenarios skill), project_path <TARGET>/django
commit: 4f8f70dc
machine: not recorded (Python 3.12, caches and MemoryMax as stated below)
---

# `django` scenario baseline

A dated record, moved verbatim from the pyeye-scenarios skill (#830, design C18). Its numbers are as captured; nothing was re-measured. Record a new baseline as a new record rather than editing this one.

## Probe suite + recorded baseline *(re-captured 2026-11-16, build `2.0.1.dev117+g95c7b40b4` = main @ `95c7b40b` after #782, Python 3.12; caches `PYEYE_PARSO_CACHE_MAX_ENTRIES=1000`, `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=500`, `PYEYE_SCRIPT_CACHE_MAX_ENTRIES=200`; max RSS 333 MB under `MemoryMax=2.5G`; the #629 sign-off, report on #636. Re-verified unchanged 2026-11-17 on `2.0.1.dev123+gb4b4b2a21` and on `2.0.1.dev129+g4f8f70dcd`, after #803's fix in PR #805)*

| # | Probe | Expected (baseline) | Demonstrates / changed since 2026-06-22 |
|---|-------|---------------------|-----------------------------------------|
| 1 | `resolve("django.db.models.Model")` | `handle: django.db.models.base.Model`, `kind:class`, `scope:project`, `base.py:501` | **canonical-handle collapse**: the re-export resolves to its definition site. Unchanged. |
| 2 | `inspect("django.db.models.Model")` | `superclasses:["…utils.AltersData"]`, `signature:"Model()"`, `edge_counts:{members:67, superclasses:1}`, `re_exports:["django.db.models.Model"]`; **no `callers`/`references` key** | **absence-vs-zero** (no caller key) and the **static-surface ceiling** (`members` omits the metaclass-injected `_meta`/`objects`/`DoesNotExist`). Changed: `re_exports` was `["…migrations.operations.fields.Model"]`, an internal import binding; only public paths are reported now (**#712**, PR #766). `members` was 68; 67 is exact (66 methods plus `pk`), because the 5 `save.alters_data = True`-style statements assign an attribute and bind nothing. |
| 3 | `expand("django.db.models.Model", "superclasses")` | one stub: `django.db.models.utils.AltersData`; `ceiling:"declared_bases"`, `unresolved_superclasses:[]` | matches `edge_counts.superclasses`. Added: `ceiling` (**#417**, PR #760) and `unresolved_superclasses` (**#624**). |
| 4 | `expand("django.core.signing", "imported_by")` | 10 module stubs incl. `django.http.request`, `django.contrib.sessions.backends.base`, and `tests.*`; `ceiling:"static_imports"`, `unresolved_importers:[]`, `unparseable_files:[".../tests/test_runner_apps/tagged/tests_syntax_error.py"]` | the reverse-static import graph (deterministic). Added: `ceiling` (**#417**), `unresolved_importers` (**#668**), and `unparseable_files` (**#729**, PR #754), which names django's deliberately broken test file instead of skipping it silently. |
| 5 | `expand("django.db.models.Model", "callers")` | `unsupported, reason:"deferred_reference_backend"` (#333), plus a `report_issues` URL (**#458**, PR #460) | **honest-limit refusal**: not faked, not empty, and it carries the in-band report path. Unchanged. |

All five are identical on an in-process repeat. Timings on `2.0.1.dev129+g4f8f70dcd` (main @ `4f8f70dc`, after PR #805): the first `inspect` takes 21 s, including building the re-export binding index for the `django` package once (#803). The first `imported_by` takes 31 s, including building the project's import graph. Repeats take ≤0.4 s.

**Round-trip probe** ([[pyeye-verify]] §1b) *(values captured 2026-11-17, build
`2.0.1.dev123+gb4b4b2a21` = main @ `b4b4b2a2`, after #795's fix in PR #797, and
re-verified unchanged on `2.0.1.dev129+g4f8f70dcd` = main @ `4f8f70dc`, after the
fix for #803 in PR #805. Timings are from the latter: Python 3.12, the same
caches as the probes above, max RSS 335 MB, 1m23s wall time including the
probes; it was 8m17s before #805)*, module `django.db.models.base`:

| Measure | Baseline | Tracking |
|---------|----------|----------|
| stubs from `expand("django.db.models.base", "imports")` | 57 (51 `project`, 6 `external`: `collections.defaultdict`, `copy`, `functools.partialmethod`, `inspect`, `itertools.chain`, `warnings`) | |
| don't round-trip | **0** | |
| inspect miss / resolve miss | 0 / 0 | |
| disagree / handle mismatch | 0 / 0 | |

Every stub round-trips, the stdlib ones included. Any miss is a regression.

Timings on `2.0.1.dev129+g4f8f70dcd`:

- **Project stubs** (51): `inspect` has a median of 0.04 s, 8.2 s in total. The
  slowest is `django.db.models.aggregates.Max` at 2.95 s; the next is
  `django.db.models.expressions.ExpressionWrapper` at 0.39 s. `resolve` is
  ≤0.19 s.
- **External stubs** (6): `inspect` is ≤0.97 s (`functools.partialmethod`).

Two earlier costs are gone:

- On `2.0.1.dev117+g95c7b40b4` this probe never finished.
  `inspect("django.apps.registry.apps")` (stub 4) re-parsed the 907 package
  files on each of about 66 BFS hops (#795, fixed by PR #797).
- On `2.0.1.dev123+gb4b4b2a21` every project stub took 8–10 s, because the
  re-export binding index was rebuilt for each new handle (#803, fixed by PR
  #805; profiled on #803).

**Tripwire:** it's a regression if a project stub's `inspect` median rises
above ~0.5 s, if any single project stub exceeds ~5 s, or if the round-trip's
wall time exceeds ~5 min. Any of these most likely means #795's or #803's cost is back:
check `canonicalization._binding_index_cache` and the artifact-cache misses
(#803's profile). `Max`'s ~3 s is today's ceiling, and it isn't profiled. For
comparison, #803's profile put a cold `inspect` with `re_exports` stubbed out
at 0.5–1.2 s, most of it Jedi inference.

> Probe 2's `members:67` is a count of *statically written* members. Reporting it as
> "Model's complete attribute set" would be wrong — `_meta`, `objects`, `DoesNotExist`
> are metaclass-injected and invisible to static analysis. The verify rubric treats
> mislabelling a static count as runtime-exhaustive as a FAIL.
