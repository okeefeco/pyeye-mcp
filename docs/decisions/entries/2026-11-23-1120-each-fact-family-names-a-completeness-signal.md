---
date: "2026-11-23"
title: "Each fact family names an independent completeness signal or a reason; inspect's measured-edge sets live in the edge registry (#1120)"
issues: [1120, 1098, 1092, 396, 851]
anchors: ["pyeye.mcp.operations.edges.INSPECT_EXPECTED_EDGES", "pyeye.mcp.operations.edges.INSPECT_UNMEASURED_EDGES", "pyeye.docs_facts.extractors.edges.registry_facts", "tests/test_docs_facts_completeness.py", "tests/conformance/response_linter.py"]
status: "active"
amends: ["2026-11-23-1098-the-server-describes-its-live-code-docs-facts-reads-the-source.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — Each fact family names an independent completeness signal or a reason; inspect's measured-edge sets live in the edge registry (#1120)

**Friction:** bound values can't drift silently, but an extractor finds only what it was written to find. A new concept, an env var read a new way, or a stale shape assumption gives no fact and no failure, and the ledger lists only facts that exist. Separately, the `edges.inspect_unmeasured` fact was parsed out of `tests/conformance/response_linter.py`, so product docs depended on test code that doesn't ship, and it was the one docs-only edge fact.

**Decision** (from the docs-facts drift assessment; approved by the maintainer, 2026-11-23):

- **A completeness signal per family:** `tests/test_docs_facts_completeness.py` maps every extractor in `EXTRACTORS` to one of two things. A `Signal` names a test that compares the family's facts with something its extractor doesn't read. A `Reason` says in one line why the family has none. A new family fails until it's declared, and a signal that names a missing test fails. One small test per family, not a framework.
- **env's signal is new:** a text scan of `src/pyeye` for environment reads, independent of the extractor's AST walk. Every `PYEYE_*` read has an `env.*` fact and every fact a read. A read whose name isn't a literal must be a stated indirection (`INDIRECT_READS`). A fixture proves that a loader the extractor doesn't know (`_get_path_env`) fails it.
- **Tools, edges and scopes** keep #1118's live-against-static tests as their signal. **cli, ci and repo_config** state reasons: their facts are read from the files that define them, and extraction fails when a pattern doesn't match.
- **The measured-edge sets are product code:** `INSPECT_EXPECTED_EDGES` and `INSPECT_UNMEASURED_EDGES` live in `pyeye.mcp.operations.edges`. The response linter aliases them (`_PHASE4_*`), and `registry_facts` yields `edges.inspect_unmeasured` from the registry. So the fact is live too, and this amends the #1098 Q1 entry's one docs-only exception: none remains.

**Anchor:** `pyeye.mcp.operations.edges.INSPECT_EXPECTED_EDGES`, `INSPECT_UNMEASURED_EDGES`; `pyeye.docs_facts.extractors.edges.registry_facts`; `tests/test_docs_facts_completeness.py`; #1120.

**Applies-to:**

- `pyeye.docs_facts.registry.EXTRACTORS`: a new family needs an entry in `FAMILIES`;
- `pyeye.mcp.operations.edges.INSPECT_EXPECTED_EDGES` and `INSPECT_UNMEASURED_EDGES`, and through them `tests/conformance/response_linter.py` (B.3) and the `edges.inspect_unmeasured` fact;
- `pyeye.docs_facts.extractors.env.extract`: its facts are checked against the text scan.

**Verify:** gold. `uv run pytest tests/test_docs_facts_completeness.py tests/test_docs_facts_rules.py tests/test_docs_facts_describe.py` passes. It covers:

- every family is declared, and every named signal test exists;
- env reads and facts agree both ways, a missed loader is caught (fixture), and a read through a variable is caught;
- the linter's sets are the registry's objects;
- the fact builds from a checkout with no `tests/`;
- every static edge and scope fact is live.

`uv run python scripts/docs_facts.py generate` leaves the tree unchanged.
