---
date: "2026-11-23"
title: "The MCP tool surface is read from source, and the server declares what it adds to plugin tools (#1098 PR B, C19)"
issues: [1098, 818, 594, 665, 559]
anchors: ["pyeye.docs_facts.static_signatures", "pyeye.docs_facts.extractors.mcp_surface.extract", "pyeye.mcp.server.PLUGIN_TOOL_EXTRA_PARAMS", "pyeye.mcp.server.PLUGIN_TOOL_SCOPE_PARAM", "tests/test_docs_facts_static_signatures.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — The MCP tool surface is read from source, and the server declares what it adds to plugin tools (#1098 PR B, C19)

**Friction:** Ruling C19 says docs-facts never imports or runs the code it describes. PR A moved every extractor to static reads except the MCP tool surface. That one built a live server, registered the admin and plugin tools on fresh servers, and read their JSON input schemas, because a plugin tool's parameters exist only after `register_plugin_tools` wraps it. The wrapper replaces `scope` and appends `envelope` and `project_path` in code, so they weren't written anywhere a static reader could see them.

**Decision:**

- **Read the tools from source.** The new `pyeye.docs_facts.static_signatures` gives the extractor what it needs:
  - core tools are the `@mcp.tool()` functions in `pyeye.mcp.server`;
  - admin tools are the names in the `ADMIN_TOOLS` tuple;
  - plugin tools come from each class in `_PLUGIN_CLASSES`, through the class's literal `name()` return and its `register_tools()` dict of `"tool": self.method`;
  - parameters come from each function's signature, in order, with literal defaults;
  - types are its annotations rendered the way the MCP input schema states them (unions flattened, `Optional`, `list[X]`, `dict[str, X]` with `Any` shown as `dict`, a `Literal` of one scalar kind), following type aliases such as `Scope` into the module that defines them;
  - an omitted plugin `scope` defaults to `PLUGIN_FALLBACK_SCOPE`, the resolver's answer with no project config.
- **Declare what can't be read.** The server now holds two literal declarations, and builds the wrapper's signature and annotations from them:
  - `PLUGIN_TOOL_EXTRA_PARAMS`: `envelope: bool = False` and `project_path: str | None = None`;
  - `PLUGIN_TOOL_SCOPE_PARAM`: `scope` becomes `Scope | None = None`.

  One declaration serves the runtime and the docs, and a test holds the built wrapper equal to it.
- **Refuse rather than guess.** A computed default, an unknown type, a non-literal return, or `*args`/`**kwargs` on a tool is an `ExtractionError` naming the file and line.
- **Proven, then cut over:** PR A's method. The static `extract` ran beside `_extract_imported` until the twin test showed them identical: 156 facts and views, in order. Then the import path and its two `STILL_IMPORTED` ratchet entries were deleted.
- **Rejected:**
  - Keeping the live registration for this one extractor, which C19 rules out.
  - Re-encoding the wrapper's parameters inside the extractor. That would be a second copy of server behaviour that could drift.
  - Generating the JSON schema with pydantic from parsed annotations. That means running code.

**Anchor:** `pyeye.docs_facts.static_signatures` (`signature`, `type_string`, `decorated`, `tuple_names`, `returned_literal`, `returned_method_dict`, `imported_from`, `declared_params`); `pyeye.docs_facts.extractors.mcp_surface.extract`; `pyeye.mcp.server.PLUGIN_TOOL_EXTRA_PARAMS`, `PLUGIN_TOOL_SCOPE_PARAM`; design ruling C19 (#818); PR A's entry `2026-11-23-1098-docs-facts-reads-pyeyes-facts-from-source.md`; #1098.
**Applies-to:**

- the reader: `pyeye.docs_facts.static_signatures`;
- the extractor: `pyeye.docs_facts.extractors.mcp_surface.extract`;
- the server declarations and the wrapper built from them: `pyeye.mcp.server.PLUGIN_TOOL_EXTRA_PARAMS`, `pyeye.mcp.server.PLUGIN_TOOL_SCOPE_PARAM`, `pyeye.mcp.server._plugin_tool`;
- the ratchet: `tests/test_docs_facts_static.py::STILL_IMPORTED`, which no longer lists `mcp_surface`.

**Verify:** PARTIAL. Gold:

- `uv run python scripts/docs_facts.py check` exits 0 with the import path deleted, so the generated docs are byte-identical;
- `uv run pytest tests/test_docs_facts_static_signatures.py tests/test_docs_facts_static.py` passes. It covers each reader, each refusal, the declaration read statically and the built wrapper equal to it, and that no extractor imports `pyeye.mcp` or `pyeye.scope_utils`.

Unverifiable: that a future plugin wrapper change is made through the declarations rather than beside them. The wrapper test catches a mismatch only in the parameters it checks.
