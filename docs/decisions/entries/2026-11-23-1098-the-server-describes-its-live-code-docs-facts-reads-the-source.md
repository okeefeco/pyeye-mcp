---
date: "2026-11-23"
title: "The server describes the code it runs; docs-facts reads the source; a test holds them equal (#1098 Q1, Q2)"
issues: [1098, 851, 827, 856]
anchors: ["pyeye.docs_facts.describe.live_facts", "pyeye.docs_facts.extractors.edges.registry_facts", "pyeye.docs_facts.extractors.scopes.scope_facts", "pyeye.validation._RESTRICTED_ANCESTORS", "pyeye.validation.restricted_ancestors", "tests/test_docs_facts_describe.py", "tests/test_docs_facts_static.py", "tests/test_final_form_path_checks.py"]
status: "active"
amends: ["2026-11-23-1098-docs-facts-reads-pyeyes-facts-from-source.md", "2026-11-18-851-load-time-facts-come-from-installed-code-only.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The server describes the code it runs; docs-facts reads the source; a test holds them equal (#1098 Q1, Q2)

**Friction:** #1098's first PR left three extractors importing pyeye, pending two rulings. `edges.extract_code()` and `scopes.extract_code()` were the live path the server's tool descriptions use while it loads (#851), so the extractor modules imported the edge registry and `scope_utils`. `security` imported `_RESTRICTED_ANCESTORS`, a comprehension the static folder can't evaluate (C19: it never runs code).

**Decision:** the rulings coordinator-3 relayed from the designer.

- **Q1: the server keeps its live self-description.** A tool description states what the running code does, so it is rendered from the imported constants. The live readers moved out of the extractors into `pyeye.docs_facts.describe.live_facts()`. It imports the registry and `scope_utils` when first called, and renders them through the extractors' own `edges.registry_facts` and `scopes.scope_facts`. It still takes no root and reads no file (#851). The extractors now only read the source; `extract_code` and `_extract_imported` are gone.
- **The equality test.** `test_load_time_facts_are_the_registry_facts` asserts that every live slot fact equals the registry's static fact. `test_every_static_load_time_fact_is_live` asserts the other direction: every static edge and scope fact is live, except `edges.inspect_unmeasured`, which is read from a test file a wheel doesn't have. Together they replace the twin test (`tests/test_docs_facts_static_twins.py`, deleted).
- **Q2, option (ii): declare it.** `_RESTRICTED_ANCESTORS` is written as a literal. `restricted_ancestors(directories)` keeps the derivation, and `test_the_declared_ancestors_equal_their_derivation` holds the literal equal to it over `_RESTRICTED_DIRS`, so a new restricted directory fails the test until the literal is updated. The `security` extractor folds the literal.
- **The ratchet is empty.** `STILL_IMPORTED` in `tests/test_docs_facts_static.py` has no entries. No extractor imports a pyeye fact source. `mcp_surface` was cleared by #1098 PR B.

The generated docs are unchanged: `scripts/docs_facts.py check` passes with no regeneration.

**Anchor:** `pyeye.docs_facts.describe.live_facts`; `pyeye.docs_facts.extractors.edges.registry_facts`; `pyeye.docs_facts.extractors.scopes.scope_facts`; `pyeye.validation._RESTRICTED_ANCESTORS` / `restricted_ancestors`; #1098, #851, C19.

**Applies-to:** `pyeye.docs_facts.describe.live_facts`, `pyeye.docs_facts.describe.load_time_facts`, `pyeye.docs_facts.extractors.edges.extract`, `pyeye.docs_facts.extractors.scopes.extract`, `pyeye.docs_facts.extractors.security.extract`, `pyeye.validation._RESTRICTED_ANCESTORS`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_describe.py tests/test_docs_facts_static.py tests/test_final_form_path_checks.py` passes. It checks:

- live slot facts equal the static facts, both ways;
- `live_facts` takes no root, and the load-time facts build from an empty directory;
- the ratchet is empty;
- the declared ancestors equal their derivation.

`uv run python scripts/docs_facts.py check` passes.
