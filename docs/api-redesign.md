# PyEye API Redesign: resolve / inspect

> This page records the **design** of the resolve / inspect redesign. For the
> response shapes as they are now, see [tools.md](reference/tools.md),
> [edges.md](reference/edges.md) and the
> [python-explore skill](../.claude/skills/python-explore/SKILL.md).

## Overview

This document describes the redesigned PyEye API surface introduced across
Phases 1–8. The redesign replaces the legacy LSP-bridge tools with six
progressive-disclosure operations — `resolve`, `resolve_at`, `inspect`,
`outline`, `expand`, and `trace` — optimised for cheap, pointer-first code
navigation. All six are shipped, live MCP tools. The canonical,
conformance-tested reference for the full set (and the supported edges) lives in
`.claude/skills/python-explore/SKILL.md`; this document covers the design background and
documents the `resolve` / `resolve_at` / `inspect` intake operations in detail.

### Why a redesign?

The original PyEye tools (`find_symbol`, `goto_definition`, `get_type_info`,
etc.) were modelled on LSP-bridge tools: each response shipped full source
context. That makes sense for humans reading an editor, but wastes wire
bandwidth when an AI agent just needs a structural fact.

An `mcp-language-server` `definition` call for `GranularCache` (a large class,
since deleted in #628) shipped the class's full source with every copy, while
`inspect` on the same class returned only its structural facts. The measured
baseline and the ratio `inspect` must stay within are recorded in
`tests/conformance/test_spec_acceptance.py`, which keeps the LSP-bridge size as
a fixed literal (`LSP_BRIDGE_BASELINE_BYTES`) and checks `inspect` on a large
live class (`JediAnalyzer`) against it.

### Current status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Handle type + canonicalization | Done |
| 2 | `resolve()` operation | Done |
| 3 | `resolve_at()` operation | Done |
| 4 | `inspect()` with edge counts | Done |
| 5 | `outline()` operation | Done |
| 6 | `re_exports` wired into `inspect` | Done |
| 7.1 | Conformance linter + pre-commit hook | Done |
| 7.2–7.5 | Spec acceptance tests (closeout) | Done |
| 8 | TypeRef recursive trees on type-bearing fields | Done |

`expand()` and `trace()` are also shipped, live MCP tools. The full primitive
set (`resolve` / `resolve_at` / `inspect` / `outline` / `expand` / `trace`) is
implemented. For the edges they traverse, see the live edge list in
`.claude/skills/python-explore/SKILL.md` and `docs/reference/edges.md`; this page
doesn't repeat it.

---

## The intake operations: `resolve` / `resolve_at` / `inspect`

These three intake operations are documented in full below. The remaining
primitives — `outline`, `expand`, and `trace` — are shipped and documented in
`.claude/skills/python-explore/SKILL.md` (the single source of truth, per #374).

### `resolve(identifier, project_path?)`

Converts any identifier form to a canonical handle.

**Supported identifier forms:**

1. Bare name: `Config`
2. Fully-qualified dotted name: `mypackage._impl.config.Config`
3. Re-exported public path: `mypackage.Config` (collapses to definition site)
4. File path with line: `src/pyeye/cache.py:238`
5. File path only: `src/pyeye/cache.py`

**Returns:** `ResolveResult` — one of three variants:

```jsonc
// Success
{
  "found": true,
  "handle": "mypackage._impl.config.Config",
  "kind": "class",
  "scope": "project",
  "location": {
    "file": "/abs/path/to/project/src/mypackage/_impl/config.py",
    "line_start": 10, "line_end": 22, "column_start": 6, "column_end": 12
  }
}

// Not found (reason is one of "unresolved", "file_not_found", "no_symbol_at_position")
{
  "found": false,
  "identifier": "UnknownClass",
  "reason": "unresolved",
  "detail": "'UnknownClass' did not resolve to a symbol. Check the spelling, or call resolve('UnknownClass') with the bare name to search the whole project."
}

// Ambiguous (a bare name matches several definitions)
{
  "found": true,
  "ambiguous": true,
  "candidates": [
    {"handle": "pkg_a.Widget", "kind": "class", "scope": "project", "location": {...}},
    {"handle": "pkg_b.Widget", "kind": "class", "scope": "project", "location": {...}}
  ]
}
```

**Re-export canonicality:** `resolve("mypackage.Config")` and
`resolve("mypackage._impl.config.Config")` return the same handle — the
definition site — when `Config` is re-exported in `mypackage/__init__.py`.

---

### `resolve_at(file, line, column, project_path?)`

Converts a source position to a canonical handle. Useful when the agent has
a file and line number from another tool (e.g. a lint error) and wants to
navigate to the definition.

**Returns:** same `ResolveResult` variants as `resolve()`.

**Example:**

```json
resolve_at("src/mypackage/_impl/config.py", 10, 6) →
{
  "found": true,
  "handle": "mypackage._impl.config.Config",
  "kind": "class",
  "scope": "project",
  "location": {...}
}
```

---

### `inspect(handle, project_path?)`

Returns a structural Node for a canonical handle. This is the main
"what is this?" operation. Returns kind, signature, location, docstring, and
kind-dependent fields. **Never returns source content.**

**Example:**

```json
inspect("mypackage._impl.config.Config") →
{
  "found": true,
  "handle": "mypackage._impl.config.Config",
  "kind": "class",
  "scope": "project",
  "location": {
    "file": "/abs/path/to/project/src/mypackage/_impl/config.py",
    "line_start": 10,
    "line_end": 22,
    "column_start": 6,
    "column_end": 12
  },
  "docstring": "Project configuration.",
  "signature": "Config(path: str)",
  "superclasses": ["mypackage._impl.base.BaseConfig"],
  "edge_counts": {"members": 12, "superclasses": 1},
  "re_exports": ["mypackage.Config"]
}
```

---

## The Node response shape

Every `inspect` response is a Node dict. Fields come in two layers:

### Universal fields (always present)

| Field | Type | Description |
|-------|------|-------------|
| `handle` | `str` | Canonical dotted-name handle |
| `kind` | `str` | One of: `class`, `function`, `method`, `module`, `variable`, `attribute`, `property`, `enum_member`. A class-body binding is `attribute`; a member of an `enum.Enum` subclass is `enum_member` (#695) |
| `scope` | `str` | `"project"` or `"external"` |
| `location` | `dict` | Pointer to the definition (see below) |
| `docstring` | `str \| null` | The symbol's full docstring, raw, or null when it has none |
| `edge_counts` | `dict` | Measured edge counts (see below) |

### Kind-dependent fields

The rows below are the design record, not the full list. For the fields
`inspect` returns today, see the executed `inspect` example under Worked
Examples in [the python-explore skill](../.claude/skills/python-explore/SKILL.md#worked-examples).

| Field | Kinds | Description |
|-------|-------|-------------|
| `signature` | function, method, class | Single-line call/class signature |
| `superclasses` | class | List of canonical handles for base classes |
| `parameters` | function, method | Typed parameter list — each entry's `type` is a recursive `TypeRef` tree (see below), not a string |
| `return_type` | function, method | Recursive `TypeRef` tree for the return annotation (see below), not a string |
| `re_exports` | non-module | Re-export aliases, deprecated (see [Re-exports](#re-exports)) |

### Location shape

```json
{
  "file": "/abs/path/to/project/src/mypackage/_impl/config.py",
  "line_start": 10,
  "line_end": 22,
  "column_start": 6,
  "column_end": 12
}
```

- `file` is an absolute path, spelled the way you spelled `project_path`.
- `line_start`/`line_end` — span the full definition body
- `column_start`/`column_end` — span the name token only
- **No source content** — location is a pointer. Use the `Read` tool
  if you need the actual text.

---

## Edge counts and the absence-vs-zero invariant

`edge_counts` is **always present** on every `inspect` response. It is never
null and never absent — though it may be an empty `{}` for kinds with no
cheaply-measurable edges (see below).

### Measured edges per kind

| Kind | Measured edges |
|------|---------------|
| `class` | `members`, `superclasses` |
| `function`, `method` | _(none — see note)_ |
| `module` | `members`; also `submodules` for a package (absent for a plain module) |
| `variable`, `attribute`, `property` | _(none — see note)_ |

An edge whose measurement overruns its time budget is left out of
`edge_counts`, not reported as `0`.

`edge_counts` reports only edges derivable cheaply from the symbol's own
definition. Three edge types that earlier drafts measured are no longer in
`edge_counts`:

- `subclasses` — counting them needs the same project-wide inheritance scan as
  listing them, so it has no cheap-preview value; it is **expand-only**
  (`expand(handle, edge="subclasses")`), per #392.
- `callers`, `references` — deferred to an indexed reference backend (Pyright,
  #333). They are **omitted** (not `0`), so the absence-vs-zero invariant holds:
  a present `0` means measured-none, an absent key means not-measured.

Kinds whose only edges were the deferred ones (functions, methods, variables,
attributes, properties) therefore get an empty `edge_counts: {}` today.

### The invariant

> A measured edge is **present** (even with value `0`).
> An unmeasured edge is **absent** (not `0`).

This is the **absence-vs-zero invariant**. It lets agents distinguish "we
measured zero" from "we don't yet measure this edge type."

It is one case of a general rule that applies to every response, not only to
`edge_counts`:

> A value pyeye returns is a measured claim over a stated scope. Anything it
> doesn't return, or can't resolve, is unknown, not absent.

- **`found: false`** is a resolution miss. It does not show that the symbol is
  missing from the code: an instance attribute assigned in `__init__`
  (`self.project_path = ...`) is real and does not resolve.
- **A returned list** is complete only over its stated scope. A class's
  `members` (and so its `outline`) are its class-body definitions; instance
  attributes assigned in methods are not measured, and runtime-injected members
  are not seen. A name missing from the list is unknown outside that scope.
- **An optional field** that is absent means "not measured", as above.

Examples:

```json
// class — members + superclasses measured
"edge_counts": {"members": 12, "superclasses": 1}

// function/method — no edges measured (callers/references deferred, #332/#333)
"edge_counts": {}

// variable — no edges measured
"edge_counts": {}
```

The same rule applies to list fields:

- `re_exports: []` — measured, zero aliases found
- `re_exports` absent — not measured for this kind (e.g. module)
- `re_exports: null` — **never valid** (conformance linter rejects this)

---

## Locations are spans

The `location` dict encodes two overlapping spans:

- **Full definition span:** `line_start` to `line_end` — the entire body,
  from the `def`/`class` keyword to the last line of the body.
- **Name span:** `column_start` to `column_end` on `line_start` — just the
  identifier token.

This gives agents both a precise cursor position (for editors) and a range
they can pass to `Read` if they need the body text.

---

## Project/external boundary

`inspect` works on both project-internal and external (stdlib/third-party)
handles. The `scope` field distinguishes them:

```json
inspect("pathlib.PurePath") →
{
  "handle": "pathlib.PurePath",
  "kind": "class",
  "scope": "external",
  "edge_counts": {"members": 47, "superclasses": 1}
}
```

For external handles:

- `scope` is `"external"`
- `expand(handle, edge="subclasses")` lists **project-internal** subclasses
  only — not stdlib subclasses of the same base. This tells you how many places
  in your project extend an external class. (`subclasses` is an expand-only
  edge; it is not in `edge_counts` — see #392.)
- All other universal fields are populated from Jedi's analysis.

---

## Re-exports

> **Note:** `re_exports` on `inspect` is deprecated; use
> `expand(handle, "re_exports")` (see [the edges reference](reference/edges.md)).
> The rest of this section is kept as the design record.

`re_exports` lists the public aliases for a symbol. If `Config` is defined
in `mypackage._impl.config` and re-exported from `mypackage`, then:

```json
inspect("mypackage._impl.config.Config") →
{
  "handle": "mypackage._impl.config.Config",
  "re_exports": ["mypackage.Config"],
  ...
}
```

Both `resolve("mypackage.Config")` and
`resolve("mypackage._impl.config.Config")` return the same canonical handle.
The re-export list on the canonical handle is the inverse mapping — all
public paths that route to this definition.

---

## Type fields are `TypeRef` trees, not strings

Every type-bearing field on an `inspect` response — `parameters[].type`,
`return_type`, and the `type` field on attribute, property and variable
nodes — is a recursive `TypeRef` tree, not a flat string. This
preserves navigability through compound types (generics, unions,
parameterized forms) without forcing the agent to client-side-parse type
expressions.

### Shape

```jsonc
type TypeRef = {
  raw: string,        // annotation as written for THIS subtree slice (always present)
  handle?: string,    // canonical handle when the head has exactly one referent
  args?: TypeRef[]    // recursive children for parameterized types
}
```

Three fields, no discriminator. Agents that don't navigate types can read
`raw` and ignore the rest.

### Worked example

`inspect()` on a function declared as
`def process(x: Dict[str, List[CustomModel]]) -> List[CustomModel]`
(with `from typing import Dict, List` and a project-local `CustomModel`)
returns:

```jsonc
{
  "handle": "service_typing_aliases.process",
  "kind": "function",
  "scope": "project",
  "signature": "process(x: Dict[str, List[CustomModel]]) -> List[CustomModel]",
  "parameters": [
    {
      "name": "x",
      "kind": "positional_or_keyword",
      "type": {
        "raw": "Dict[str, List[CustomModel]]",
        "handle": "typing.Dict",
        "args": [
          { "raw": "str", "handle": "builtins.str" },
          {
            "raw": "List[CustomModel]",
            "handle": "typing.List",
            "args": [
              { "raw": "CustomModel", "handle": "models.CustomModel" }
            ]
          }
        ]
      }
    }
  ],
  "return_type": {
    "raw": "List[CustomModel]",
    "handle": "typing.List",
    "args": [
      { "raw": "CustomModel", "handle": "models.CustomModel" }
    ]
  },
  "edge_counts": {},
  "re_exports": []
}
```

The `handle` on each subtree is composable: an agent that wants to drill
into `models.CustomModel` calls `inspect("models.CustomModel")` directly —
no string parsing, no `resolve` round-trip.

### Head-canonicalisation: `typing.Dict` vs `builtins.dict`

The same shape written with PEP 585 builtins
(`def process(x: dict[str, list[CustomModel]])` — no `typing` import)
yields **distinct** root handles:

```jsonc
"type": {
  "raw": "dict[str, list[CustomModel]]",
  "handle": "builtins.dict",
  "args": [
    { "raw": "str", "handle": "builtins.str" },
    {
      "raw": "list[CustomModel]",
      "handle": "builtins.list",
      "args": [
        { "raw": "CustomModel", "handle": "models.CustomModel" }
      ]
    }
  ]
}
```

The implementation MUST NOT silently rewrite `typing.Dict` → `builtins.dict`
or vice-versa. Modern Python treats `typing.Dict` as a deprecated alias for
`builtins.dict`, but that's metadata on the symbol itself —
discoverable via `inspect("typing.Dict")` — not a transformation pyeye
applies in the wire format. Preserving what the source actually wrote keeps
the response honest.

### Absence-vs-zero applies per node

The same invariant from `edge_counts` applies inside a single TypeRef:

- `handle` absent on a node = "no single canonical referent for the head,
  OR we couldn't resolve it confidently."
- `args` absent on a node = "this is a bare name (not parameterized)."
- Both absent on a leaf = "we have the raw text only."

Per-leaf degradation does not poison the rest of the tree —
`Dict[str, UnknownThirdParty]` legitimately yields `handle: "typing.Dict"`
at the root, `handle: "builtins.str"` on the first arg, and
`{ "raw": "UnknownThirdParty" }` (no handle) on the second.

### No-guess discipline

`handle` is populated **only** when Jedi `goto` (with file/line context for
the annotation site) returns exactly one definition. Best-effort global
bare-name search is non-conforming — the field's value is its certainty,
and a wrong handle is worse than an absent one. (Reference: a lookup-style
resolver was previously observed silently mapping the parameter type
`Path` to an unrelated module-local variable named `path`; that failure
mode must not recur.)

### Known v1 limitations (graceful degradation)

These constructs preserve `raw` but may omit `handle` and/or `args`. The
response stays conformant:

- **`Callable[[A, B], C]`** — uneven bracket structure
  (`[args_list, return_type]`) doesn't fit uniform recursion. The `raw`
  carries the full expression; `args` may be absent. Example response from
  `def register(callback: Callable[[int, str], bool]) -> None`:

  ```jsonc
  "type": { "raw": "Callable[[int, str], bool]", "handle": "typing.Callable" }
  ```

- **`Literal[1, 2, "x"]`, `Annotated[X, metadata]`, `ParamSpec`,
  `TypeVarTuple`, PEP 695 type aliases** — type-system-specific argument
  semantics that don't fit uniform `TypeRef` recursion. Same rule:
  preserve `raw`, omit `args`.
- **Forward-reference strings** — resolve only when the referenced symbol
  exists at inspect time; otherwise `handle` is absent. A forward ref to
  a non-existent symbol degrades to `{ "raw": "DoesNotExist" }`.

### Telemetry

The implementation tracks degraded-path categories via an in-process
counter so future passes can be prioritised empirically rather than by
guess. See `degraded_counts` in `src/pyeye/mcp/operations/typeref.py`.
The `get_performance_metrics` admin tool reports the counts by shape: the
`typeref_degraded` section of its report, and the
`pyeye_typeref_degraded_total` counter in its Prometheus format. Reading
them doesn't reset them (#331).

### Caching

TypeRef builds are cached in a bounded, per-process LRU keyed on the project
root, the annotation's file and its `mtime_ns`, the annotation's position, and
its source text (see `_typeref_cache` in `src/pyeye/mcp/operations/typeref.py`).
An edit to that file changes `mtime_ns`, so the old entry is never hit again and
the next `inspect` rebuilds it. This keeps repeated `inspect` calls on heavily
typed modules cheap.

### Spec cross-reference

Full normative discussion lives in
`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`
section "Type fields as `TypeRef` trees". Acceptance
fixtures are under
`tests/integration/api_redesign/fixtures/typeref_compound/` and the
end-to-end conformance tests are in
`tests/integration/api_redesign/test_conformance.py::TestCriterion14TypeRefConformance`.

---

## Migration note

The clearly-replaced legacy navigation tools have been **removed** from the
MCP surface (issue #376). The progressive-disclosure operations are their
replacements. Use this table to migrate existing agent code:

| Removed tool | Replacement | Why |
|----------|---------------|-----|
| `find_symbol(name)` | `resolve(name)` | Canonical handle + ambiguity surfaced |
| `goto_definition(file, line, col)` | `resolve_at(file, line, col)` | Returns canonical handle directly |
| `get_type_info(file, line, col)` | `inspect(handle)` | Richer Node, no source content |
| `get_module_info(module)` | `inspect(module_handle)` | Same Node contract; `edge_counts.members` |
| `find_imports(module)` | `expand(handle, edge="imported_by")` | Stub-based, canonical handles |
| `find_subclasses(class)` | `expand(handle, edge="subclasses")` (direct) / `trace(follow=["subclasses"], max_depth=k)` (closure) | Direct subclasses only since #422 (one hop); full transitive closure via `trace`. `subclasses` is expand-only, not in `edge_counts` (#392; cheap count gated on #333/#397) |
| `list_packages` / `list_modules` | `outline` | One structural lister |
| `list_project_structure` | `outline` | ″ |
| `lookup(identifier)` | `resolve` → `inspect` | Progressive disclosure |

**Also removed in 2.0** (#505): `find_references`, `get_call_hierarchy` and
`analyze_dependencies` were removed rather than deprecated, because they
returned confidently wrong answers. `get_call_hierarchy`'s forward half is
`expand(handle, edge="callees")`; `analyze_dependencies` maps onto
`expand(imports)` / `expand(imported_by)` / `trace(follow=["imports"])`.
Callers and references have no replacement until the Pyright reference backend
(#333) lands. The CHANGELOG's migration map has the full table.
`configure_packages` and the framework plugin tools are orthogonal to the
navigation redesign and are kept.

The underlying `JediAnalyzer` methods are internal implementation, not API.
Those that back the new operations remain (e.g. `analyzer.find_symbol`,
`analyzer.find_importers`, `analyzer.find_subclasses`). Those that only served
the removed tools (e.g. `find_imports`, `list_modules`, `list_packages`,
`get_type_info`, `goto_definition`) were deleted in #628, because nothing
reachable from an MCP tool called them.

---

## Cross-references

- Spec: `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`
- Layering principle: `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`,
  section "1. Layering — semantic vs. content" (pyeye returns pointers and
  structural facts, never file content)
- Conformance linter: `tests/conformance/response_linter.py`
- Spec acceptance tests: `tests/conformance/test_spec_acceptance.py`
