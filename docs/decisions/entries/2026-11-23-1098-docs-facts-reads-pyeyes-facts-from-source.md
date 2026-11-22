---
date: "2026-11-23"
title: "docs-facts reads pyeye's facts from its source, never by importing it: a constant folder, twins proven equal, a ratchet (#1098, C19)"
issues: [1098, 1091, 1083, 818, 851, 827]
anchors: ["pyeye.docs_facts.static", "pyeye.duplication.COMMANDS", "tests/test_docs_facts_static.py", "tests/test_docs_facts_static_twins.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — docs-facts reads pyeye's facts from its source, never by importing it: a constant folder, twins proven equal, a ratchet (#1098, C19)

**Friction:** the maintainer's ruling C19 (2026-11-22, recorded in the #818 design doc, PR #1097): no runtime facts anywhere, pyeye's own repo included. A deterministic fact can be read from what is written in code; a non-deterministic one is useless as a fact. pyeye's own extractors imported pyeye to read their facts: its settings, config, resolver tables, edge registry, validator constants, the duplication CLI's argparse parser and the MCP registrations. #1091's per-repo config was going to allow `pyeye.*` import refs on that basis, and C19 removes that exception.

**Decision:** the inventory and phasing approved by coordinator-3, 2026-11-22. This is PR A: every extractor but `mcp_surface`, which is PR B.

- **`pyeye.docs_facts.static`, a constant folder over `ast`.** It evaluates:
  - literals;
  - a name bound to a constant, in the same module or imported from a `pyeye` module (absolute or relative), folded there;
  - f-strings over those;
  - `frozenset`, `set`, `tuple` and `list` of a literal or of nothing;
  - the `-`, `|`, `&` and `+` operators.

  It never calls anything. Any other node raises `ExtractionError`, naming its file and line and saying to write it as a literal. Registries written as calls (`Step("name", "summary", fn)`, `ScopeForm(...)`) give their literal arguments (`call_args`); the function arguments are never touched. A dict's literal keys come from `dict_keys`, docstrings from `ast.get_docstring`, and module source from `<root>/src/pyeye/...`, never `pyeye.__file__`.
- **Twins proven equal.** Each extractor got a static `extract` beside its import-based `_extract_imported`, and a test asserted equal facts and views, in order, on this repo: cli, duplication, edges, env, repo_config, resolver, review, scopes and security. Then the import paths were deleted, in a separate commit, so the proof stays in history. `ci` was already static.
- **Declare what can't be read.** The duplication CLI builds its subcommands in a loop, so its vocabulary is declared as `pyeye.duplication.COMMANDS`, and a test holds the parser equal to it. `edges.edge_status` is re-expressed over the declared status sets; the twin test proved it identical.
- **The ratchet.** `test_extractors_import_no_fact_source_beyond_the_ratchet` pins the pyeye modules an extractor still imports for facts. Each entry names the ruling that removes it; the list only shrinks, and an entry that is no longer imported fails too. The engine's own helpers (`path_utils`, `async_utils`) are tools, not fact sources.
- **Kept, pending rulings:**
  - `edges.extract_code()` and `scopes.extract_code()` stay live. The server fills its tool descriptions from them while it loads (#827, #851), and Q1 (static reading of the installed source, or live) is with the designer. Their twin test holds the live and static facts equal meanwhile.
  - `security` imports `_RESTRICTED_ANCESTORS`, a comprehension: Q2, derive or declare.
  - `mcp_surface` is PR B.
- **The output is byte-identical:** `scripts/docs_facts.py generate` writes nothing, and `check` passes.

**Anchor:** `pyeye.docs_facts.static.constant` / `call_args` / `dict_keys` / `docstring` / `Module`; `pyeye.duplication.COMMANDS`; `pyeye.docs_facts.extractors.edges._StaticRegistry`; #1098, C19, #1091.

**Applies-to:** `pyeye.docs_facts.static`, `pyeye.duplication.COMMANDS`, `pyeye.docs_facts.extractors.cli.extract`, `pyeye.docs_facts.extractors.duplication.extract`, `pyeye.docs_facts.extractors.edges.extract`, `pyeye.docs_facts.extractors.env.extract`, `pyeye.docs_facts.extractors.repo_config.extract`, `pyeye.docs_facts.extractors.resolver.extract`, `pyeye.docs_facts.extractors.review.extract`, `pyeye.docs_facts.extractors.scopes.extract`, `pyeye.docs_facts.extractors.security.extract`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_static.py tests/test_docs_facts_static_twins.py tests/test_duplication.py` passes. It checks:

- the folder folds each supported form and refuses calls, comprehensions and attributes of non-pyeye modules, with the file and line;
- the ratchet holds;
- `edges` and `scopes` live equals static;
- `COMMANDS` equals the parser.

`git show 623a9d19` holds the twin proof for all nine extractors. `uv run python scripts/docs_facts.py generate` writes nothing, and `check` passes.
