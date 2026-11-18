---
date: "2026-11-18"
title: "Classes that can't be placed are disclosed in find_pydantic_models' envelope, capped (#921)"
issues: [921, 568, 594, 435, 842]
anchors: ["pyeye.plugins.pydantic.PydanticPlugin.envelope_extras", "pyeye.plugins.pydantic.PydanticPlugin._unplaced_classes", "pyeye.plugins.base.AnalyzerPlugin.envelope_extras", "pyeye.mcp.operations.completeness.TRUNCATION_REASONS"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-18 — Classes that can't be placed are disclosed in find_pydantic_models' envelope, capped (#921)

**Friction:** a class whose base is an expression (`class M(make_base())`) has no static base, so the class graph can't say whether it's a model, and `find_pydantic_models` dropped it silently. The result then read as the complete set of models (#568). #930 made such bases unresolved on the `superclasses` edge; this decision covers the disclosure.

**Decision** (the maintainer's, 2026-11-18):

- **The envelope gains `unplaced_classes`.** With `envelope=true`, `find_pydantic_models` returns it beside `scope`, `searched`, `unsearched_scopes` and `results`. Each entry is `{name, file, line, base}`, where `base` is the source text of the first base that can't be placed. The key is always present, `[]` when none.
- **It covers every such class in the searched scope**, with no pydantic-looking filter, because we can't tell which ones are models. "Can't be placed" means that, after subscripts are removed, the base is neither a name nor an attribute: the rule #930 set for the class graph and `superclass_bases`.
- **It follows the bounded-response contract (#435).** The `max_unplaced` parameter (default 50, `None` for all) caps the list. When it cuts, the envelope carries `truncated: true`, `truncation_reasons: ["max_unplaced"]` and `total`. `max_unplaced` is a registered budget reason. The trio refers to `unplaced_classes` only, and the tool description says so: **`results` is never capped**.
- **The bare-list form is unchanged,** like `unsearched_scopes` (#594, #842). The core `subclasses` edge gains no field; its `literal_subclassing` ceiling already says class factories aren't included.
- **A generic hook,** `AnalyzerPlugin.envelope_extras`, adds tool-specific envelope keys, so `server.py` has no tool-specific branch.
- **Classified `added`,** for v2.2.0.

**Anchor:** `pyeye.plugins.pydantic.PydanticPlugin.envelope_extras`, `_unplaced_classes`; `pyeye.plugins.base.AnalyzerPlugin.envelope_extras`; the `max_unplaced` reason in `pyeye.mcp.operations.completeness.TRUNCATION_REASONS`; #921, #568, #594, #435, #842.
**Applies-to:**

- the disclosure: `pyeye.plugins.pydantic.PydanticPlugin.envelope_extras`, `pyeye.plugins.pydantic.PydanticPlugin._unplaced_classes`;
- the envelope merge: `pyeye.plugins.base.AnalyzerPlugin.envelope_extras`, through the plugin-tool wrapper in `pyeye.mcp.server`;
- the cap: the `max_unplaced` entry in `pyeye.mcp.operations.completeness.TRUNCATION_REASONS` and `pyeye.mcp.operations.completeness.DEFAULT_MAX_UNPLACED`.

**Verify:** GOLD. `uv run pytest tests/test_plugin_unplaced_classes.py tests/test_completeness_registry.py` covers:

- every expression-base class listed, and subscripted bases placed;
- `[]` when none;
- the cap's `truncated`/`total` with the full `results` kept;
- `None` lifting the cap;
- an invalid cap as a tool error;
- the bare list unchanged;
- the description saying `results` is never capped;
- the reason registered as a budget reason.
