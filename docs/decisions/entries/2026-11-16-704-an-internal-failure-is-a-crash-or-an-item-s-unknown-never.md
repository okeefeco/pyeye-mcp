---
date: "2026-11-16"
title: "An internal failure is a crash, or one item's unknown; never \"unresolved\" or a measured empty (#704)"
issues: [704, 684, 626, 623, 703]
anchors: ["pyeye.resolver.resolve_handle", "resolve_item", "resolve_name", "_synthetic_import", "_place_definition", "pyeye.canonicalization.collect_re_exports", "_scan_package_for_handle", "pyeye.mcp.operations.resolve._resolve_at_position", "pyeye.mcp.operations.edges"]
status: "active"
amends: ["2026-11-15-626-one-error-channel-caller-errors-are-mcp-tool-errors.md", "2026-11-15-623-one-canonical-handle-resolver-every-tool-echoes-the.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-16 — An internal failure is a crash, or one item's unknown; never "unresolved" or a measured empty (#704)

**Friction:** #684's parso `KeyError` hid for days. `resolve_handle` and `_synthetic_import` caught `Exception` and answered `found: false, reason: "unresolved"`, a confident statement about the user's code that was really a pyeye bug. The same pattern was elsewhere.

- Definition placement, bare-name lookup and goto-at-position reported a miss.
- The edges' own-file loads returned `stubs: []`.
- `collect_re_exports` returned `[]`, even though `inspect` was already written to leave `re_exports` absent if collection raised.

Slice C of #626 already said that anything but a caller error "is a genuine bug… stays a loud, logged crash"; these catches broke that.

**Decision:** two rules, by the subject of the failure.

- **Single subject → loud crash.** When the thing the caller asked about can't be computed, the exception propagates, and the SDK reports "Error executing tool X" with the traceback logged.
  - This covers `resolve_handle`, `_synthetic_import`, `_place_definition`, `_anchor_at_stdlib_definition`, `resolve_name`'s lookups, `_resolve_at_position`, and an edge loading its own file.
  - `resolve_handle` is now "never raises **for a miss**".
- **Per item → that item's unknown.** One bad item in a multi-item answer doesn't sink the call. `resolver.resolve_item` logs the failure with its traceback and returns a `NotFound` whose detail says it was an internal error, not a fact about the code. The caller reports it through its existing signal:
  - trace: `unresolved_roots` / `unresolved_nodes`;
  - `imports`: the goto fallback or `unresolved_imports`;
  - a typeref: its handle is left absent;
  - a plugin record: its `unresolved` marker;
  - subclass base canonicalisation.
- **No per-item signal → crash, and the field is omitted.** `re_exports` has none, so a failing file propagates out of `collect_re_exports` to `inspect`'s guard. The field is then ABSENT (unknown), never `[]`. Fields like this are candidates for #435's shared completeness envelope; no new field is invented here.
- Parse failures stay #703's `unparseable`. Honest expected misses are unchanged: `goto_target`'s counted `unresolved_*` (including #650's `RecursionError`), shape probes, and optional-field probes (absent = unknown).
- Rejected: a typed `internal_error` reason in the not-found shape. It would put bugs back in the lookup-ran channel that #626 keeps for answers.

**Anchor:** `pyeye.resolver.resolve_handle`, `resolve_item`, `resolve_name`, `_synthetic_import`, `_place_definition`; `pyeye.canonicalization.collect_re_exports`, `_scan_package_for_handle`; `pyeye.mcp.operations.resolve._resolve_at_position`; the edges' own-file loads; #704, #684, #626.
**Applies-to:**

- the single-subject sites `pyeye.resolver.resolve_handle`, `_synthetic_import`, `_place_definition`, `_anchor_at_stdlib_definition`, `resolve_name`, `pyeye.mcp.operations.resolve._resolve_at_position`, and the own-file loads in `pyeye.mcp.operations.edges` (`_class_members`, `_module_members`, `resolve_callees`, `resolve_imports`, `resolve_enclosing_scope`, `superclass_bases`);
- the field with no per-item signal: `pyeye.canonicalization.collect_re_exports` / `_scan_package_for_handle`, via `inspect`'s `re_exports` guard;
- the per-item callers of `pyeye.resolver.resolve_item`:
  - `pyeye.mcp.operations.trace` (roots, nodes);
  - `pyeye.mcp.operations.typeref` (`_stdlib_binding_handle`, `_resolve_head_in_scope`);
  - `pyeye.mcp.operations.edges` (`_stdlib_import_target`, `_canonical_import_targets`);
  - `pyeye.plugins.handles`;
  - `JediAnalyzer` subclass base canonicalisation;
- the tests `tests/test_internal_errors_not_unresolved.py`.

**Verify:** gold. `uv run pytest tests/test_internal_errors_not_unresolved.py` passes:

- an exception injected at each single-subject site propagates, and through `mcp.call_tool` it is an `UnexpectedToolError`, never `found: false`;
- with one failing file `inspect` answers and `re_exports` is absent;
- `resolve_item` logs and labels the internal error;
- a trace with one failing root walks the others, and an `imports` edge with one failing target still answers;
- genuine misses are still responses.
