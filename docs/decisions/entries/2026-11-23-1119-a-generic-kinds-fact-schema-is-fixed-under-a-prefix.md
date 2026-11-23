---
date: "2026-11-23"
title: "A generic kind's fact schema is fixed, under a configurable prefix; no ID or markdown templates (#1119)"
issues: [1119, 1107, 1091]
anchors: ["pyeye.docs_facts.entry_points.factory", "pyeye.docs_facts.kinds.BUILT_IN_KINDS", "pyeye.docs_facts.pyeye_kinds.REMAINING", "pyeye.docs_facts.pyeye_kinds.PYEYE_KINDS", "tests/test_docs_facts_entry_points.py", "tests/test_docs_facts_pyeye_kinds.py"]
status: "active"
amends: ["2026-11-23-1107-pyeyes-docs-facts-setup-is-data-pyeye-kinds-no-preset.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A generic kind's fact schema is fixed, under a configurable prefix; no ID or markdown templates (#1119)

**Friction:** #1119 turns pyeye-only extractor kinds into generic kinds any repository can configure, and each conversion must give pyeye byte-identical facts. The easy way to reach byte-identity is a config vocabulary of ID patterns, markdown templates and view shapes. That vocabulary would be a public contract other repositories write, and it grows with every kind.

**Decision:** A generic kind defines its own fact IDs, values, markdown and views. Its config chooses only what it reads (e.g. `package`, `module`) and the first ID segment (`prefix`). Unknown options are refused (`KindOptionsError`). `pyeye-cli` became `entry-points` on these terms: pyeye's facts were already that schema under the prefix `cli`. A kind that can't reach byte-identity this way stays `pyeye-*` until a ruling. A template vocabulary (the `call-table` proposal for scopes, resolver and review) needs the maintainer's ruling first. The remaining count is the constant `pyeye_kinds.REMAINING`, shown in the docs-facts dev doc as the `literal` fact `docs_facts.pyeye_kinds_remaining`.

**Anchor:** `pyeye.docs_facts.entry_points.factory`; `pyeye.docs_facts.kinds.BUILT_IN_KINDS`; `pyeye.docs_facts.pyeye_kinds.REMAINING`; #1119, #1107, #1091.

**Applies-to:** every generic (non-`pyeye-*`) kind registered in `pyeye.docs_facts.kinds.BUILT_IN_KINDS`: today `entry-points`; #1092's `structure` registers there too and is governed by this rule. The `pyeye-*` kinds take no options at all (`pyeye.docs_facts.pyeye_kinds._kind`). The data-fact kinds (`toml`/`json`/`yaml`/`literal`, `pyeye.docs_facts.data_facts`) already let the config name each fact's ID, one fact per entry, and are not templates.

**Verify:** PARTIAL. Gold: `tests/test_docs_facts_entry_points.py` refuses an unknown option and a multi-segment prefix, and proves pyeye's `cli` facts equal the committed `docs/facts/facts.json`. `tests/test_docs_facts_pyeye_kinds.py::TestTheKinds::test_the_count_only_shrinks` asserts `len(PYEYE_KINDS) == REMAINING <= 11`. Unverifiable: that no future generic kind adds ID or markdown templates. No test sweeps every kind's option set, so that needs review.
