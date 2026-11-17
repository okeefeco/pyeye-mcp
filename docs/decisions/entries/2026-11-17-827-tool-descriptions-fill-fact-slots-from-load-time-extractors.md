---
date: "2026-11-17"
title: "Tool descriptions fill <<fact:…>> slots from the load-time extractors; parameters are checked, not slotted (#827)"
issues: [827, 818, 824]
anchors: ["pyeye.docs_facts.describe.fill", "pyeye.docs_facts.describe.described", "pyeye.docs_facts.describe.hand_lists", "pyeye.docs_facts.describe.LOAD_TIME_EXTRACTORS", "pyeye.docs_facts.extractors.scopes.extract", "pyeye.scope_utils.SCOPE_FORMS", "pyeye.scope_utils.PLUGIN_FALLBACK_SCOPE", "pyeye.mcp.server.PLUGIN_PROJECT_PATH_NOTE", "tests/test_docs_facts_describe.py", "tests/test_docs_facts_scopes.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-18-827-each-exposed-edge-states-its-own-ceiling.md"]
superseded_by: []
---

## 2026-11-17 — Tool descriptions fill <<fact:…>> slots from the load-time extractors; parameters are checked, not slotted (#827)

**Friction:** The MCP tool descriptions hand-copied facts the code owns, and they drifted. `trace` listed seven traversed edges when it follows nine (`submodules` and `re_exports` were missing). `expand`'s bullet list had no `submodules` entry, and its kind table left out `re_exports`. Twenty plugin tools described three scope forms out of six, and said `all` means "include configured namespaces". `resolve` and every plugin tool had a parameter (`max_candidates`, `envelope`) that no description named. #818 D9 says the fact parts of a description come from the same extractors as the docs.

**Decision:**

- **Slots, not format strings.** A docstring writes a fact part as `<<fact:ID>>` or `<<fact:ID:FORM>>` (forms `list`, `bullets`, `applies_to`), rendered in the docstrings' RST style. `str.format` was rejected because descriptions hold literal braces (JSON shapes). Core tools carry `@described` (innermost, so the wrappers copy the filled text). Plugin tools are filled in the server's plugin wrapper. An unknown ID or form, a malformed token, or a multi-line (`bullets`) slot that isn't on a line of its own raises `SlotError` while the server loads.
- **Only load-time extractors fill slots.** They are `edges` and the new `scopes`, which never read `pyeye.mcp.server`. `mcp_surface` reads the registered tools, so it can't describe them while they register. `describe` imports the extractors on first fill, and `edges` imports the edge registry inside `extract()`. Without that, `pyeye.mcp`'s package `__init__`, which imports the server, closed a cycle.
- **Parameters are checked, not slotted.** Repeating a tool's schema in its own prose adds nothing. A test requires each `Args` section to name exactly the parameters in the registered schema. The plugin wrapper's `envelope` and `project_path` are documented once, in `PLUGIN_PROJECT_PATH_NOTE`.
- **The hand-list rule.** Outside the slots, a paragraph that names three or more members of a guarded view (`edges.implemented`, `edges.deferred`, `ceilings.table`, `scopes.options`) must name all of them. A complete list with prose per member is allowed, because a new member then fails it. A partial list must be a slot. One or two examples are fine.
- **One scope grammar.** `scope_utils.SCOPE_FORMS` is the single list. The `scope` extractor (`scope.option.<form>`, `scope.default.plugin`, views `scopes.options` and `scopes.table`) reads it, and a test checks it against `resolve_scope_paths`'s own branches. Each tool's effective default stays on its `mcp_surface` parameter fact; the policy is the `scope` extractor's. `ScopeValidator`'s divergent copy is #836.
- **No contract change.** Only description text changes. No signature or schema changes, and `no-breaking` prints 0.

**Anchor:** `pyeye.docs_facts.describe` (`fill`, `described`, `hand_lists`, `LOAD_TIME_EXTRACTORS`); `pyeye.docs_facts.extractors.scopes.extract`; `pyeye.scope_utils.SCOPE_FORMS`; #827, #818 (D9, §5), #824.
**Applies-to:**

- the filler and rule: `pyeye.docs_facts.describe.fill`, `described`, `hand_lists`;
- the slotted descriptions: `pyeye.mcp.server.expand`, `pyeye.mcp.server.trace`, and every plugin tool through `pyeye.mcp.server._plugin_tool`;
- the scope grammar: `pyeye.scope_utils.SCOPE_FORMS`, `pyeye.scope_utils.PLUGIN_FALLBACK_SCOPE`, `pyeye.docs_facts.extractors.scopes.extract`;
- the wrapper parameters' one description: `pyeye.mcp.server.PLUGIN_PROJECT_PATH_NOTE`.

**Verify:** gold. `uv run pytest tests/test_docs_facts_describe.py tests/test_docs_facts_scopes.py` passes:

- a bad slot raises `SlotError`;
- no registered core, admin or plugin description keeps a slot token or hand-writes a partial guarded list;
- every `Args` section matches its schema;
- the load-time extractors import nothing from the server;
- slot facts equal the registry's facts;
- `SCOPE_FORMS` equals `resolve_scope_paths`'s branches, and every form resolves without a warning;
- the default policy matches `SmartScopeResolver.plugin_tool_default`.
