---
date: "2026-11-23"
title: "A repository's docs-facts config is data only: built-in kinds read files, and nothing names code to import (#1091)"
issues: [1091, 1083, 1098, 1092, 1094, 818]
anchors: ["pyeye.docs_facts.config", "pyeye.docs_facts.data_facts", "pyeye.docs_facts.kinds", "pyeye._data_files", "pyeye.docs_facts.static.file_constant", "tests/test_docs_facts_config.py"]
status: "active"
amends: ["2026-11-22-1091-docs-facts-runs-on-any-repo-through-a-setup.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A repository's docs-facts config is data only: built-in kinds read files, and nothing names code to import (#1091)

**Friction:** #1091 step 1 (PR #1096) made docs-facts runnable through a `Setup`, but a repository could only build one in Python. RFC #1083 needs a repository to declare what docs-facts checks. The first proposal let the config name extractors and docs by import reference. The maintainer's rulings refused that:

- **Via designer, 2026-11-22:** static only for any repository other than pyeye.
- **C19, the same day:** no runtime facts anywhere, pyeye included.

So the config can't name code at all.

**Decision:** the maintainer's rulings via designer and coordinator-3, 2026-11-22.

- **Where:** `[tool.pyeye.docs_facts]` in `pyproject.toml`, or `"docs_facts"` in `.pyeye.json`, which wins. Repository-level only: the user's global pyeye config is never read for it.
- **No config is an error,** "nothing to check" (`config.ConfigError`). The CLI has no fallback.
- **`preset = "pyeye"`** (the maintainer's ruling via designer, 2026-11-23: a bridge until #1107 moves pyeye's registry to data). It selects a setup built into the engine (`config.PRESETS`): pyeye's extractors, doc registry, rules and pages, read at call time. Only engine built-ins can be named. A preset can't be combined with `facts`, `extractors` or `docs`; `rules`, `changelog` and `paths` override it. pyeye's own `pyproject.toml` declares `preset = "pyeye"`. Its `generate`/`check` output is unchanged.
- **The inline path is dogfooded in CI:** `tests/fixtures/docs_facts_inline` is a small repository configured inline, with `literal`, `toml`, `json` and `yaml` facts and `honest-claims`. `check` must pass on it as committed, and every kind must catch a change.
- **Data only (C19):**
  - **`facts`:** `{id, from, file, key | name}` tables, built-in kinds only. `literal` folds a module-level constant from the file's syntax tree (`static.file_constant`). Names resolve in that file only; its imports are never followed. `toml`/`json`/`yaml` read a dotted key path through `pyeye._data_files`, the one data reader. ProjectConfig's YAML branch now uses it too, and YAML is read with `safe_load` only (designer's note; PyYAML is a runtime dependency, #1094).
  - **`extractors`:** `{kind, <options>}` tables for further built-in kinds. A kind is a factory, options to `Extractor` (`kinds.BUILT_IN_KINDS`, `kinds.KindOptionsError`). This is the seam #1092's structural extractor registers in.
  - **`docs`:** inline `DocEntry` tables.
  - **`rules`:** `"all"` or a list of IDs. A rule whose facts are absent is skipped and reported (PR #1096).
  - **`paths`:** `Setup.paths`, threaded through `plan` and the record loaders, defaulting to today's `docs/facts/...` files.
- **Refused, each naming where it is:**
  - any value shaped like `package.module:attr`, at any depth, refused as code;
  - unknown keys, kinds and rules;
  - files outside the repository (#717's `relative_within`).
- **Amends #1091's first entry:** the `Setup` now also carries `Paths`. pyeye's output is still byte-identical.
- **Stated where readers look:** SECURITY.md's Security Model says docs-facts never imports or runs the analysed repository's code. `docs/development/docs-facts.md` documents the config.

**Anchor:** `pyeye.docs_facts.config.load` / `find` / `ConfigError`; `pyeye.docs_facts.data_facts`; `pyeye.docs_facts.kinds.BUILT_IN_KINDS`; `pyeye.docs_facts.static.file_constant`; `pyeye._data_files`; `pyeye.docs_facts.setup.Paths`; #1091, C19.

**Applies-to:** `pyeye.docs_facts.config.PRESETS`, `pyeye.docs_facts.config`, `pyeye.docs_facts.data_facts`, `pyeye.docs_facts.kinds`, `pyeye.docs_facts.static.file_constant`, `pyeye._data_files`, `pyeye.config.ProjectConfig._load_from_file`, `pyeye.docs_facts.setup.Paths`, `pyeye.docs_facts.cli.plan`, `pyeye.docs_facts.cli.main`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_config.py tests/test_docs_facts_static.py` passes. It checks:

- where the config is read, and that the global config is not;
- no config is an error;
- refusals of code references, unknown keys, kinds, rules and outside files;
- the inline docs and the rules selection;
- the toml/json/yaml and literal kinds, each with its misses;
- the kinds seam;
- the paths;
- generate and check through the CLI.

`uv run pytest tests/test_docs_facts_inline_fixture.py` checks the inline fixture: `check` passes, each kind catches a change, `honest-claims` runs, and no pyeye page or rule runs. Acceptance, run by hand on Scrapy 2.20.0 and Poetry 2.5.2, is recorded in the PR.
