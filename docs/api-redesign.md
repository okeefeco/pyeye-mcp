# PyEye API Redesign: resolve / inspect

## Overview

This document describes the redesigned PyEye API surface introduced across
Phases 1–4, 6, and 7. The redesign adds three new operations — `resolve`,
`resolve_at`, and `inspect` — optimised for cheap, pointer-first code
navigation.

### Why a redesign?

The original PyEye tools (`find_symbol`, `goto_definition`, `get_type_info`,
etc.) were modelled on LSP-bridge tools: each response shipped full source
context. That makes sense for humans reading an editor, but wastes wire
bandwidth when an AI agent just needs a structural fact.

Measurement from 2026-05-02: `mcp-language-server`'s `definition` call for
`GranularCache` (a 234-line class) returned ~17,500 bytes per copy. The new
`inspect` operation returns the same structural information in ~527 bytes —
roughly 0.03× the wire cost.

### Current status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Handle type + canonicalization | Done |
| 2 | `resolve()` operation | Done |
| 3 | `resolve_at()` operation | Done |
| 4 | `inspect()` with edge counts | Done |
| 5 | `outline()` operation | Deferred |
| 6 | `re_exports` wired into `inspect` | Done |
| 7.1 | Conformance linter + pre-commit hook | Done |
| 7.2–7.5 | Spec acceptance tests (closeout) | Done |
| 8 | TypeRef recursive trees on type-bearing fields | Done |

`expand()` and `trace()` are future operations, not yet planned.

---

## The three operations

### `resolve(identifier, project_path?)`

Converts any identifier form to a canonical handle.

**Supported identifier forms:**

1. Bare name: `Config`
2. Fully-qualified dotted name: `mypackage._impl.config.Config`
3. Re-exported public path: `mypackage.Config` (collapses to definition site)
4. File path with line: `src/pyeye/cache.py:238`
5. File path only: `src/pyeye/cache.py`

**Returns:** `ResolveResult` — one of three variants:

```json
// Success
{
  "found": true,
  "handle": "mypackage._impl.config.Config",
  "kind": "class",
  "scope": "project",
  "location": {
    "file": "src/mypackage/_impl/config.py",
    "line_start": 10,
    "line_end": 22,
    "column_start": 6,
    "column_end": 12
  }
}

// Not found
{
  "found": false,
  "handle": null,
  "reason": "no match for 'UnknownClass'"
}

// Ambiguous (bare name matches multiple definitions)
{
  "found": "ambiguous",
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
resolve_at("src/pyeye/cache.py", 238, 6) →
{
  "found": true,
  "handle": "pyeye.cache.GranularCache",
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
inspect("pyeye.cache.GranularCache") →
{
  "handle": "pyeye.cache.GranularCache",
  "kind": "class",
  "scope": "project",
  "location": {
    "file": "src/pyeye/cache.py",
    "line_start": 238,
    "line_end": 412,
    "column_start": 6,
    "column_end": 18
  },
  "docstring": "Granular per-file cache that invalidates only changed files.",
  "signature": "class GranularCache(ProjectCache)",
  "superclasses": ["pyeye.cache.ProjectCache"],
  "edge_counts": {
    "members": 12,
    "superclasses": 1,
    "subclasses": 0,
    "callers": 3,
    "references": 47
  },
  "re_exports": []
}
```

---

## The Node response shape

Every `inspect` response is a Node dict. Fields come in two layers:

### Universal fields (always present)

| Field | Type | Description |
|-------|------|-------------|
| `handle` | `str` | Canonical dotted-name handle |
| `kind` | `str` | One of: `class`, `function`, `method`, `module`, `variable`, `attribute`, `property` |
| `scope` | `str` | `"project"` or `"external"` |
| `location` | `dict` | Pointer to the definition (see below) |
| `docstring` | `str \| null` | First paragraph of docstring |
| `edge_counts` | `dict` | Measured edge counts (see below) |

### Kind-dependent fields

| Field | Kinds | Description |
|-------|-------|-------------|
| `signature` | function, method, class | Single-line call/class signature |
| `superclasses` | class | List of canonical handles for base classes |
| `parameters` | function, method | Typed parameter list — each entry's `type` is a recursive `TypeRef` tree (see below), not a string |
| `return_type` | function, method | Recursive `TypeRef` tree for the return annotation (see below), not a string |
| `attributes` | class | Public attributes with types — each `type` is a recursive `TypeRef` tree (see below) |
| `re_exports` | non-module | Re-export aliases (see below) |

### Location shape

```json
{
  "file": "src/pyeye/cache.py",
  "line_start": 238,
  "line_end": 412,
  "column_start": 6,
  "column_end": 18
}
```

- `line_start`/`line_end` — span the full definition body
- `column_start`/`column_end` — span the name token only
- **No source content** — location is a pointer. Use the `Read` tool
  if you need the actual text.

---

## Edge counts and the absence-vs-zero invariant

`edge_counts` is **always present** on every `inspect` response. It is never
null and never absent.

### Measured edges per kind

| Kind | Measured edges |
|------|---------------|
| `class` | `members`, `superclasses`, `subclasses`, `callers`, `references` |
| `function`, `method` | `callers`, `references` |
| `module` | `members`, `references` |
| `variable`, `attribute`, `property` | `references` |

### The invariant

> A measured edge is **present** (even with value `0`).
> An unmeasured edge is **absent** (not `0`).

This is the **absence-vs-zero invariant**. It lets agents distinguish "we
measured zero" from "we don't yet measure this edge type."

Examples:

```json
// class — all 5 edges measured
"edge_counts": {"members": 12, "superclasses": 1, "subclasses": 0, "callers": 3, "references": 47}

// function — only callers + references
"edge_counts": {"callers": 5, "references": 23}

// variable — only references
"edge_counts": {"references": 8}
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
  "edge_counts": {"members": 47, "superclasses": 1, "subclasses": 1, ...}
}
```

For external handles:

- `scope` is `"external"`
- `edge_counts.subclasses` counts **project-internal** subclasses only —
  not stdlib subclasses of the same base. This is intentional: it tells you
  how many places in your project extend an external class.
- All other universal fields are populated from Jedi's analysis.

---

## Re-exports

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
`return_type`, and the `type` field on `attributes`, properties, and
variables — is a recursive `TypeRef` tree, not a flat string. This
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
  "edge_counts": { "callers": 0, "references": 0 },
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
response stays conformant; future passes will tighten coverage:

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
guess. See `degraded_counts` and `get_and_reset_degraded_counts()` in
`src/pyeye/mcp/operations/typeref.py`.

### Caching

TypeRef builds are cached per `(file_path, mtime_ns, raw)` in a
per-process dict. When a file is edited, its `mtime_ns` changes and the
old key is unreachable, so the next `inspect` call rebuilds. This keeps
repeated `inspect` calls on heavily-typed modules cheap.

### Spec cross-reference

Full normative discussion lives in
`docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`
under "Type fields as `TypeRef` trees" (lines ~395–475). Acceptance
fixtures are under
`tests/integration/api_redesign/fixtures/typeref_compound/` and the
end-to-end conformance tests are in
`tests/integration/api_redesign/test_conformance.py::TestCriterion14TypeRefConformance`.

---

## Migration note

The new operations (`resolve`, `resolve_at`, `inspect`) are **additive**.
The existing tools (`find_symbol`, `goto_definition`, `get_type_info`, etc.)
continue to work. They have been marked deprecated in source but are not
removed; removal is planned once the migration completes.

**Prefer the new operations** for new agent code:

| Old tool | New operation | Why |
|----------|---------------|-----|
| `find_symbol(name)` | `resolve(name)` | Canonical handle + ambiguity surfaced |
| `goto_definition(file, line, col)` | `resolve_at(file, line, col)` | Returns canonical handle directly |
| `get_type_info(file, line, col)` | `inspect(handle)` | Richer Node, no source content |

---

## Cross-references

- Spec: `docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md`
- Layering principle: `~/.claude/projects/okeefeco/pyeye-mcp.md`
  (memory entry: "Pyeye is semantic, never content")
- Conformance linter: `tests/conformance/response_linter.py`
- Spec acceptance tests: `tests/conformance/test_spec_acceptance.py`
