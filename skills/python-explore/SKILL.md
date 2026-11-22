---
name: python-explore
description: Use when understanding, navigating, debugging, refactoring, or extending Python code with the pyeye MCP server. Triggers on "how does X work", "what does", "why is X doing", "is there a helper that…", "what calls/imports/subclasses this", "add feature", "implement", "refactor", "trace", "debug", "extend". Does NOT trigger for explicit "show me"/"read this file"/"print"/"display" requests, "what's the syntax for" language questions, single-line typo/string fixes with an exact location given, adding a new test case only, or when pyeye output for the symbol is already in context. Requires the pyeye MCP server.
---

# Python Explore

**Find with grep, prove with pyeye.** Text search is the fastest way to discover
*where* a concept lives. pyeye turns each hit into facts you can rely on: a
canonical handle, its kind and signature, what it contains, calls, imports and
extends. Read the source only where those facts point.

## The Split

| You have… | Use | Then |
|---|---|---|
| A concept or text, no name ("is there a helper that hashes files?", an error message, a config key) | `Grep` / `rg` over the source, with a few synonyms | turn each hit into a handle with `resolve_at(file, line, column)` |
| A name you know (`Settings`, `myapp.cache.Cache.evict`) | `resolve(name)` | `inspect` / `outline` / `expand` the handle |
| A position (a stack frame, a pasted line, a grep hit) | `resolve_at(file, line, column)` | the same |
| "Which modules use stdlib X?" (`hashlib`, `subprocess`, `pickle`) | `expand("hashlib", "imported_by")`: every project module importing it, in one call | `outline` the candidates |
| "Who calls / references this?" | your **LSP**, never grep (see [Honest Limits](#honest-limits-no-reverse-references)) | `resolve_at` maps its answers back to handles |

Grep **finds candidates**; it doesn't answer structural questions. A grep hit is
text: it can't tell a definition from a mention, an alias from a shadowed name, or
a call from a comment. Before you rely on a hit, resolve it and check the fact you
need with pyeye. And `imported_by` misses a helper that never imports the module
itself (it gets the function passed in, or calls a wrapper), so pair it with a grep
for the concept.

## The Model: Progressive Disclosure

Start at the cheapest step that answers your question.

1. **Orient:** `resolve` (or `resolve_at`) to a canonical handle, then `inspect` it,
   or `outline` a module or class for its skeleton.
2. **Drill:** `expand` one edge from a handle to its immediate neighbours.
3. **Trace:** `trace` follows edges across several hops (a call chain, an import
   closure, a member tree).

**Canonical handles are the currency.** A handle is Python's dotted notation
anchored at the *definition site*: stable across edits that don't rename or move the
symbol, and the same whichever import alias you came through. It's pyeye's name for
a definition, not always an importable path (a class defined in a function is
`pkg.mod.func.Name`), so pass handles back to pyeye rather than `import` them. pyeye
returns **pointers and structured facts, never source**: `Read` the `file:line` it
points at when you need the code.

**Rules:**

- Never re-explore what pyeye already surfaced in this conversation.
- Never answer a callers/references question with grep.
- Don't trigger for "show me" / "read this file" / "run" requests, "what's the
  syntax for" questions, a typo fix at a given location, or a new test case only.

## The Primitives

| Primitive | Use it to | Returns |
|-----------|-----------|---------|
| `resolve(identifier)` | Turn a name, dotted path, or `file:line` into a canonical handle | `{handle, kind, scope, location}`, or `{ambiguous, candidates}` |
| `resolve_at(file, line, column)` | Turn a position into a handle | same shape as `resolve` |
| `inspect(handle)` | Answer "what is this?": kind, signature, docstring, `edge_counts` | a structural Node, plus kind-dependent fields (e.g. `superclasses`); no source |
| `outline(handle)` | See a module's or class's skeleton in one call | a tree of member stubs (direct members by default; `max_depth` to go deeper) |
| `expand(handle, edge)` | Walk ONE edge to the immediate neighbours | a list of stubs |
| `trace(start, follow, …)` | Walk edges across several hops | a subgraph (nodes + edges) |

- **`kind`** is one of `class`, `function`, `method`, `module`, `variable`,
  `attribute`, `property`, `enum_member`. A name bound in a class body is
  `attribute`; module- and function-level names are `variable`.
- **`location`** comes with `resolve`, so you don't need `inspect` just for "where is
  it defined?".
- **Ambiguity:** a bare name can match several symbols. `resolve` then returns
  `{found: true, ambiguous: true, candidates: [...]}`. Pick one, or re-resolve the full
  dotted handle. A bare name that is a top-level module resolves to that module
  (`resolve("inspect")` is stdlib `inspect`); use the dotted handle for a project
  symbol of the same name. A bare method or class-attribute name is a fallback, tried
  only when no module or top-level definition matches; dunder names never match.
- **Capped lists:** `resolve` candidates and `expand` stubs are capped by default
  (`max_candidates`, `max_stubs`). When something was cut, the result says
  `truncated: true`, `truncation_reasons` and `total`; pass `None` for all. Defaults
  are in the [tool reference](../../docs/reference/tools.md).
- **Not found:** check `found` on every result. A miss is `{found: false, <your input
  echoed>, reason, detail}` with no node, tree or stubs, and `detail` names the next
  step. `reason: "unresolved"` means pyeye couldn't resolve the handle as written:
  unknown, **not** evidence the symbol is absent (an instance attribute set in
  `__init__` never resolves). Re-`resolve` the bare name; if that misses too, `Read`
  before concluding anything. `resolve_at` can also say `file_not_found` or
  `no_symbol_at_position`. Only a `handle` key is ever a handle.
- **Errors vs misses:** a call that ran always returns a response. A **tool error**
  means it couldn't run (an invalid argument, a missing `project_path`, an unusable
  config); fix what the message names and call again.
- **Unparseable source:** a file the server's Python can't parse has unmeasured
  edges: `reason: "unparseable"` from `expand` / `trace`, and `truncation_reason:
  "unparseable"` in `outline`. Unknown, not empty: `Read` the file.
- **Stubs:** a `.pyi`-only module has handles; a `.py` beside a stub wins. Nodes
  declared in a `.pyi` carry `stub: true`, and `callees` on a stub declaration says
  `reason: "stub_declaration"` (unknown, not "calls nothing").
- **`scope`** is `"project"` or `"external"` (stdlib, site-packages). External symbols
  get project-scoped answers: `expand("pathlib.Path", "subclasses")` lists only this
  project's subclasses of `Path`.

## Supported Edges

`expand` and `trace` walk these edges, the **complete** set pyeye answers today:

<!-- fact:begin edges.implemented -->
`members`, `callees`, `imported_by`, `subclasses`, `superclasses`, `imports`, `enclosing_scope`, `submodules`, `re_exports`
<!-- fact:end -->

| Edge | Direction | Meaning |
|------|-----------|---------|
| `members` | container → children | a class's methods and class-level attributes, or a module's top-level definitions (imported names belong to `imports`) |
| `submodules` | package → child modules | a package's direct child modules and subpackages |
| `enclosing_scope` | child → parent | the lexical scope containing this symbol (method → class) |
| `callees` | function → what it calls | forward call targets resolved from the body; calls it couldn't resolve are counted in `unresolved_call_sites` |
| `subclasses` | class → direct subclasses | project classes that **directly** extend it (the closure via `trace`) |
| `superclasses` | class → its bases | direct bases in declaration order; ones that don't resolve are in `unresolved_superclasses`, with the reason in `unresolved_superclass_details` |
| `imports` | module → what it imports | every import binding a module-scope name, including under `if TYPE_CHECKING:` and `try`/`except ImportError`. A TYPE_CHECKING-only target carries `type_only: true` (on the edge in `trace`) |
| `imported_by` | module → its importers | project modules importing it, wherever the import sits (a lazy import in a function counts). Works on a stdlib or installed module too |
| `re_exports` | symbol → public re-exporting modules | each stub is a module; its `bindings` are the public paths it provides (`["pkg.Foo"]`) |

`imports` and `imported_by` aren't exact inverses: a lazy import shows in
`imported_by` but not in the importer's `imports`. `subclasses` and `imported_by`
stubs are pointers (no `signature`): `inspect` one to drill in.

**Static-surface ceiling.** Each edge is complete only over a stated scope. A class's
`members` (and its `outline`) are its **class-body definitions**: instance attributes
set in methods (`self.x = …`) are not measured, and nothing injected at runtime
(metaclasses, `setattr`, `__getattr__`, `type(...)`, `__init_subclass__`, `importlib`
with a computed name) is seen. So a Django `Model`'s `outline` omits `_meta` and
`objects`. An absent member, subclass or importer means "not measured in that
scope", **not** proof of absence. Each response names its ceiling (`ceiling` on
`expand` and `outline`, `ceilings` on `trace`):

<!-- fact:begin ceilings.table -->
| Ceiling | Complete over |
|---|---|
| `declared_bases` | the bases written in the class statement; bases added at runtime are not included, and bases that don't resolve to exactly one class are listed in unresolved\_superclasses, an ambiguous base (imported by a try/except shim, or rebound by an if/else) among them (#1057) |
| `literal_subclassing` | project classes whose class statement names this class as a base, resolved as superclasses resolves it: a class whose base is ambiguous (imported by a try/except shim, or rebound by an if/else) is not listed under any of its candidates (#1057). Classes built with type(), class factories or \_\_init\_subclass\_\_ registration are not included. The scan skips virtual environments (a directory holding pyvenv.cfg, whatever its name) and directories named like caches or build output (build, dist, env, venv, .tox and the like) unless they hold \_\_init\_\_.py or \_\_init\_\_.pyi; a PEP 420 namespace package with such a name is not scanned (#1104) |
| `on_disk_modules` | modules and subpackages present on disk under the package; entries added to \_\_path\_\_ at runtime are not included |
| `package_reexports` | import bindings written in source in the public modules of the symbol's own package (#712); re-exports from other packages and names provided lazily by a module \_\_getattr\_\_ are not included |
| `static_calls` | calls whose target static analysis resolves; dynamic calls are counted in unresolved\_call\_sites, not listed |
| `static_definitions` | definitions written in source: a class body (methods, nested classes, class-level assignments) or a module's top level. Instance attributes assigned in methods (self.x = ...) and anything injected at runtime (metaclass, setattr, \_\_getattr\_\_, type(), \_\_init\_subclass\_\_) are not included |
| `static_imports` | import statements written in source; importlib / \_\_import\_\_ with a computed name is not included. A stub's (.pyi) own imports are declarations, not runtime imports: imported\_by doesn't count them, while imports on a stub module lists them (#933). For imported\_by, the scan skips virtual environments (a directory holding pyvenv.cfg, whatever its name) and directories named like caches or build output (build, dist, env, venv, .tox and the like) unless they hold \_\_init\_\_.py or \_\_init\_\_.pyi; a PEP 420 namespace package with such a name is not scanned (#1104) |
<!-- fact:end -->

`enclosing_scope` has none: lexical nesting is exact. Which edges repeat across
sessions (the determinism tiers) is in [reference.md](reference.md#determinism).

## Honest Limits: No Reverse References

**"Who calls this?" and "what references this?" can't be answered by pyeye.** The
edges <!-- fact:begin edges.deferred -->`callers`, `decorated_by`, `decorates`, `overridden_by`, `overrides`, `passed_by`, `read_by`, `references`, `written_by`<!-- fact:end --> are **deferred** to a reference backend (Pyright) that isn't wired up yet
([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). Asked for one, pyeye
refuses rather than guessing, and `inspect`'s `edge_counts` omits them (never `0`):

```json pyeye-example tool=expand
{"handle": "myapp.cache.Cache.evict", "edge": "callers"}
```

```json pyeye-output
{"found": true, "edge": "callers", "unsupported": true, "reason": "deferred_reference_backend",
 "stubs": "<absent>", "…": "<omitted>"}
```

**Delegate to your LSP** (a Pyright/Pylance-backed tool, e.g. Claude Code's `LSP`):

1. `resolve(name)` gives the definition's `location` (file, line, column).
2. Ask the LSP at that position: `findReferences`, or `incomingCalls` for callers.
3. `resolve_at` maps any position it returns back to a pyeye handle.

pyeye drives orientation and forward facts; the LSP answers the inbound questions.
Don't ask both for the same fact: they infer independently and can disagree. Why the
line falls here, and how a name becomes a handle:
[Resolution and Determinism](https://github.com/okeefeco/pyeye-mcp/blob/main/docs/architecture/resolution.md).

**Never fake it with grep.** A text search for a name under-reports (aliases,
`getattr`, re-exports) and over-reports (comments, shadowed names), and nothing tells
you which. With no LSP, say so: "pyeye can't give reliable caller data (#333), and
there's no LSP here". Then offer what pyeye *can* answer: `callees`, `imported_by` /
`imports`, `subclasses` / `superclasses`, `members`.

> **No legacy escape hatch.** v2.0 removed `find_references`, `get_call_hierarchy`, `analyze_dependencies`:
> they answered confidently and wrongly, and a confident wrong answer is worse than an
> honest "not available".

Hit a pyeye bug or limitation? Every `unsupported` result carries a `report_issues`
URL, and the `pyeye://about` resource gives the version and issues URL. Surface it.

## Absence vs Zero

A value pyeye returns is a measured claim over a stated scope; **anything it doesn't
return, or can't resolve, is unknown, not absent.**

- `expand`'s `stubs: []` with `found: true` is a measured zero. `found: false` is a
  miss, not proof of absence.
- In `edge_counts`, a **missing key means "not measured"**; `superclasses: 0` means
  measured, none.
- `inspect`'s `deprecation`: `[]` means read and none found; an absent key means it
  couldn't read the definition. Only `kind: "unconditional"` says the symbol is
  deprecated. `overloads` lists the `@overload` signatures callers see, while
  `signature` is the implementation's.
- An `expand` or `trace` result carries honesty fields that say where it is
  incomplete: `unresolved_call_sites`, `unresolved_imports`, `unresolved_importers`,
  `unparseable_files`, `handleless_subclass_count`, `unreadable_definitions`, and
  `trace`'s `unresolved_roots` / `unresolved_nodes`. Check the ones for your edge
  before calling a result complete ("no subclasses", "nothing imports this", "this is
  everything it defines"). What each means: [reference.md](reference.md#honesty-fields).

## Framework Plugin Tools: Always `envelope=true`

When pyeye detects Pydantic, Django or Flask, it also registers that framework's
tools ([tool reference](../../docs/reference/tools.md#plugin-tools)). They are
callable by name as soon as `configure_packages` lists them in `activated_plugins`.
Pass `project_path` for another project. **Always call them with `envelope=true`**:

```json pyeye-example tool=find_django_models fixture=docs_examples_django
{"envelope": true}
```

```json pyeye-output
{"scope": "main", "searched": ["main"], "unsearched_scopes": [], "rejected_paths": [],
 "results": [{"name": "Product", "handle": "shop.models.Product", "…": "<omitted>"}]}
```

- **`results`** is the answer (`[]` = searched, none found).
- **`unsearched_scopes`** lists configured scopes the search did **not** cover. If
  it's non-empty, don't call the result complete: retry with `scope="all"`, or say
  which scopes you didn't search.
- **`rejected_paths`** lists config entries the path check refused; tell the user. A
  missing key means the check couldn't run.
- **`unplaced_classes`** (`find_pydantic_models`): classes whose base is an
  expression, any of which may be a model not in `results`.
- A record's `handle` goes straight to `inspect` / `outline` / `expand`; a record with
  `unresolved` has no handle. A tool *error* means the search failed, not "none".

## Worked Examples

Handles use a placeholder project (`myapp.…`). Each `json pyeye-example` block is a
real call (arguments only; `project_path` is yours), and the `json pyeye-output`
after it is the response, trimmed: `"…": "<omitted>"` marks left-out keys, a final
`"<omitted>"` left-out items, and `"<absent>"` a key the response doesn't have. CI
runs them against a small `myapp` project.

**"Is there a helper that hashes a file?"** Find with grep, prove with pyeye. The
concept has no name yet, so search the text:

```text
Grep(pattern="sha256|hashlib|digest", glob="*.py")  -> myapp/digest.py:7: def sha256_of(path: Path) -> str:
```

Turn the hit into a handle, then check what it is:

```json pyeye-example tool=resolve_at
{"file": "myapp/digest.py", "line": 7, "column": 4}
```

```json pyeye-output
{"found": true, "handle": "myapp.digest.sha256_of", "kind": "function", "…": "<omitted>"}
```

```json pyeye-example tool=inspect
{"handle": "myapp.digest.sha256_of"}
```

```json pyeye-output
{"found": true, "kind": "function", "signature": "sha256_of(path: Path) -> str",
 "docstring": "Hex SHA-256 of a file's contents.", "…": "<omitted>"}
```

When the concept is a stdlib module, its importers are the candidate set in one call:

```json pyeye-example tool=expand
{"handle": "hashlib", "edge": "imported_by"}
```

```json pyeye-output
{"found": true, "edge": "imported_by", "stubs": [
  {"handle": "myapp.digest", "kind": "module", "…": "<omitted>"}], "…": "<omitted>"}
```

**"What is `Settings`?"** Orient in one or two calls:

```json pyeye-example tool=resolve
{"identifier": "myapp.config.Settings"}
```

```json pyeye-output
{"found": true, "handle": "myapp.config.Settings", "kind": "class", "scope": "project",
 "location": {"…": "<omitted>"}}
```

```json pyeye-example tool=inspect
{"handle": "myapp.config.Settings"}
```

```json pyeye-output
{"found": true, "kind": "class", "signature": "Settings()",
 "superclasses": ["myapp.base.ConfigBase"],
 "edge_counts": {"members": 3, "superclasses": 1, "subclasses": "<absent>", "callers": "<absent>"},
 "…": "<omitted>"}
```

`subclasses` is absent from `edge_counts` (not counted), not `0`: `DevSettings` does
subclass `Settings`, and `expand(..., "subclasses")` finds it.

**Ambiguous name:** let `resolve` disambiguate; don't guess.

```json pyeye-example tool=resolve
{"identifier": "Settings"}
```

```json pyeye-output
{"found": true, "ambiguous": true, "candidates": [
  {"handle": "myapp.cli.Settings", "kind": "class", "…": "<omitted>"},
  {"handle": "myapp.config.Settings", "kind": "class", "…": "<omitted>"}]}
```

**"What's inside this module?"** The skeleton in one call:

```json pyeye-example tool=outline
{"handle": "myapp.cache"}
```

```json pyeye-output
{"found": true, "ceiling": "static_definitions",
 "node": {"handle": "myapp.cache", "kind": "module", "…": "<omitted>"},
 "children": [
   {"node": {"handle": "myapp.cache.DependencyTracker", "…": "<omitted>"},
    "truncated": true, "truncation_reason": "max_depth", "member_count": 2,
    "unreadable_definitions": []},
   "<omitted>"],
 "unreadable_definitions": [],
 "truncation_reasons": ["max_depth"]}
```

`outline` lists direct members by default. A nested container comes back `truncated`
with `member_count`: "not walked yet", not empty. The root's `truncation_reasons`
lists every reason anything was cut: `max_depth` and `max_nodes` are budgets (raise
them, or `outline` the node), `external` and `survey_leaf` are boundaries by design
(`outline` that node), and `unparseable` means `Read` the file. On a *package*,
`outline` surveys its submodules. More in [reference.md](reference.md#outline).

**"What does this function call?"** Forward and reliable:

```json pyeye-example tool=expand
{"handle": "myapp.cache.Cache.evict", "edge": "callees"}
```

```json pyeye-output
{"found": true, "edge": "callees", "ceiling": "static_calls", "unresolved_call_sites": 0,
 "stubs": [
   {"handle": "myapp.cache.DependencyTracker.dependents", "kind": "method", "…": "<omitted>"},
   "<omitted>"],
 "…": "<omitted>"}
```

**Across hops:**

```text
trace("myapp.plugins.Base", follow=["subclasses"], max_depth=3)  -> bounded subclass closure
trace("myapp.cache.Cache.evict", follow=["callees"], max_depth=3)  -> 3-hop call structure
trace("myapp", follow=["imports"])  -> import closure; an edge back to the start is a cycle
```

**"Who calls `Cache.evict`?"** pyeye defers it; resolve the position and hand it to
the LSP:

```json pyeye-example tool=resolve
{"identifier": "myapp.cache.Cache.evict"}
```

```json pyeye-output
{"found": true, "handle": "myapp.cache.Cache.evict", "kind": "method",
 "location": {"line_start": 25, "column_start": 8, "…": "<omitted>"}, "…": "<omitted>"}
```

```text
LSP.incomingCalls(<location.file>, line=25, character=9)  -> real callers, with call sites
```

## While You Edit

A project file change drops pyeye's whole-project indices, and the next query that
needs one rebuilds it by walking the project. Bare-name `resolve`, and `subclasses`,
`imported_by` and `re_exports`, need one; dotted or positional `resolve`,
`resolve_at`, `outline` and the other edges don't. So ask the whole-project questions
before a run of edits and once after it, not between edits. Details:
[reference.md](reference.md#while-you-edit).

## Stating Your Mental Model

For a non-trivial change, state what you found, in **handles + `file:line`**, so the
user can correct you, and say plainly what pyeye couldn't confirm:

```markdown
**Mental model: `myapp.cache.Cache`** (`myapp/cache.py:31`)
- Depends on: `myapp.config.Settings`, `collections.OrderedDict`
- 7 members, 1 superclass (measured)
- Callers: from the LSP; without one, caller impact is unverified (#333)
```

If pyeye is unavailable, say so ("pyeye unavailable, falling back to `Read`") and
carry on with `Read` and grep.

## Red Flags

- Answering "who calls / references this?" with grep instead of the LSP (or, with no
  LSP, an honest "not available").
- Treating a grep hit as a structural fact (its kind, its callers, that it's the only
  definition) without resolving it.
- Reading whole files to find a concept a grep would locate in one search.
- Grepping for a name you already know: `resolve` it.
- Reaching for a pre-v2.0 tool name: the primitives above, plus the framework plugin
  tools, are the whole surface.
- Calling a plugin tool without `envelope=true`, or reporting `results` as complete
  while `unsearched_scopes` is non-empty.
- Re-exploring a symbol pyeye already surfaced in this conversation.
- Asking a whole-project question after every edit in a run of edits.
