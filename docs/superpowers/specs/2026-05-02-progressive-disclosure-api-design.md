# Pyeye Public API Redesign: Progressive Disclosure with Canonical Handles

**Issues:** #316, #320, #321
**Date:** 2026-05-02
**Status:** Design
**Supersedes (in part):** [`2026-03-27-unified-lookup-tool-design.md`](./2026-03-27-unified-lookup-tool-design.md) — keeps the unified-intake direction; replaces the "return everything" response shape with progressive disclosure.

## Goal

Redesign Pyeye's public MCP surface around **canonical Python handles**, **progressive disclosure**, and **a typed property graph** — a small set of operations (`resolve`, `inspect`, `outline`, `expand`, `trace`) that return cheap structural answers by default and let the agent drill on demand. Keep the entire interface semantic-only: pyeye returns pointers and structured facts, never file content.

## Scope and Non-Goals

**In scope:**

- A new public operation set replacing the current ~14 Jedi-shaped tools.
- The data shape returned by every operation (the typed property graph).
- The closed-ish vocabulary of edge types.
- Plugin extension semantics — how plugins add edges, kinds, and resolution paths without bloating the core.
- Migration strategy from the current API.

**Not in scope:**

- Internal analyzer changes beyond what's needed to support the new operations. (Cache infrastructure landed under the lookup-performance-cache plan; this spec assumes that work.)
- Type-quality improvements (Jedi vs. Pyright). The new shape composes with whichever backend pyeye uses.
- Cross-language support. Python only.
- Diagnostics/type-error surfacing. Out of scope; complementary tools (e.g., the Pyright LSP plugin) compose at the agent layer.

## Foundational Principles

These principles are non-negotiable in the design. Every operation, return field, and plugin extension must respect them.

### 1. Layering — semantic vs. content

Pyeye is the semantic layer. Read is the content layer. Pyeye returns pointers (`file`, `line_start`, `line_end`) plus structured semantic facts (signatures, types, edges). Pyeye **never** ships file content (snippets, bodies, surrounding context).

Boundary test: *structurally bound to the symbol → semantic → returned. Free-form text → content → not returned.*

Operation test for any new tool: *"would Pylance ship this, or would the editor ship this?"* If editor — not our job.

(See `feedback_pyeye_layering.md` in project memory.)

### 2. Cheap-by-default, drill on demand

Every default response is small and structural. Edge counts, not contents. Highlights (top-N), not exhaustive lists. Bodies and full enumerations require explicit follow-up calls. The wire economics scale with how much the agent actually engages with, not with how much the codebase contains.

### 3. Canonical handles, plain Python notation

Handles are Python's own dotted notation: `a.b.c.d`. Kind is a return field, not encoded in the handle. Identifiers are stable across edits, deduplicating across import aliases. Two intake paths (`resolve(name)` and `resolve_at(file, line, col)`) both produce a handle; everything downstream operates on handles.

### 4. Project-aware scoping

Pyeye respects project boundaries: `build/`, `dist/`, `.tox/`, vendored code are out-of-scope by default. Pointers returned are pointers into *the project*, not into arbitrary `.py` files in the workspace. (LSP-bridge MCPs were observed indexing `build/lib/` repeatedly; pyeye must not.)

### 5. Plugin attribution visible

Every plugin-added edge type and plugin-defined kind names its plugin via an `@plugin` suffix. Conflict-free vocabulary; clear attribution; skills can dispatch on type.

### 6. Python structure, not domain meaning

(Carried forward from the unified-lookup design.) Pyeye reports Python's object model: bases, subclasses, references, imports, callers, callees, members, signature, docstring. It does not interpret domain meaning ("consumers", "patterns", "blast radius"). Plugins extend the vocabulary with project-specific Python facts; they do not introduce subjective domain interpretation.

## Identity Model

### Handles

A handle is a Python dotted-name string identifying exactly one symbol within a project's scope:

```typescript
ModuleHandle    = "a.b.c"           # module a.b.c
ClassHandle     = "a.b.c.MyClass"   # class MyClass in module a.b.c
FunctionHandle  = "a.b.c.do_thing"  # function in module a.b.c
MethodHandle    = "a.b.c.MyClass.method"
AttributeHandle = "a.b.c.MyClass.field"
```

Properties:

- **Stable across edits** — qualname-derived, not coordinate-derived.
- **Deduplicating across import aliases** — `import x as y; y.foo()` and `from x import foo; foo()` resolve to the same handle.
- **Unambiguous within project** — Python's resolution rules guarantee uniqueness in a properly-scoped project. (Build artifacts and namespace package distribution are explicitly handled by project-aware scoping and the namespace resolver.)

### Canonicality: re-exports and aliases

Python permits a single object to be reachable by multiple dotted paths. Most commonly via re-exports in `__init__.py`:

```python
# package/_impl/config.py
class Config: ...

# package/__init__.py
from package._impl.config import Config
```

Both `package.Config` and `package._impl.config.Config` are valid identifiers binding to the same class. Without an explicit rule, plugins and skills will quietly disagree about which form is the "real" handle.

**Rule: the canonical handle is the definition site.**

For the example above, the canonical handle is `package._impl.config.Config`. Both `resolve("package.Config")` and `resolve("package._impl.config.Config")` collapse to that handle. References from either form are deduplicated. This matches how Pyright and Jedi already think (trace imports to definitions) and gives refactoring closures a single, stable target.

**Re-exports are surfaced as a node field, not as a separate handle.**

When `inspect` returns a node, its `re_exports` field lists the public dotted paths that bind to this symbol. The agent gets the canonical handle for navigation *and* knows which public names exist for human-facing references:

```typescript
{
  handle: "package._impl.config.Config",
  kind: "class",
  re_exports: ["package.Config"],  // public names binding to the canonical handle
  ...
}
```

`re_exports` is empty when the symbol is only accessible at its definition path. A symbol re-exported from multiple places lists all bindings.

Refinement (deferred to implementation): distinguishing `__all__`-listed exports from incidental re-exports. The spec mandates the field shape; richer per-entry metadata (e.g., `in_all: boolean`) is permitted as an extension, not required.

### Kinds

Kind is always present on a node. Two categories:

**Core (Python-fundamental):**

```typescript
"class" | "function" | "method" | "module" | "attribute" | "property" | "variable"
```

**Plugin (non-Python entities):**

```typescript
"yaml_reference@yaml" | "modelref@aac" | ...
```

Pattern: `<name>@<plugin>` for non-Python entities returned by plugins. Core kinds have no suffix.

For Python entities that have framework significance (e.g., a Pydantic model class), `kind` is still core (`class`); the plugin annotation is in `tags`.

### Cross-package boundaries: project vs. external

A handle-shaped string isn't a promise that pyeye can do everything for it. Symbols outside the project's source — third-party packages from `site-packages`, the standard library, vendored installations — are reachable as handles, but operations on them are **project-scoped**, not full-graph.

Every node and stub carries a binary `scope` field:

- `"project"` — symbol is defined in the project (within a configured package path). All operations return rich, full-graph data. Counts and edge expansions are exhaustive within the project's analysis.
- `"external"` — symbol is defined outside the project (third-party package, stdlib, vendored). Operations still work, but with project-scoped semantics:
  - `inspect` returns what's derivable from the external source: kind, signature, docstring, direct members, location in site-packages.
  - `expand(handle, edge=callers|references|read_by|written_by|passed_by|subclasses|overridden_by|imported_by)` returns **project-internal matches only** — not who in other packages calls or extends the external symbol. Pyeye doesn't index every package's call graph against every other package's symbols.
  - `expand(handle, edge=members|superclasses|callees|...)` walks the external symbol's own structure (its class members, its own superclasses, what it itself calls) — pyeye can derive these from the external source on demand.
  - `edge_counts` on an external node are project-scoped. A `subclasses: 3` count on `pydantic.BaseModel` means three classes in *this project* extend it.
  - `outline` works on an external module or class (enumerates its members), bounded to one level of immediate structure.

**Indexing depth for external symbols.** Pyeye does not eagerly index installed packages. It lazily resolves external symbols when the agent inspects them — Jedi/Pyright follow into site-packages on demand. Direct members of an externally-referenced class are derivable from the class itself; deeper transitive symbols are resolved only if the agent specifically navigates to them. Cost is bounded by agent curiosity, not by eager dep-tree indexing.

**Why `external` and not `stdlib | third_party | vendored`?** A binary distinction is what governs operation behavior: project = full-graph, external = project-scoped. The location field already shows where the symbol lives (a path in site-packages, a stdlib path, etc.), which is enough information for the agent. Finer distinctions are not load-bearing for the API.

**Asymmetry to expect.** The same code relationship can look different depending on which end the agent starts from. From a project class, `superclasses` may return external handles (e.g., `pydantic.BaseModel`) — reaching out is fine. From an external class, `subclasses` returns project-scoped only — pyeye doesn't enumerate every package's subclasses against every external symbol. Same edge type, different completeness. Agents and skill authors should expect this directional asymmetry: full-graph going *out* from project nodes, project-scoped coming *back* from external nodes.

### Locations

Every node has a location:

```typescript
type Location = {
  file: string         // posix path, project-relative or absolute
  line_start: number   // 1-indexed
  line_end: number     // 1-indexed, inclusive
  column_start?: number // 0-indexed, when relevant
  column_end?: number
}
```

Locations are *pointers*, not content. The agent uses Read with these to fetch source when needed.

## Operations

Five operations comprise the entire public surface.

### `resolve(name) → Handle | [Handle]`

Convert a name to a handle.

```typescript
resolve(identifier: str) → ResolveResult

type ResolveResult =
  | { found: true, handle: Handle, kind: Kind, scope: "project" | "external", location: Location }
  | { found: true, ambiguous: true, candidates: { handle: Handle, kind: Kind, scope: "project" | "external", location: Location }[] }
  | { found: false, reason: string }
```

`identifier` accepts any form: bare name (`Config`), dotted path (`a.b.c.Config`), re-exported public path (`package.Config` where the definition is at `package._impl.config.Config`), file-with-line (`src/foo.py:42`). The resolver normalizes all forms to the **definition-site canonical handle** (see "Canonicality: re-exports and aliases" above). Re-exports collapse to the same handle as the definition path.

When ambiguous (bare name matching multiple symbols), returns candidates with enough context for the agent to pick. Plugin-registered identifier forms (e.g., `users.yaml#user_model`) are tried in registration order before falling through to Python resolution.

`scope` is included on every success result (and on every candidate) so the agent can decide whether to drill in (project — full-graph data) or treat the symbol as a leaf (external — project-scoped operations only) without a follow-up `inspect` call. Computing scope at resolution is cheap.

`location` is also included on every success result and every candidate. The data is already at hand when resolution succeeds — Jedi exposes `module_path`, `line`, and `column` on the resolved `Name` — and "where is this symbol defined?" is the single most common follow-up to "what is its handle?". Surfacing location on the success variant eliminates a near-mandatory second `inspect` call for the most common case.

### `resolve_at(file, line, column) → Handle`

Convert a position to a handle.

```typescript
resolve_at(file: string, line: int, column: int) → ResolveResult
```

Used when the agent has coordinates (from a stack trace, error report, or pasted excerpt) rather than a name. Same return shape as `resolve`.

### `inspect(handle) → Node`

The canonical "what is this?" operation. Returns a small, structured node.

```typescript
inspect(handle: Handle) → Node
```

(See "Return Shape" below for the Node schema.)

Cheap by default: returns kind, location, signature/type/docstring, edge counts, and top-N highlight handles per edge. **No bodies, no full member lists, no exhaustive enumerations, no metrics.**

### `outline(handle) → Tree`

Recursive walk of the `members` edge, scope-bounded, returns a tree.

```typescript
outline(handle: Handle, max_depth?: int) → OutlineTree

type OutlineTree = {
  node: Stub
  children: OutlineTree[]
}

type Stub = {
  handle: Handle
  kind: Kind
  scope: "project" | "external"
  signature?: string  // for callable kinds, one-line
  line_start: number
  line_end: number
}

// Context-narrowed extension: stubs returned from `expand(handle, edge="references")`
// (the aggregate edge) carry an additional subkind field so the agent can distinguish
// reads from writes from passes without further calls.
type ReferenceStub = Stub & {
  subkind: "read" | "write" | "passed"
}
```

Default `max_depth`: unbounded within the scope. Nested classes are walked; classes' member functions are walked; their bodies are not.

Returns the structural skeleton of a module or class. No bodies. No metrics.

**External-scope cap.** `outline(external_handle, max_depth=N)` treats `max_depth` as `min(N, 1)` — the immediate members of the external class or module are returned, but deeper nesting inside third-party code is not walked even if requested. This is consistent with the lazy-resolution principle for external symbols: agents wanting to walk deeper into installed packages call `inspect` per-member, which lazily resolves through Jedi/Pyright on demand. Predictable behavior; no eager dep-tree indexing.

### `expand(handle, edge, ...) → ExpandResult`

Single-hop walk along one edge type. Paginated.

```typescript
expand(
  handle: Handle,
  edge: EdgeType,
  limit?: int,            // default 20
  cursor?: string,        // opaque pagination token
  filter?: ExpandFilter,  // optional pre-filtering
) → ExpandResult

type ExpandResult = {
  stubs: Stub[]
  cursor?: string  // present if more results available; absent means full result set delivered
}

type ExpandFilter = {
  include_tests?: boolean   // default true
  module_pattern?: string   // glob over module path
  same_package?: boolean    // restrict to same top-level package
}
```

Returns stubs (handle + kind + signature + lines), not full nodes. The agent calls `inspect` on stubs it wants to drill into.

**Aggregate edges and ReferenceStub.** When `edge` is an aggregate type (currently only `references`), the returned `stubs` array is `ReferenceStub[]` rather than plain `Stub[]` — each stub carries the `subkind` field (`"read" | "write" | "passed"`). For all other edges (specific edges like `read_by`, `written_by`, `passed_by`, and non-aggregate edges generally), the array is `Stub[]` and `subkind` is omitted because the classification is implicit in the edge type.

**Default ordering for aggregate `references`.** Results are interleaved by location — sorted by `(file, line_start)` ascending — with `subkind` as the deterministic tiebreaker (alphabetical: `passed < read < write`). Interleaved-by-location is the right default because pagination cursors then advance through a flat list without page-boundary-mid-group artifacts, and it matches how an agent naturally scans a file. Specific-edge expansions (`read_by` etc.) are also ordered by `(file, line_start)` for consistency.

**On counts**: `expand` deliberately does not return a total count. Counts live on `inspect(handle).edge_counts` — which the agent has already retrieved as part of orientation before deciding whether to expand. Pagination state is read from `cursor` presence (absent = full result set delivered; present = more available). If a filtered count is genuinely needed, the agent paginates to it; if that becomes a frequent enough need, a separate `count(handle, edge, filter?)` operation is the right home for it later, not a conditional field on `expand`.

### `trace(start, follow, ...) → Subgraph`

Bounded multi-hop BFS along one or more edge types. Returns a subgraph.

```typescript
trace(
  start: Handle | Handle[],
  follow: EdgeType[],
  max_depth?: int,        // default 3
  max_nodes?: int,        // default 50
  stop_when?: StopPredicate,
) → Subgraph

type Subgraph = {
  nodes: Map<Handle, Stub>
  edges: { from: Handle, to: Handle, kind: EdgeType }[]
  truncated: boolean   // true if max_depth or max_nodes was hit before natural termination
}

type StopPredicate = {
  module_pattern?: string  // stop when entering matching module
  exclude_tests?: boolean
  // ... extensible
}
```

Used for refactor closures, call chains, bug-tracing — anywhere the agent needs to see *structure* across multiple hops.

**Termination semantics.** Trace deduplicates by handle. Each handle is visited at most once; edges *to* already-visited handles are recorded in the subgraph (so cycles are visible to the agent) but do not trigger re-expansion. This guarantees termination on cyclic graphs — including the common cases of mutual recursion, circular references between sibling modules, and self-referential classes — even when `max_depth` is unbounded. The trace is naturally bounded by the count of reachable handles under the given `follow` set and `stop_when` filter.

**`truncated` semantics.** `truncated: true` means `max_depth` or `max_nodes` was hit *before* natural termination — there are reachable handles the trace did not visit. `truncated: false` means the full reachable closure was returned. The agent can re-trace with higher caps if `truncated: true` and the truncation matters for the question being asked.

**Edge deduplication.** Nodes are deduped by handle (each handle appears once in `Subgraph.nodes`). Edges are *not* deduped across types — if A → B exists via both `callers` and `references`, both appear in `Subgraph.edges` with their respective `kind` values. Cycles and multi-edge-type relationships are both faithfully represented.

**Aggregate edges in `follow`.** When `follow` includes an aggregate edge (currently only `references`), trace expands it to the underlying specific edges (`read_by`, `written_by`, `passed_by`) at traversal time. Returned `Subgraph.edges` always carry specific (non-aggregate) `kind` values — never `references`. This means trace's edge metadata always tells the agent the precise relationship, and `Subgraph` nodes never need a subkind field (the kind is on the edge, not the node).

## Return Shape: The Typed Property Graph

Pyeye returns nodes from a typed property graph. The schema:

### Universal node fields

Every node, regardless of kind, has:

```typescript
type Node = {
  handle: Handle                          // definition-site canonical
  kind: Kind
  scope: "project" | "external"           // see "Cross-package boundaries" below
  location: Location
  docstring?: string                      // when present (semantic, not content)
  re_exports?: string[]                   // public dotted paths binding to this symbol; empty list if measured-and-none
  edge_counts: Record<EdgeType, number>   // counts per MEASURED edge type; project-scoped on external nodes. See "Absence vs zero" below.
  highlights?: Record<EdgeType, Handle[]> // top-N adjacent handles per measured edge
  tags?: string[]                         // plugin classifications (only on Python kinds)
  properties?: Record<string, unknown>    // plugin properties (only on plugin kinds)
}
```

### Absence vs. zero: a load-bearing invariant

Implementations communicate certainty by **what's present**, not by zero values. The rule applies to every optional or extensible field on a Node:

- **Field absent** = "we didn't measure this." The agent does not know whether the value would be empty, zero, or large — only that this implementation didn't compute it.
- **Field present (even if empty/zero)** = "we measured this and the result is what's shown."

Most concretely, this governs `edge_counts`:

| Response | Meaning |
|---|---|
| `edge_counts: { members: 5, callers: 23 }` | We measured `members` (5) and `callers` (23). We did *not* measure any other edge types. |
| `edge_counts: { members: 5, callers: 0, subclasses: 0 }` | We measured `members`, `callers`, *and* `subclasses`. The latter two have zero matches. |
| `edge_counts: {}` | We measured no edges on this node — `edge_counts` is mandatory but is empty when nothing was measured. |

The agent can rely on this distinction. If an edge type the agent expected is absent from `edge_counts`, the implementation is signaling that it doesn't yet measure that edge — not that the count happens to be zero. The agent can either accept the unknown or call a different operation that does measure (or wait for a later implementation that does).

The same rule applies to:

- `re_exports` — present (possibly `[]`) means "we walked re-exports for this symbol and found these." Absent means "we don't compute re-exports for this kind/implementation."
- `highlights` — present (possibly `{}`) means "we considered which neighbors to highlight." Absent means "this implementation doesn't compute highlights for this kind."
- `tags` — present (possibly `[]`) means "we evaluated plugin classifications." Absent means "no classification step ran."
- `properties` — present means "this is a plugin kind with plugin-defined data." Absent means "no plugin properties apply."

**This invariant is part of the spec contract**, not an implementation detail. An implementation that returns zero for unmeasured edges is non-conforming. The conformance test suite verifies both directions: keys present must reflect actual measurement; absences must not be silently filled with zero.

**Why this matters.** "Zero results" is a load-bearing signal — a class with `subclasses: 0` is genuinely unextended; a function with `callers: 0` is genuinely unused (within scope). Conflating that with "we didn't bother to check" destroys the agent's ability to distinguish certainty from ignorance, and quiet differences between implementations would silently corrupt downstream reasoning.

### Kind-dependent properties (on Python kinds)

| Kind | Additional fields |
|---|---|
| `class` | `signature?` (constructor), `superclasses: Handle[]` |
| `function` / `method` | `signature: string`, `parameters: Param[]`, `return_type?: string`, `is_async: boolean`, `is_classmethod: boolean`, `is_staticmethod: boolean` |
| `module` | `package: Handle?`, `is_package: boolean` |
| `attribute` / `property` / `variable` | `type?: string`, `default?: string` (for simple literals only) |

```typescript
type Param = {
  name: string
  type?: string
  default?: string         // simple literals only; complex defaults represented by source range pointer
  kind: "positional" | "positional_or_keyword" | "keyword_only" | "var_positional" | "var_keyword"
}
```

**Notably absent (by design):**

- No `body`, `source`, or `snippet` fields anywhere
- No metrics (LOC, complexity, halstead, etc.)
- No `references` or `callers` lists by default — only `edge_counts.references`, `edge_counts.callers`, etc. Use `expand` for the actual lists.

### Plugin extensions on Python kinds: `tags`

Plugins classify Python entities via tags. A Pydantic model class returns:

```typescript
{
  handle: "a.b.c.UserModel",
  kind: "class",                   // core Python truth
  scope: "project",                // defined in this project
  tags: ["model@pydantic"],        // plugin classification
  superclasses: ["pydantic.BaseModel"],  // handle-shaped; resolves to a node with scope: "external"
  signature: "UserModel(*, id: int, name: str)",
  edge_counts: {
    members: 4,
    references: 23,
    subclasses: 1,
    "validators@pydantic": 2,      // plugin-added edge appears in counts
    "field_validators@pydantic": 1,
    "computed_fields@pydantic": 0
  },
  ...
}
```

### Plugin kinds: `properties` bag

Non-Python entities returned by plugins use plugin-namespaced kinds and a `properties` bag for plugin-specific data:

```typescript
{
  handle: "users.yaml#user_model",
  kind: "yaml_reference@yaml",
  scope: "project",
  location: { file: "config/users.yaml", line_start: 14, line_end: 23 },
  properties: {
    yaml_path: "models.user_model",
    aac_class: "UserModel",
    // ... plugin-defined; pyeye doesn't interpret
  },
  edge_counts: {
    "modelref@aac": 1   // points to underlying Python class
  }
}
```

Pyeye transports the `properties` bag verbatim. Skills (shipped with the plugin) interpret it.

## Edge Type Vocabulary

### Core edges (closed-ish)

| Edge | From → To | Meaning |
|---|---|---|
| `members` | parent → child | what's defined inside (class → methods; module → classes/functions) |
| `enclosing_scope` | child → parent | inverse of `members` |
| `callers` | callee → caller | who calls this function/method |
| `callees` | caller → callee | what this function/method calls |
| `read_by` | symbol → read sites | sites where this symbol's value is read (non-call) |
| `written_by` | symbol → write sites | sites where this symbol is assigned to (mutations) |
| `passed_by` | symbol → passing sites | sites where this symbol is passed as a value (callback arg, type reference, etc.) |
| `references` | symbol → use sites | virtual aggregate of `read_by ∪ written_by ∪ passed_by`; **excludes call sites** (use `callers` for invocations); stubs carry `subkind` annotation |
| `superclasses` | subclass → parent | inheritance up |
| `subclasses` | parent → child | inheritance down |
| `overrides` | override → original | this method overrides |
| `overridden_by` | original → overrides | this method is overridden by |
| `decorated_by` | target → decorator | the decorators applied to this function/class |
| `decorates` | decorator → targets | everything this decorator is applied to |
| `imports` | importer → imported | what this module imports |
| `imported_by` | imported → importer | who imports this module |

This is the closed-ish core set. Additions to the core require deliberate review — they expand the universal vocabulary every agent depends on.

### Naming convention

Edges that point *to* sites where the symbol is acted upon use the `_by` suffix: `decorated_by`, `read_by`, `written_by`, `passed_by`, `imported_by`, `overridden_by`. Read as "this symbol is X by [these sites]." The convention is consistent; plugin authors should follow it.

`passed_by` reads slightly awkwardly compared to "passed_to" but stays in the convention; pyeye returns the call/use sites where the symbol appears as a passed value, not the receiving parameter positions, so `_by` is correct.

### Class vs. method edge semantics

Classes and methods are both callable in Python (`MyClass(...)` instantiates), so `callers`/`callees` need explicit semantics for each:

- **`callers` of a class** = sites that instantiate it (`MyClass(...)`). Treat instantiation as calling the class.
- **`callees` of a class** = empty. Classes don't call things; their methods do. The agent uses `members` to enumerate methods, then `callees` on each. This avoids ambiguous "aggregate of all method callees" semantics that would pollute the result with everything every method calls.
- **`callers` of `__init__`** = sites that explicitly invoke `__init__` directly (typically `super().__init__()` from subclass constructors). Implicit constructor calls from instantiation are attributed to the *class*, not to `__init__`.
- **`callees` of `__init__`** = what the constructor body calls.
- **Methods otherwise** behave as expected: `callers` returns sites that invoke the method, `callees` returns what the method's body calls.

This split keeps "who instantiates this class" and "who calls `__init__` directly" as separable queries — both are useful and they're meaningfully different.

### Reference semantics

References to a symbol come in three shapes — reads, writes, and pass-by-value uses. Lumping them together is a refactor footgun: rename safety wants all three, but "what mutates this attribute" wants writes only and "what reads this state" wants reads only. The vocabulary distinguishes them as separate core edges:

- `read_by` — sites where the symbol's value is read (variable read, attribute read, condition test)
- `written_by` — sites where the symbol is assigned to (`x = ...`, `obj.field = ...`)
- `passed_by` — sites where the symbol is passed as a value rather than invoked (callback args, type references in annotations, function objects bound to other names)

`references` is a virtual aggregate over these three. It's not stored separately — pyeye computes the union at query time. Stubs returned from `references` queries carry a `subkind` field (`"read" | "write" | "passed"`) so the agent can distinguish without making three separate calls. Stubs returned from a specific edge (e.g., `written_by`) omit `subkind` because the classification is implicit.

**Boundary with `callers`/`callees`:** call sites are covered by `callers` and `callees`, not by `read_by`. `foo()` is a `callers` relationship for `foo`, even though calling semantically involves reading the name. The aggregate inherits the exclusion: `references` also excludes call sites — `callers` is the exclusive home for invocation relationships. This split keeps "find calls to foo" and "find non-call references to foo" as cleanly separable queries, and ensures call sites are never double-counted across both aggregates.

### Decoration semantics

Decorators are first-class structural facts in Python and a major path through which framework conventions express themselves. Both directions of the decoration relationship are core edges:

- `decorated_by` — from a function/class to the decorator handles applied to it. Used for "what decorates this?"
- `decorates` — from a decorator handle to everything it is applied to in the project. Used for "find all things decorated with X."

The inverse direction (`decorates`) is the structurally interesting one — it makes queries like "find every `@cached_property` in the project" a single `expand("functools.cached_property", edge="decorates")` call instead of an enumerate-then-filter exercise.

**Decoration handles point to the decorator callable**, not the decoration site. For:

- `@cached_property` — handle: `functools.cached_property`
- `@app.route("/path")` — handle: `flask.Flask.route`
- `@deprecated("v2")` — handle: the `deprecated` callable

Decorator *arguments* (e.g., the `"/path"` string in `@app.route("/path")`) are not modeled in the core edge. They're plugin territory: a Flask plugin's `routes@flask` derived view extracts the path argument and exposes it via `properties` on the view's results. The core edge captures the structural relationship; plugins capture the framework-specific argument semantics.

**Kind-changing decorators** (`@property`, `@staticmethod`, `@classmethod`) change the symbol's `kind` or the `is_classmethod`/`is_staticmethod` flag. These facts are visible directly on the node. The `decorated_by` edge can still surface them for completeness — `expand("builtins.property", edge="decorates")` returns every `@property` in the project, which is a useful query — but the kind/flags are the primary representation.

### Plugin edges

Plugin edges use the `<name>@<plugin>` syntax. Examples:

- `validators@pydantic`, `field_validators@pydantic`, `computed_fields@pydantic`, `model_config@pydantic`
- `routes@flask`, `blueprints@flask`, `error_handlers@flask`
- `models@django`, `admin_registrations@django`
- `modelref@aac`, `yaml_definition@yaml`

Plugin edges appear in `edge_counts` on relevant nodes. The agent calls `expand(handle, edge="validators@pydantic")` to walk them.

### Edge directionality

Each edge type has a defined direction. `expand` walks in that direction. Inverse edges are separate types (`callers` vs. `callees`) so the agent's intent is explicit.

## Plugin Extension Model

### Plugins as semantic lifters

A plugin's role: translate project-specific or framework-specific conventions into Python facts. Plugins do not add operations; they extend the vocabulary the operations work with.

A plugin can do four things:

1. **Add identifier forms to `resolve`** — e.g., the YAML plugin recognizes `users.yaml#user_model` as a resolvable identifier and produces a handle (Python or `yaml_reference@yaml`).
2. **Add edge types** — e.g., the Pydantic plugin defines `validators@pydantic` as an edge from a Pydantic model class to its validator methods. The plugin provides the traversal logic.
3. **Add tags or kinds** — Python entities with framework significance get tags (`model@pydantic` on a class). Non-Python entities get plugin-namespaced kinds with `properties` bags.
4. **Register derived views over core edges** — most framework conventions are decoration patterns or naming patterns over Python that already have a core representation. Rather than reimplement traversal, plugins register filter+enrich rules over core edges:

   - Flask's `routes@flask` is a derived view over `decorates` from `flask.Flask.route` — the plugin filters decoration targets, extracts the path argument from the call site, and exposes it as `properties.route_path`.
   - Pydantic's `validators@pydantic` is a derived view over `decorates` from `pydantic.validator` and `pydantic.field_validator` — same pattern, different decorator handles, different argument extraction.
   - Click's `commands@click` is a derived view over `decorates` from `click.command`.

   Derived views compose cleanly with core caching (the underlying edge is computed and cached once; the view filters at query time). Plugin authors should reach for derived views before adding fully custom traversal logic.

### Plugin coupling with skills

Plugins ship with skills. Skills are the interpretation layer that knows what to do with plugin-typed responses. The unit of distribution is **plugin + skill together**:

- Plugin teaches pyeye how to navigate the convention.
- Skill teaches the agent what to do with the navigation results.

Pyeye is the typed transport; skills are the per-domain interpreter. Pyeye doesn't need to understand AAC, YAML, or Pydantic semantically — it transports typed envelopes; skills decode.

### Non-Python pointer returns

Plugins are permitted to return pointers to non-Python files (YAML configs, templates, etc.) when the relationship genuinely points outside Python. The kind is plugin-namespaced; the location points at the file. The agent uses Read with the location for content, same as for Python.

## Canonical Agent Workflows

Examples grounding the operations in real agent tasks.

### "What is `pyeye.cache.GranularCache`?"

```python
node = inspect("pyeye.cache.GranularCache")
# → kind=class, signature, docstring, edge_counts: { members: 9, callers: 0, references: 23, subclasses: 0, superclasses: 1, ... }, highlights: ...
```

One call. Agent has the structural answer.

### "What's inside `pyeye.cache`?"

```python
tree = outline("pyeye.cache")
# → tree of (ProjectCache, GranularCache, DependencyTracker, CacheMetrics, ...) with their methods
```

One call. Recursive structure.

### "Who calls `GranularCache.invalidate_file`?"

```python
result = expand("pyeye.cache.GranularCache.invalidate_file", edge="callers")
# → list of stubs for caller methods/functions
```

One call. Caller list, paginated, no source bodies.

### "What's the call closure 3 levels deep from `lookup`?"

```python
graph = trace(
  start="pyeye.mcp.lookup.lookup",
  follow=["callees"],
  max_depth=3,
  stop_when={ exclude_tests: true }
)
# → subgraph with nodes + edges; fan-in visible
```

One call. Multi-hop. Structure preserved.

### "What's the impact set of renaming `GranularCache.invalidate_file` to `evict_file`?"

```python
graph = trace(
  start=handle,
  follow=["references", "callers", "overrides", "overridden_by"],
  max_depth=Infinity,
  max_nodes=200
)
# → full closure subgraph; reference stubs carry subkind so writes vs. reads are visible
# Termination is guaranteed by handle dedup even with unbounded depth — see Termination semantics.
```

One call. Refactor safety enumeration. The `references` aggregate captures non-call uses (subkind-annotated for risk assessment); `callers` covers invocation sites; `overrides`/`overridden_by` covers methods that share the slot. If `truncated: true` comes back, `max_nodes` was the limit — re-trace with a higher cap if the missing nodes matter.

### "Find the validators on `UserModel`"

```python
result = expand("a.b.c.UserModel", edge="validators@pydantic")
# → list of validator method stubs
```

One call. Plugin-aware traversal; Python destinations.

### "What mutates `Settings.cache_ttl`?"

```python
result = expand("a.b.config.Settings.cache_ttl", edge="written_by")
# → list of stubs for assignment sites; no reads, no pass-by-value uses
```

One call. Mutation-only query — no enumerate-then-filter against a flat reference list. Pairs with `trace(handle, follow=["written_by"], max_depth=∞)` for transitive data-flow questions.

### "Find every `@cached_property` in the project"

```python
result = expand("functools.cached_property", edge="decorates")
# → list of stubs for every property decorated with @cached_property
```

One call. Decoration as a structural edge — no enumerate-then-filter.

### "What is `pydantic.BaseModel` and which project classes inherit from it?"

```python
node = inspect("pydantic.BaseModel")
# → {
#     handle: "pydantic.BaseModel",
#     kind: "class",
#     scope: "external",                              // defined in pydantic, not this project
#     location: { file: "<site-packages>/pydantic/main.py", ... },
#     signature, docstring, edge_counts: { members: 47, subclasses: 12, ... },
#     ...
#   }
# Note: edge_counts.subclasses is project-scoped — 12 classes in THIS project extend BaseModel.

descendants = expand("pydantic.BaseModel", edge="subclasses")
# → 12 stubs of project classes that extend BaseModel; no third-party subclasses
```

Two calls. The agent gets shallow info on the external class plus the project-scoped subclass list. `expand` doesn't try to enumerate subclasses across all installed packages.

### "Find every Flask route handler with their paths"

```python
result = expand(flask_app_handle, edge="routes@flask")
# → list of stubs; each .properties.route_path carries the URL pattern
```

One call. Derived view over `decorates` from `flask.Flask.route`; route path extracted by the plugin.

## Empirical Anchors

Design decisions are grounded in observed behavior of alternative MCPs (mcp-language-server, agent-lsp, Anthropic Pyright LSP plugin, Microsoft Pylance MCP). Three observations from 2026-05-02:

1. **Content shipping is expensive.** mcp-language-server's `definition` call on a 234-line class returned ~470 lines (canonical + build artifact copies). Agent rendered ~30 lines of structural answer. ~13× wire-format overhead.

2. **Outline as a primitive is missing across alternatives.** No LSP-bridge has a clean "structure of this scope" operation. agent-lsp made 7 MCP calls assembling outline from primitives. Pyeye took 4 (current API); progressive disclosure target is 1 (`outline()`).

3. **Project-aware scoping is missing.** `build/lib/` showed up as live code in three separate prompts across LSP-bridges. Pyeye must not.

These anchors validate the layering principle, the outline primitive, and project-aware scoping as real, measurable advantages — not aspirational design preferences.

## Open Questions for Implementation

Resolve during implementation rather than blocking the spec.

### Cursor mechanics

Pagination tokens for `expand`. Open questions:

- Opaque vs. structured? Probably opaque to discourage clients depending on internal shape.
- Stable across cache invalidation? If a file change invalidates the underlying edge set, the cursor should fail-soft (return error, agent restarts pagination).
- Default order? Alphabetical by handle? Frequency-weighted?

### Highlight ranking

`inspect` returns top-N adjacent handles per edge type. How to rank?

Heuristic stack to evaluate:

- Same package > adjacent package > different package
- Non-test > test
- In-edit-set (recently modified) > stable
- Frequency of reference (more callers = more central)

N defaults to ~5 per edge type. Configurable per-call.

### Trace stop conditions

`StopPredicate` schema. Initial proposal:

- `module_pattern: string` — glob match
- `exclude_tests: boolean`
- `same_package: boolean`
- `max_handles_per_node: number` — branching limit per node

Plugin-aware predicates worth considering: `exclude_kind: ["model@pydantic"]`?

### Bulk mode

How does the agent get "every reference" for a rename refactor without paginating?

Options:

- `expand(handle, edge=X, limit=Infinity)` — leans on existing API, expensive responses possible
- Separate `enumerate(handle, edge=X)` operation for bulk-only — explicit cost signaling
- `bulk: true` flag on `expand` — middle ground

Probably: explicit `bulk: true` flag with documentation that it bypasses pagination and may return large responses. Caller acknowledges the cost.

### Watcher / freshness contract

When pyeye returns `(file, line_start, line_end)`, how stale is the pointer? Specifically:

- Within a single call, pointers are current as of pyeye's index state.
- Across calls, pointers may go stale if the file changes between calls.
- Agent's responsibility: re-resolve the handle if it suspects staleness (e.g., after a Bash edit outside the watcher's view).
- Watcher health probe (from the cache plan, Phase 4) reports degraded state to pyeye, which can include a freshness warning in responses.

Concrete contract to settle: format of the freshness signal in responses (a `pointer_freshness: "fresh" | "watcher_degraded" | "stale_likely"` field on Node?).

### Plugin author API

Plugin authors need a clear interface to:

- Register identifier-form recognizers (extend `resolve`)
- Register edge types and traversal functions
- Register kinds and tag rules
- Declare a skill that ships alongside

Open: should this be a Python `AnalyzerPlugin` ABC (current design), a manifest file (`pyeye_plugin.toml`), or both?

### Edge-case handle resolution

The canonicality rule (definition site) handles re-exports cleanly. Several rarer Python patterns are flagged as known holes, deferred to implementation:

- **`if TYPE_CHECKING:` aliases** — symbols imported only for type-checking, not present at runtime. Pyright sees them; Jedi's view depends on configuration. Initial proposal: include them as resolvable, tag with `tags: ["type_only"]` so the agent knows the binding is virtual.
- **Conditional imports** — `try: import x; except: import y as x`. The handle resolves to whichever branch the static analyzer picks; document the chosen behavior.
- **Dynamic class creation** — `Foo = type("Foo", (Base,), {...})`, decorators that synthesize classes, `dataclasses.make_dataclass`. Static analysis can't always see these; pyeye returns "not found" rather than fabricating a handle. Plugins may extend resolution for known patterns (e.g., a plugin understands a specific factory).
- **Stub files (`.pyi`)** — when a `.py` definition has a corresponding stub, the canonical handle points to the `.py` definition; `re_exports` (or a stub-specific field) may indicate the stub location for type queries. Defer concrete shape.

These are known holes, not blockers. Most agent workflows don't encounter them; when they do, conservative behavior (return what static analysis sees, mark virtual bindings explicitly) is acceptable.

### Error semantics

Standardized shape when:

- Handle doesn't resolve
- Plugin throws during traversal
- Position is on whitespace / no symbol
- Project not configured

Initial proposal: every operation returns either success or `{ error: string, code: ErrorCode, recoverable: boolean }`. ErrorCode is a small enum (`unresolved`, `ambiguous`, `plugin_failed`, `no_symbol_at_position`, `project_not_configured`).

## Migration Plan

### Phased coexistence

Old and new APIs run in parallel during transition.

**Phase A — additive (no breaking changes):**

- Implement `resolve`, `resolve_at`, `inspect`, `outline`, `expand`, `trace` as new MCP tools alongside existing tools.
- Existing tools (`find_symbol`, `find_references`, etc.) continue to work unchanged.
- Plugins extend the new system; existing plugin tools (`find_models`, `find_validators`) remain temporarily.

**Phase B — convergence:**

- Plugin tools migrate to plugin-namespaced edges (`find_validators` becomes `expand(handle, edge="validators@pydantic")`).
- Existing tool documentation marks them deprecated, points to new operations.
- Existing tool implementations become thin wrappers calling new operations internally.

**Phase C — cleanup:**

- Remove deprecated tools after a transition period (e.g., one minor version).
- New API is the only public surface.

### Test conformance

A reference test suite validates implementations against the spec:

- Operation signatures and return shapes
- Edge type completeness
- Plugin extension mechanics
- Layering principle (no content in any response)
- Project-aware scoping (build artifacts excluded)

The existing `tests/integration/` and `tests/e2e/` work extends to cover new operations.

## Acceptance Criteria

The redesign is complete when:

1. All five operations (`resolve`, `inspect`, `outline`, `expand`, `trace`) are implemented and pass conformance tests.
2. The full core edge type vocabulary is supported, with `expand` and `trace` operating uniformly across them.
3. The Pydantic plugin has been migrated to the new model: it adds plugin edges (`validators@pydantic` etc.) and the existing `find_*` tools become deprecated thin wrappers.
4. Empirical comparison against the LSP-bridge baseline shows materially lower wire cost at same-or-better answer quality. **Floor targets** (these are floors, not goals — failing to clear them indicates the implementation is silently shipping content somewhere it shouldn't):
   - `outline(handle)` returns ≤ 0.5× the bytes the agent would assemble via the LSP-bridge synthesized equivalent (`documentSymbol` + `definition` + filtering across multiple calls).
   - `inspect(handle)` returns ≤ 0.3× the bytes of the LSP-bridge equivalent (typically `definition` shipping full source).

   Anchor from 2026-05-02 measurement: mcp-language-server's `definition` for a 234-line class returned ~470 lines per copy. Current pyeye (pre-redesign) was already at ~65% of LSP wire cost. Post-redesign with no content shipping should clear the 0.5× / 0.3× floors comfortably; if it doesn't, the implementation is leaking content fields somewhere and the layering CI check (criterion 11) should catch it.
5. Project-aware scoping verified: `build/`, `dist/`, `.tox/`, vendored packages excluded by default; configurable via project config.
6. Re-export canonicality verified: `resolve("package.Config")` and `resolve("package._impl.config.Config")` return the same handle when `Config` is re-exported; `inspect` on that handle lists `package.Config` in `re_exports`. References from both forms collapse in `expand(handle, edge="references")`.
7. Project/external boundary verified: `inspect("pydantic.BaseModel")` (or any third-party handle the project references) returns `scope: "external"` with shallow-derived data; `expand(external_handle, edge="subclasses")` returns project-internal subclasses only; `edge_counts` on external nodes are project-scoped.
8. Trace termination on cyclic graphs verified: a fixture with mutual recursion or a circular reference graph returns a subgraph in finite time even with `max_depth=Infinity`; cycle-completing edges appear in `Subgraph.edges`; nodes are deduped by handle.
9. Reference partition verified: a fixture with known reads, writes, and passes (e.g., a class attribute with 3 reads, 2 writes, 1 pass-by-value) confirms `expand(handle, edge="read_by")` returns exactly the read sites, `written_by` returns exactly the write sites, `passed_by` returns exactly the pass sites, and `references` returns the union with each stub's `subkind` correctly populated. `read_by` results must exclude call sites (those belong to `callers`).
10. Absence-vs-zero invariant verified for `edge_counts`: a fixture confirms (a) measured edges with no matches return `count: 0` (e.g., a class with no subclasses returns `subclasses: 0`); (b) unmeasured edge types are absent from `edge_counts` entirely; (c) the same distinction is verified for `re_exports`, `highlights`, `tags`, and `properties` — present-but-empty signals measurement, absence signals non-measurement. An implementation that fills unmeasured edges with zero fails this criterion.
11. The layering principle is enforceable in CI: a linter check rejects any new tool returning fields that contain source content.
12. Plugin author API is documented; an example third-party plugin demonstrates the extension model.
13. Migration documentation describes the deprecation path for current tools.

## Cross-References

**Project memory:**

- [`feedback_pyeye_layering.md`](../../../../.claude/projects/-home-mark-GitHub-pyeye-mcp/memory/feedback_pyeye_layering.md) — the layering principle in full
- [`project_api_redesign.md`](../../../../.claude/projects/-home-mark-GitHub-pyeye-mcp/memory/project_api_redesign.md) — the redesign direction (this spec is its concretization)

**Earlier specs:**

- [`2026-03-27-tool-ergonomics-design.md`](./2026-03-27-tool-ergonomics-design.md)
- [`2026-03-27-unified-lookup-tool-design.md`](./2026-03-27-unified-lookup-tool-design.md) — superseded on response shape; foundational on intake.

**Related plan:**

- [`2026-05-02-lookup-performance-cache.md`](../plans/2026-05-02-lookup-performance-cache.md) — internal infrastructure (Phase 1 complete; Phases 4–6 will be re-spec'd against this redesign).

**Issues:**

- #316 — tool ergonomics
- #320 — symbol_name parameter (subsumed by canonical handles)
- #321 — module FQN handling (subsumed by canonical handles)
