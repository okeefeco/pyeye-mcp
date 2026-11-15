---
date: "2026-10-29"
title: "Dotted handles are placed by definition lookup, never by inference; a mismatched inference is not-found (#506, #544)"
issues: [506, 544]
anchors: ["pyeye.canonicalization.find_definition_name", "_resolve_class_member", "pyeye.mcp.operations.resolve._resolve_dotted_name", "_resolve_external_dotted_name", "tests/test_class_attribute_resolution.py", "tests/test_contextual_type_resolution.py::TestClassAttributeTypeResolvesContextually"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-15-623-one-canonical-handle-resolver-every-tool-echoes-the.md", "2026-11-15-544-stdlib-private-definitions-get-public-handles-os-path-is-located.md"]
superseded_by: []
---

## 2026-10-29 — Dotted handles are placed by definition lookup, never by inference; a mismatched inference is not-found (#506, #544)

**Friction:** `resolve` and `resolve_canonical` treated everything before a handle's last dot as a module. For `module.Class.attr` that missed and fell back to Jedi `infer()`, which answers "what value is this?". So `resolve` returned `found: true` with an attribute's *type* (`Widget.name: str` → `builtins.str`), or with a different project function (`Holder.factory = make_widget` → `make_widget`). Methods resolved only because a function infers to itself. The unguarded `infer()` in `resolve`'s external fallback also turned every `collections.abc` ABC into `typing._SpecialGenericAlias`, because typeshed declares those ABCs in `typing`.
**Decision:** Place a handle by walking back to the nearest module file and matching `full_name` across all scopes (`find_definition_name`). Canonicalize a member reached through a re-exported class by canonicalizing the class first. Accept an inferred definition only if its name equals the requested leaf; otherwise return not-found. For the typeshed/runtime mismatch, the guard deliberately yields honest not-found rather than a fix. Rejected: `prefer_stubs=True` (→ `typing.Mapping` in `typing.pyi`). It is cheap, but it records typeshed's reversed claim as canonical (the deprecated alias, a different runtime object), which breaks canonical = definition-site. The runtime-site fix (`_collections_abc.Mapping` via a static source-chain walk) is scoped to #544.
**Anchor:** #506 ; #544 ; `pyeye.canonicalization.find_definition_name` / `_resolve_class_member` ; `pyeye.mcp.operations.resolve._resolve_dotted_name` / `_resolve_external_dotted_name` ; `tests/test_class_attribute_resolution.py` ; `tests/test_contextual_type_resolution.py::TestClassAttributeTypeResolvesContextually`.
**Verify:** gold — `uv run pytest tests/test_class_attribute_resolution.py tests/test_contextual_type_resolution.py` passes: four class attributes resolve to themselves with their definition line, `mypackage.Widget.name` canonicalizes to `mypackage._core.widgets.Widget.name`, `resolve("collections.abc.Mapping")` is never `typing._SpecialGenericAlias`, and `json.JSONDecoder` still resolves. PARTIAL residue: `collections.abc` ABCs and `typing` special forms are now unresolved (#544 tracks the runtime-site fix); instance attributes assigned in methods are not modelled by any primitive (#565).
