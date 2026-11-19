# Resolution and Determinism

This page is the written contract for *how pyeye resolves things*: which engine
answers which kind of question, how a name becomes a canonical handle, and what
pyeye says when it can't answer. It collects a principle that grew out of many
separate fixes. The reasoning behind each rule lives in its decision entry
under `docs/decisions/entries/`; this page states the rules and points there.

## Three tiers, by kind of question

### 1. Structural facts that are literally in the source: AST is the ground truth

Who subclasses `X`, who imports this module, what a relative import names, what
a package or class contains. These are answered from what is written in the
source, not from Jedi's type inference, which would add only non-determinism.
Where an edge needs Jedi, it says so and the fallback is measured (the
`subclasses` bullet below).

- `imported_by` is a pure-AST reverse scan (#436).
- Relative-import resolution has one AST seam, where there used to be two
  divergent resolvers (#426).
- The `subclasses` edge resolves bases AST-first, in the analyzer's class-graph
  walk. Jedi forward `goto` is the documented fallback for the bases the AST
  can't resolve; #419 measured how often Django needs it.
- `expand(subclasses)` builds its stubs from AST facts. It used to re-derive a
  Jedi `Name` per subclass, which brought #419's non-determinism back (#445).

### 2. Semantic inference: Jedi, bounded

Types, cross-file `goto`, signatures, re-export canonicalisation. Jedi is the
engine. Each use is bounded, and where Jedi's answer can be wrong or
non-deterministic the edge documents that tail rather than hiding it.

### 3. Reverse queries Jedi answers unreliably: deferred, never faked

Callers, references and reverse `edge_counts` are not answered with Jedi's
`get_references`, which is non-deterministically wrong. They are left to a
deterministic backend (#333) or to the client's LSP. The legacy tools that
answered them confidently and wrongly were removed in 2.0 (#505).

## The static-edge determinism invariant

> A static structural edge is **deterministic** and is built from
> **AST-derived facts**. It never re-derives each adjacent through Jedi.

This holds in practice for `imported_by` and `subclasses`, and each edge has its
own regression test. #452 tracks making it a registry-level check, so that a new
edge can't reintroduce the #445 pattern without a test failing.

## One canonical handle resolver

Every exact-path lookup goes through one resolver,
`pyeye.resolver.resolve_handle(path, analyzer) -> Resolved | NotFound` (#623). That covers
`inspect`, the `outline` root, the `expand` source, `trace` roots and interior
nodes, `resolve` and `resolve_at`, typeref forward refs, and the external
targets of the `imports` edge. Each tool echoes the handle the resolver returns.

**Canonical means definition site.** `pkg.Thing` re-exported from `pkg._impl`
resolves to `pkg._impl.Thing`, and every tool reports that handle. The one
exception is the standard library's private-module pattern: a public stdlib
class defined in a private module keeps its public name
(`collections.abc.Mapping`, not `_collections_abc.Mapping`), because that is
the name user code imports (#544).

The strategy is a table in `pyeye.resolver` that the resolver runs in order;
the first step that answers wins:

<!-- fact:begin resolver.strategy -->
Every path:

1. `project_module`: a project module, as a package or a single file
2. `namespace_package`: a PEP 420 namespace package: a directory with importable content and no init file

Then, inside the project:

1. `definition_placement`: the definition in the deepest project module along the path, following a re-export alias to its definition (an explicit import, or a `from x import \*` of a name x star-exports), with no fallback to shallower modules

Then, outside the project:

1. `private_stdlib`: a stdlib definition in a private module, named by its public re-exporting module
2. `external_module`: a stdlib or site-packages module, through a Jedi import
3. `external_definition`: a definition at exactly the requested path, found by goto
4. `guarded_inference`: an inferred definition, accepted only if its name equals the last component
<!-- fact:end -->

The path's top-level package picks the side, so external inference can never
answer for a project path, and a project path that the deepest module doesn't
define is not-found rather than retried somewhere shallower (#506). Inference
runs last because it can land on a different object: `typing.TYPE_CHECKING`
infers to `bool`, which is why a definition must sit at exactly the requested
path, and why a guessed answer is refused rather than returned.

Scope comes from one rule, `pyeye.resolver.scope_for`, shared by the resolver
and every edge stub: code inside the configured project boundary is `project`,
and everything else is `external`.

What is never a binding: the target of an attribute assignment (`self.x = …`,
`obj.attr = …`). Jedi gives it the same `full_name` as a local of the method, or
as a module member, but it binds nothing in that scope, so it is never placed
and never listed as a member (#567). Instance attributes are not modelled yet
(#565).

## Bare names

A bare (dot-free) name goes through `pyeye.resolver.resolve_name`, which returns
`Resolved`, `Ambiguous` (with candidates) or `NotFound`. Its policy is a table
too, and the first rule that answers wins:

<!-- fact:begin resolver.bare_name -->
1. `shadow`: a top-level package or module under more than one project root is ambiguous
2. `exact_module`: a complete top-level module (the project's package, a namespace root or an external module) wins over same-named definitions
3. `name_index`: every project definition with that name, canonicalised: one is the answer, several are ambiguous
4. `members`: only when nothing above matched, every method or class attribute with that name, decided the same way; dunder names never match
<!-- fact:end -->

Why this order:

- Picking one of two same-named top-level packages would hide the collision,
  so a shadow is always reported (#423).
- `resolve("functools")` should be stdlib `functools` even if the project
  defines something named `functools` (#602, #623); the project's symbol is
  reached by its dotted handle.
- Members are a fallback because methods and attributes are never in the name
  index: a top-level name therefore hides same-named methods, and every class
  defines the dunder names, so they would only ever be ambiguous (#508).

## The environment the resolver sees

Correctness must not depend on cache size or on Jedi internals:

- The name index is whole-project and lives outside the parsed-file LRU, so an
  eviction can never make a definition silently disappear (#457).
- Evicting an entry from parso's in-memory parse cache is harmless. parso's own
  GC once dropped stdlib files Jedi still held and made `asyncio.Queue`
  unresolvable in large runs (#684). pyeye now recovers a missing entry from the
  module's own tree, with an identical answer, and bounds the cache with an LRU
  of its own (#713, `pyeye._parso_cache`).
- Jedi's own private subprocess directory is never on the analysed `sys.path`;
  otherwise its files read as top-level modules (`resolve("functions")`) and
  shadowed configured packages (#722).

## Saying "I don't know" honestly

A miss is never dressed up as an answer:

- Every primitive except `trace` returns one not-found shape,
  `{found: false, <lookup echo>, reason, detail}`, with `reason` drawn from a
  closed per-operation set and `detail` naming the next step (#626). `trace`
  has no top-level miss: it lists roots it couldn't resolve in
  `unresolved_roots`.
- The resolver never guesses. A path it can't place is not-found, and it never
  hands back Jedi's raw `full_name`, which no other tool would accept.
- Absence is not zero. An omitted field means "not measured"; `[]` means
  "measured, none". `trace` keeps unresolved roots and interior callees in
  always-present fields (#488) rather than dropping them, and `imports` /
  `imported_by` list what they couldn't resolve or name (#494, #668).
- A file the server's interpreter can't parse is never silently skipped: a
  source whose own file fails reports `unparseable` (#703), and the scans
  <!-- fact:begin edges.unparseable -->`imported_by`, `subclasses`, `re_exports`<!-- fact:end --> list such files in
  `unparseable_files` (#729).

## Where the details live

- Decision entries: `docs/decisions/entries/`. Start with "One canonical handle
  resolver" and "Bare name: an exact top-level module wins" (#623).
- Edge design specs: `docs/superpowers/specs/` (expand core, imported_by).
- The agent-facing summary is in the `python-explore` skill
  (`skills/python-explore/SKILL.md`).
