---
date: "2026-11-19"
title: "Unsaved configure_packages calls accumulate in a session overlay; the response lists them under unsaved (#953)"
issues: [953, 898, 858, 828]
anchors: ["pyeye.config.add_unsaved", "pyeye.config.clear_unsaved", "pyeye.config.ProjectConfig._apply_unsaved", "pyeye.mcp.server.configure_packages", "pyeye.mcp.server._unsaved_view", "pyeye.docs_facts.examples.Example", "tests/test_unsaved_config_overlay.py"]
status: "active"
amends: ["2026-11-18-898-rejected-config-entries-are-disclosed-in-rejected-paths.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-19 — Unsaved configure_packages calls accumulate in a session overlay; the response lists them under unsaved (#953)

**Friction:** the docs say `configure_packages` calls are additive. But each call rebuilt `ProjectConfig` from disk and appended only its own entries, so a second `save=False` call silently dropped the first one's: `[proj, libA]` was followed by `[proj, libB]`. The analyzer, rebuilt from that config, dropped them too.

**Decision:** the maintainer's ruling, with the coordinator's answers on the gaps (2026-11-19). It ships in v2.2.0.

- **A per-project, process-wide overlay of unsaved additions:** `config._UNSAVED`, keyed by the resolved project path.
  - `add_unsaved` merges new entries as a save merges them. Packages and standalone dirs extend, deduped; a namespace replaces that namespace's list, as `save=True` does.
  - Every `ProjectConfig` load applies the overlay last, after the disk sources and auto-discovery (`_apply_unsaved`). So every consumer sees it (`get_analyzer`, plugin contexts, `configure_packages`), a reloaded config gets it on top, and it reaches Jedi through the constructor's config route (#858). A session-only package doesn't suppress sibling auto-discovery, just as a `save=False` call never did, because it appended after a disk load.
  - It lives as long as the process: unsaved entries last until restart or a save. There is no other way to drop them; that is accepted and documented.
- **`save=True`:** it persists the overlay together with its own entries whenever either exists, even when the call names none (`configure_packages(save=True)`), then clears the overlay (`clear_unsaved`).
- **The `unsaved` key** (`953.added.md`) is always present in `configure_packages`' response, and only there, not in the plugin envelope.
  - **What it lists:** what lives only in the overlay. It is computed as the response's own fields minus a disk-only load (`ProjectConfig(include_unsaved=False)`, `_unsaved_view`), so an entry later written to the file by hand drops out.
  - **Shape:** it mirrors the RESPONSE (`{packages, namespaces, standalone: {dirs}}`), not the input parameters' names (`standalone_dirs`). Each field then has its counterpart's form (normalised `packages` and `namespaces`, raw `standalone.dirs`) and compares with it field for field. That was the coordinator's change to the proposal.
  - **Empty values:** `[]` / `{}` when nothing is unsaved; absence and zero stay distinct (#568).
  - **Rejected alternative:** a per-entry `source` marker, which would change `packages` from a list of strings to a list of objects.
- **Executed docs:** the accumulation is shown in `docs/api/README.md` as an executed example (#828). That needed one addition to the example syntax: a body that is a JSON ARRAY of argument objects is a sequence, run in order on the same project, with the shown output matched against the last call's response (`Example.before`). Each example stays one isolated test, and a conftest fixture clears the overlay between tests.

**Anchor:** maintainer ruling on #953 (via coordinator-3, 2026-11-19); `pyeye.config.add_unsaved`, `clear_unsaved`, `has_unsaved`, `ProjectConfig._apply_unsaved`; `pyeye.mcp.server.configure_packages`, `_unsaved_view`; `pyeye.docs_facts.examples.Example`; #953, #898, #858, #828.
**Applies-to:**

- the overlay: `pyeye.config.add_unsaved`, `pyeye.config.has_unsaved`, `pyeye.config.clear_unsaved`, `pyeye.config.ProjectConfig._apply_unsaved`, `pyeye.config.ProjectConfig.load_config`;
- the tool: `pyeye.mcp.server.configure_packages`, `pyeye.mcp.server._unsaved_view`;
- the example syntax: `pyeye.docs_facts.examples.Example`, `pyeye.docs_facts.examples.parse_examples`.

**Verify:** gold. `uv run pytest tests/test_unsaved_config_overlay.py tests/test_docs_examples.py` passes. It checks:

- two unsaved calls keep both packages, and the analyzer resolves both;
- the save-like merge (dedupe; namespace replaced per name; standalone extended);
- overlays are per project;
- a save persists the overlay with its own entries, and a bare save persists a pending overlay and clears it, while a bare save with nothing pending writes nothing;
- a reloaded config gets the overlay on top, and an entry written to the file is no longer unsaved;
- the disk-only view leaves the overlay out;
- `unsaved` is always present, empty when nothing is pending, and mirrors the response's fields;
- the sequence syntax parses and rejects bad bodies;
- the README's executed two-call example shows three packages and two unsaved.
