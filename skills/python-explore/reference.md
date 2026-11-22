# Python Explore: Reference

Detail behind [SKILL.md](SKILL.md), for when a result needs reading closely. Load it
on demand; the skill itself covers the everyday calls.

## Honesty Fields

`expand` and `trace` results carry fields that say where they are incomplete. **Read
them before treating a result as complete**: an empty or clean-looking subgraph can
mean a resolution miss, not a real zero. `trace` carries maps keyed by node; `expand`
carries the same signal as flat fields for its one node.

- **`unresolved_roots`** (always present): `[]` means every root resolved. A **non-empty**
  list means those start handles did *not* resolve — so `nodes: {}` with a non-empty
  `unresolved_roots` is "I couldn't resolve the root" (a cold-start miss is possible, #419),
  **not** "this root has no neighbours." Retry, `resolve`/`inspect` the handle, or fall back
  to `Read`/your LSP — do not conclude the symbol calls/contains nothing.
- **`unresolved_nodes`** (always present): interior nodes `trace` reached but could not
  resolve (the same handles `expand` answers `found: false` for),
  so it did **not** walk them. A node listed here is a dead end of the walk, **not** a
  node with no neighbours.
- **`unsupported_edges`** also lists an edge that doesn't apply to some node's kind
  (e.g. `imports` on a class), with `reason: "not_applicable"`: its `detail` names the
  kind and the kinds the edge does apply to. Those nodes were not walked along that
  edge — that's "not applicable", not "measured, none". `expand` gives the same
  `not_applicable` answer directly (e.g. `members` on a function, `subclasses` on a
  module), never a `stubs: []`.
- **`unresolved_call_sites`** (present only when you traced `callees`): a `{handle: count}`
  map of nodes whose outbound calls were *not* fully resolved (dynamic/un-inferable sites,
  or a flaky miss). A node listed here has **incomplete callees** — don't treat its part of
  the call graph as exhaustive. An absent field means call sites weren't measured (you
  didn't trace `callees`); `{}` means traced and all resolved.
- **`unresolved_imports`** (present only when you traced `imports`): a `{handle: [target, …]}`
  map of nodes whose `imports` walk couldn't resolve a statically-present `from X import Y`
  (each entry is the intended dotted target). A node listed here has an **incomplete import
  set** — a dependency closure is missing those edges. `expand(handle, "imports")` carries
  the same signal as a flat `unresolved_imports: [target, …]` list (`[]` when all resolved).
- **`unresolved_importers`** (present only when you traced `imported_by`): a
  `{handle: [file, …]}` map of files that import that module but have **no module name**
  (a path part that isn't a Python identifier, e.g. `my-script.py`, `tools-dir/x.py`), so
  they can't be stubs. They are still dependents: count them when sizing fan-in.
  `expand(handle, "imported_by")` carries the same flat `unresolved_importers: [file, …]`
  list (`[]` when every importer has a handle).
- **`unparseable_files`** (present only when you traced one of <!-- fact:begin edges.unparseable -->`imported_by`, `subclasses`, `re_exports`<!-- fact:end -->): a
  `{handle: [file, …]}` map of project files the server's Python **couldn't parse** (often
  newer syntax than its interpreter), so the reverse scan never read them. A subclass or
  importer defined there is **unknown, not absent**. `expand` on one of those edges
  carries the same flat `unparseable_files: [file, …]` list (`[]` when every
  file parsed). Read those files, or run pyeye on a newer Python, before concluding.
- **`handleless_subclass_counts`** (present only when you traced `subclasses`): a
  `{handle: count}` map of nodes with direct subclasses that **no handle can name**: a
  class two or more function levels deep (`nested_local`), one whose name is bound more
  than once in its function, by any Python binding: another class, a `def`, a parameter, an import or an assignment (`ambiguous_local`), or one in a file with no module path
  (`migrations/0001_initial.py`). A class in a function, one level deep and unique, does
  have a handle (`pkg.mod.func.Name`). They're real subclasses, so add them when you count, but `trace`
  can't walk below them. `expand(handle, "subclasses")` carries `handleless_subclass_count`
  (always complete) and `handleless_subclasses: [{name, file, line, reason}, …]` to `Read`
  them; `max_stubs` caps that list on its own, so `count > len(list)` means it was cut.
- **`unreadable_definition_counts`** (present only when you traced `members`): a
  `{handle: count}` map of containers with definitions **pyeye's parser couldn't read**.
  Python parses the file, but newer syntax in a definition's header (PEP 646
  `*args: *Ts` or `Generic[*Ts]`, PEP 695 `[*Ts, **P]` or `type Pair[T] = ...`) defeats
  Jedi's parser, so the definition isn't listed. `expand(handle, "members")` and
  `outline` carry `unreadable_definitions: [{name, kind, line, reason}, …]` (`[]` when
  none), and `inspect` carries `unreadable_definition_count`. Asking for such a
  definition answers not-found with a detail naming its line: Read it there.

So "no callers"-style reasoning from a `trace` result requires `unresolved_roots == []` **and**
(for call graphs) the relevant node absent from `unresolved_call_sites`; a dependency-closure
claim from `imports` likewise requires the node absent from `unresolved_imports`, and a
"nothing depends on this" claim from `imported_by` requires it absent from `unresolved_importers`
— and, for `imported_by` and `subclasses`, an empty `unparseable_files`. A "no subclasses"
claim also needs `handleless_subclass_count == 0` (or the node absent from
`handleless_subclass_counts`). A "this is everything it defines" claim from `members`
needs `unreadable_definitions == []`.

## Determinism

Each edge has a determinism tier (#452): which engine picks its adjacents, and so
what repeats across sessions. `goto` edges can return a different external (stdlib
or installed) target from one session to the next, so compare their project-scope
stubs across sessions, never their external ones:

<!-- fact:begin determinism.table -->
| Determinism | Edges | Guarantee |
|---|---|---|
| `filesystem` | `submodules` | read from a directory listing, without calling Jedi; the same result in every process for the same files on disk |
| `ast` | `imported_by`, `re_exports` | read from the syntax tree of the project's files, without calling Jedi; the same result in every process for the same source |
| `jedi_local` | `members`, `enclosing_scope` | read by Jedi from the source's own file, with no cross-file inference; the same result in every process for the same source |
| `goto` | `callees`, `subclasses`, `superclasses`, `imports` | each adjacent is a Jedi forward goto target. Project-scope adjacents are the same in every process; an external (stdlib or installed) target behind a try/except import shim may differ between processes (#419), so don't compare external adjacents across sessions. A name bound to more than one target (a base imported by a try/except shim, or rebound by an if/else) resolves to none, never to a pick (#1057) |
<!-- fact:end -->

## Outline

`outline` defaults to **direct members only** (`max_depth=1`) for every root.
A nested container that has members comes back `truncated: max_depth` with no
`children`, plus `member_count` saying how many it holds. That means "not walked
yet", not "empty": `outline` its handle to drill in, or pass a larger `max_depth`
(`None` = unbounded, still capped by `max_nodes`).

Check the root's `truncation_reasons` first: it lists every reason any node was
cut for (absent when nothing was). `max_depth` / `max_nodes` are budget cuts, so
raise the limit, and the node's count says how much is missing. `external` /
`survey_leaf` are boundaries by design, so outline that node instead.
`unparseable` means the node's file doesn't parse under the server's Python, so
read the file.

**Cold start: "what's in this package / project?"** — orient top-down, drill on
demand. `outline` on a *package* surveys its child modules/subpackages (depth-1
by default — subpackages marked `truncated: max_depth`); pass a higher
`max_depth`, or `expand`/`trace` the `submodules` edge, to go deeper. A survey
lists modules, not their members: a module that has members comes back
`truncated: survey_leaf` (`outline` that module to see them), and only a
genuinely empty one is `children: []`. A package's own `__init__` members are
not listed either — `member_count: N` on a walked package says how many were left
out (`expand(pkg, "members")` lists them). Counts are named for their edge and
match `inspect`'s `edge_counts`: a survey cut by `max_nodes` carries
`submodule_count`. A package with no submodules is outlined
by its members instead:

```json pyeye-example tool=resolve
{"identifier": "myapp"}
```

```json pyeye-output
{"found": true, "handle": "myapp", "kind": "module", "scope": "project", "…": "<omitted>"}
```

```text
outline("myapp")                  -> direct submodules/subpackages (depth-1 survey)
expand("myapp.db", "submodules")  -> one hop of a subpackage's children
trace("myapp", follow=["submodules"], max_depth=3)  -> bounded package tree (capped + `truncated`)
```

Then drill: `resolve(root) → outline(pkg) | expand(pkg, "submodules") → pick a
module → inspect / expand("members") / trace`.

> **Namespace-rooted packages work the same way.** A PEP 420 namespace package
> (no `__init__.py` at its root) resolves to `kind: "module"`, anchored on its
> directory, and namespaces configured in `.pyeye.json` count as `scope:
> "project"`, including repos that live outside the project root.

## While You Edit

Any change to a project file makes pyeye drop that project's whole-project
indices once the watcher's debounce (<!-- fact:begin env.PYEYE_WATCHER_DEBOUNCE.default -->0.5<!-- fact:end --> s by default) passes.
Nothing is rebuilt until a query needs an index. That query then rebuilds it by
walking every project file; unchanged files are re-parsed only if the parsed-file
cache has dropped them.

**Rebuilds a whole-project index on its first use after an edit:**

- bare-name `resolve` (`resolve("Config")`): the name and member indices;
- `expand` / `trace` on `subclasses` (the class graph) or `imported_by` (the
  import graph);
- `expand` / `trace` on `re_exports`, and `inspect` on any handle that isn't a
  module: its deprecated `re_exports` field reads the same scan.

**Cheap after an edit (no project walk):** dotted and `file:line` `resolve`,
`resolve_at`, `outline`, `inspect` on a module, and `expand` / `trace` on
`members`, `callees`, `imports`, `superclasses`, `submodules` and
`enclosing_scope`.

- **Ask the whole-project questions before a run of edits**, while you plan it:
  what subclasses or imports the code you'll change, and the handles you'll need.
- **Don't ask them between edits.** Each one after an edit pays a rebuild.
- **After the run, one query pays the rebuild once.** Use it to check the result.
- Between edits, navigate by dotted handle or `file:line`, not by bare name.

## Dependency and Coupling Analysis

Module relationships are answerable from two static edges — `imports` (what a
module depends on) and `imported_by` (which project modules depend on it) — plus
`trace(follow=["imports"])` for the multi-hop closure. From those you can compute
the standard coupling metrics by hand:

- **Fan-out (efferent):** size of `expand(mod, "imports")` — how many things this
  module depends on. High fan-out = many reasons to change = fragile.
- **Fan-in (afferent):** size of `expand(mod, "imported_by")` — how many project
  modules depend on this one. High fan-in = changes here are risky.
- **Instability:** `fan_out / (fan_in + fan_out)`. `0` = stable (depended on,
  depends on nothing); `1` = unstable (depends on others, nothing depends on it).
  Entry points sit near 1; core/shared modules near 0.

**Detecting cycles:** `trace(start=mod, follow=["imports"])`, then scan the
returned `edges` for one whose `to` is the start module. `trace` visits each node
once but still records edges back into already-visited nodes, so that back-edge is
exactly an `A → … → A` circular dependency. (Look in `edges`, not `nodes` — nodes
are deduped, so the start won't literally reappear.) Standard ways out: extract a
shared base module both can import, inject the dependency instead of importing it,
or move the import inside the function (lazy import).

**Reading the architecture:** a clean layered design shows imports flowing one
direction (API → services → models → external) with no back-edges; a "utility
hub" shows one low-instability module with high fan-in; a cycle is the
anti-pattern. Map a few key modules with `expand(…, "imports")` to see which
shape you have before refactoring.

> Same static-surface ceiling as everywhere else: `imports` covers
> <!-- fact:begin ceiling.static_imports -->import statements written in source; importlib / \_\_import\_\_ with a computed name is not included. A stub's (.pyi) own imports are declarations, not runtime imports: imported\_by doesn't count them, while imports on a stub module lists them (#933). For imported\_by, the scan skips virtual environments (a directory holding pyvenv.cfg, whatever its name) and directories named like caches or build output (build, dist, env, venv, .tox and the like) unless they hold \_\_init\_\_.py or \_\_init\_\_.pyi; a PEP 420 namespace package with such a name is not scanned (#1104)<!-- fact:end -->, so an absent edge
> means "not imported in source," not "never loaded."
