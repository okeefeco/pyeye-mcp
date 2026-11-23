---
date: "2026-11-24"
title: "Every handle an architecture page names resolves, through the dump and then pyeye's resolver; architecture pages only, for now (#1176)"
issues: [1176, 1173, 1092, 1178]
anchors: ["pyeye.docs_facts.extractors.structure.handles_rule", "pyeye.docs_facts.extractors.structure.handles_findings", "pyeye.docs_facts.structure.handles.unresolved", "pyeye.docs_facts.structure.handles.named", "pyeye.docs_facts.structure.options.ARCHITECTURE_PAGES", "pyeye.decision_sites.pyeye_resolver", "tests/test_structure_handles.py"]
status: "active"
amends: ["2026-11-23-1092-the-structure-kinds-fact-contract.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-24 — Every handle an architecture page names resolves, through the dump and then pyeye's resolver; architecture pages only, for now (#1176)

**Friction:** `/arch-facts` area docs and top maps (#1173) name helpers by fully-qualified handle. Nothing checked them. A removed or renamed helper left a stale handle that `check` passed (the RFC #1083 trial's `validate_v2` did check). Checking against the dump alone would also call a correct re-exported path stale, because the dump lists each definition only where it's defined.

**Decision:** The `structure` kind brings a third rule, `architecture-handles`, built for its prefix like `layering` and `structure-coverage`.

- **Scope:** it scans only registered pages matching the kind's `architecture_pages` globs (default `docs/architecture/**`, ruling 1 on #1173). Architecture pages only, for now (ruling B); other pages aren't held to it.
- **Two steps, stale only if both fail:** a fast path through the dump's `<p>.members.<owner>` facts (an owner, or `<owner>.<member>`, readable or not), then pyeye's `resolve` through the shared `pyeye.decision_sites.pyeye_resolver` (the maintainer's direction on #1176: dogfood pyeye). A failure names the handle, its line and the resolver's reason.
- **The handle convention:** a dotted name starting with a top-level name the dump knows, in code spans or plain prose, never glued to `/`, `.`, `-` or a word character. Fact-block content isn't scanned. A dotted name that only looks like a handle (`pkg.lock`) is allowed per page.
- No new facts; static only (C19). Rejected: a separate resolve wrapper on `structure.dump.Pyeye`. There's one resolver, the one `decisions check` uses (#1178).

**Anchor:** `pyeye.docs_facts.extractors.structure.handles_rule` / `handles_findings`; `pyeye.docs_facts.structure.handles`; `pyeye.docs_facts.structure.options.ARCHITECTURE_PAGES`; `pyeye.decision_sites.pyeye_resolver`; #1176, #1173 (ruling B), #1178.

**Applies-to:** every registered page matching a `structure` kind's `architecture_pages` globs, in every repository that configures the kind (`pyeye.docs_facts.extractors.structure.structure` brings the rule). Not other pages: pyeye's own docs, skills and decision entries aren't checked by this rule (decision entries get their own check, #1182).

**Verify:** PARTIAL. Gold: `tests/test_structure_handles.py` fails a removed and a renamed handle with file:line (in a code span and in plain text), passes a live one, and resolves a handle the dump excludes through pyeye on a fixture repo. It also asks the resolver once per distinct miss, and skips non-architecture pages and repositories without the kind. `tests/test_structure_extractor.py::TestRegistration::test_factory_owns_its_prefix_and_brings_its_rules` lists the three rules. Unverifiable: that the convention's boundaries (what counts as glued) suit every repository's prose; review false hits through page `allow` entries.
