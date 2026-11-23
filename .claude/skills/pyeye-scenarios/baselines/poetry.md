---
date: 2026-11-23
command: pyeye-verify probe suite and task trial on scenario poetry (pyeye-scenarios skill), project_path <TARGET>/poetry
commit: f053174e
machine: dev01 (Linux, 8 GB)
---

# `poetry` scenario baseline

The first record for Poetry 2.5.2 (`4934abbd`), a `src/`-layout project, captured by the first structured-verification run (#1140). Record a new baseline as a new record rather than editing this one.

## Probe suite + recorded baseline *(captured 2026-11-23, build `2.2.1.dev75+gf053174ea`)*

| # | Probe | Expected (baseline) | Demonstrates / tracking |
|---|-------|---------------------|-------------------------|
| 1 | `resolve("poetry.publishing.hash_manager.Hexdigest")` | `class`, `project`, `src/poetry/publishing/hash_manager.py:15` | `src/` layout found with no config |
| 2 | `inspect("poetry.publishing.hash_manager.Hexdigest")` | `signature: "Hexdigest(md5: str \| None, sha256: str \| None, blake2_256: str \| None)"`, `superclasses: ["NamedTuple"]`, `edge_counts: {members: 3, superclasses: 0}` | ✅ **#1126** (was the factory's `(typename, fields, /)`) |
| 3 | `expand("hashlib", "imported_by")` | 10 module stubs, all `project` (8 under `poetry.*`, 2 under `tests.*`); `unresolved_importers`: `tests/repositories/fixtures/pypi.org/generate.py` | the audit's stdlib-importer pattern; a file with no module name is listed, not dropped (#668) |
| 4 | the same with `max_stubs=3` | 3 stubs, `truncated: true`, `truncation_reasons: ["max_stubs"]`, `total: 10`, same order as row 3 | right altitude, determinism |
| 5 | `resolve("poetry.utils.env.Env")` | `poetry.utils.env.base_env.Env` | re-export collapses to the definition site |
| 6 | `expand("poetry.utils.env.base_env.Env", "subclasses")` | `poetry.utils.env.system_env.SystemEnv`, `poetry.utils.env.virtual_env.VirtualEnv`; `handleless_subclass_count: 0`; a `transitive_hint` | direct subclasses only (#422) |
| 7 | `outline("poetry.utils.env")` | a package survey: 11 submodules, `poetry.utils.env.python` `truncated: max_depth` with `submodule_count: 4`, the rest `survey_leaf`; root `member_count: 3` | survey mode, counts named for their edge |
| 8 | `expand("poetry.factory.Factory", "callers")` | `unsupported: true`, `reason: "deferred_reference_backend"` | honest limits (#333) |

## Round-trip probe

`scripts/roundtrip_probe.py <TARGET>/poetry poetry.installation.executor`: 39 stubs, **0** don't round-trip.

## Task trial

The discovery task: "Is there an existing helper that computes a hash (such as SHA-256) of a file on disk? Name it by its full dotted path, and list every place under `src/poetry` that calls it."

Ground truth: `poetry.utils.helpers.get_file_hash`, called from `poetry.installation.executor.Executor._validate_archive_hash` and `poetry.packages.direct_origin` (`get_package_from_file`). A near-duplicate, `poetry.masonry.builders.editable.EditableBuilder._get_file_hash`, is worth naming.

| Arm | Correct | Turns | Tokens | Time |
|-----|---------|-------|--------|------|
| grep-only control | yes, both callers, and named the near-duplicate | 4 | 89,625 | 21 s |
| `python-explore` skill + pyeye | yes, both callers, and named the near-duplicate | 11 | 258,506 | 33 s |

The skill arm took its caller list from the LSP's `incomingCalls`, since pyeye defers callers (#333), and proved each call site with `resolve_at`.
