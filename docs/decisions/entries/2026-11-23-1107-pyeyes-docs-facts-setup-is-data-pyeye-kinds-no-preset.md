---
date: "2026-11-23"
title: "pyeye's docs-facts setup is data: a registry file, restricted pyeye-* kinds, built-in pages; the preset is deleted (#1107)"
issues: [1107, 1091, 1119, 1083]
anchors: ["pyeye.docs_facts.doc_registry.read", "pyeye.docs_facts.pyeye_kinds.PYEYE_KINDS", "pyeye.docs_facts.pyeye_kinds.project_name", "pyeye.docs_facts.config.load", "pyeye.docs_facts.docs.for_repo", "docs/facts/docs.toml", "tests/test_docs_facts_pyeye_kinds.py", "tests/test_docs_facts_doc_registry.py", "tests/test_docs_facts_config.py"]
status: "amended"
amends: ["2026-11-23-1091-a-data-only-docs-facts-config-per-repository.md"]
supersedes: []
amended_by: ["2026-11-23-1119-a-generic-kinds-fact-schema-is-fixed-under-a-prefix.md"]
superseded_by: []
---

## 2026-11-23 — pyeye's docs-facts setup is data: a registry file, restricted pyeye-* kinds, built-in pages; the preset is deleted (#1107)

**Friction:** #1091 shipped `preset = "pyeye"` as a bridge. It was a data value that selected a setup built into the engine, because pyeye's typed `DocEntry` list and its extractors were code, which a data-only config can't name (C19). pyeye therefore didn't dogfood the config path that other repositories use.

**Decision:** the maintainer's ruling, relayed via designer and coordinator-3 on 2026-11-23.

- **Q1: the registry is a data file.** `docs/facts/docs.toml` holds one `[[doc]]` table per entry, with `path`, `audience`, `kind` and optionally `site`, `covers` and `allow`. The config's `docs` key takes either the path of a TOML, JSON or YAML file, read by `doc_registry.read` through the shared data-file reader and the config's own entry validator, or an inline list as before. The file was proven equal to the typed `DOCS`, entry for entry and in order, with a byte-identical plan, before `DOCS` was deleted (commit 7c151bec).
- **Q2 (a): pyeye's extractors are `pyeye-*` built-in kinds.** There are 11, one per extractor, and that count is #1119's baseline: `test_the_count_only_shrinks` fails if it grows. Each kind's docstring ends "No generic kind can express it: <why>", and a test checks each one. A kind takes no options.
  - **Restricted to pyeye's repository.** That is the repository whose `pyproject.toml` declares `[project] name = "pyeye-mcp"` (`pyeye_kinds.project_name`). The package name is what PyPI and the lockfile key on, so it holds for any checkout or fork of pyeye, and another repository can't match by accident.
  - **The check runs at extraction.** Anywhere else, extraction raises an `ExtractionError` that names the restriction, and the CLI reports "cannot extract the facts". The coordinator accepted extraction time over config-load time: it is the same command, it fails loudly, and the check needs no config code.
- **The reference pages.** A new `pages` key lists built-in page paths from `pages.PAGES`. Those pages render pyeye's facts, so the config refuses them outside pyeye's repository; unlike the kinds, this check runs at load time.
- **Q3: the reference pages are listed explicitly** in the registry, and a test holds them equal to `pages.PAGES`.
- **Deleted:** `preset`, `PRESETS`, `_preset`, `setup.pyeye_setup`, the typed `docs.DOCS` (with `REFERENCE_PAGES` and the `_seeded` claim-seed merge; `claim_seeds.SEEDS` is empty and a test keeps it so).
  - A caller that names no registry or setup now gets the analysed repository's own, from its config (`docs.for_repo`, `config.load`).
  - `entry_for` takes the registry explicitly.
  - `preset` is now an unknown key.
- **The generated docs are unchanged:** `generate` writes nothing, and `check` passes from the config alone.

**Anchor:** `pyeye.docs_facts.doc_registry.read`; `pyeye.docs_facts.pyeye_kinds.PYEYE_KINDS` / `project_name`; `pyeye.docs_facts.config.load`; `docs/facts/docs.toml`; #1107, #1091, #1119, C19.

**Applies-to:** `pyeye.docs_facts.config.load`, `pyeye.docs_facts.doc_registry.read`, `pyeye.docs_facts.pyeye_kinds.PYEYE_KINDS`, `pyeye.docs_facts.kinds.BUILT_IN_KINDS`, `pyeye.docs_facts.docs.for_repo`, `pyeye.docs_facts.docs.entry_for`, `pyeye.docs_facts.cli.plan`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_pyeye_kinds.py tests/test_docs_facts_doc_registry.py tests/test_docs_facts_config.py tests/test_docs_facts_registry.py` passes. It checks:

- the 11 kinds equal pyeye's extractors in order and give the registry's facts;
- each kind's docstring says why it can't be generic, and the count can't grow;
- the restriction refuses another repository;
- pages are known and restricted;
- `preset` is refused;
- this repository's config names the kinds and the registry file;
- every doc is registered.

`uv run python scripts/docs_facts.py check` passes.
