---
date: "2026-11-23"
title: "A runtime binding beats a TYPE_CHECKING-only binding of the same name (#1106)"
issues: [1106, 1088, 1081, 857, 437]
anchors: ["pyeye.resolver.prefer_runtime_bindings", "pyeye.resolver._anchor_on_bindings", "pyeye._module_scope.type_only_lines", "pyeye.mcp.operations.edges._collect_members", "pyeye.resolver.shadowed_by_type_only", "pyeye.mcp.operations.inspect._build_signature", "tests/test_type_checking_runtime_anchor.py"]
status: "active"
amends: ["2026-11-22-1088-an-overloaded-function-anchors-on-its-implementation.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A runtime binding beats a TYPE_CHECKING-only binding of the same name (#1106)

**Friction:** Scrapy 2.20.0's `Spider` declares `parse: CallbackT` under `if TYPE_CHECKING:` and defines `def parse(self, response, **kwargs)` in the `else:`. #857's `_anchor_on_bindings` kept the first binding for an `if`/`else` pair, so `resolve`, `inspect`, `expand(members)` and `outline` all reported `parse` as an `attribute` at the declaration. The method's signature, docstring and location were never shown. #1092's coverage check found it.

**Decision** (maintainer's ruling on #1106, 2026-11-23, via designer; coordinator-3 approved this entry):

- **The runtime binding wins** for kind, signature, docstring and location. This is #1088's principle (anchor on what runs, not on what declares it), using #1081's reading of the guard.
  - A binding is type-only when its line is in a branch only a type checker takes: the body of `if TYPE_CHECKING:`, or the `else` of `if not TYPE_CHECKING:`, at any depth. Class and function bodies count too (`pyeye._module_scope.type_only_lines`).
  - The guard spellings are #1081's: bare, aliased, `typing.`/`typing_extensions.`.
- **One rule, everywhere it matters.** `resolver.prefer_runtime_bindings` drops the type-only bindings when runtime ones exist.
  - `_anchor_on_bindings` applies it before its other rules (#857, #1088), which then see only the runtime bindings.
  - The members dedup (`edges._collect_members`) keeps the same binding, so a member's stub matches what `resolve` anchors.
- **Unchanged:**
  - a name bound only under the guard keeps its declaration;
  - a pair with no type-only branch keeps #857's answer (`sys.version_info` `if`/`else` keeps the first);
  - names from several files (namespace stubs) keep the first portion's;
  - a file the server's Python can't parse keeps the first binding (#703).
- **The signature comes from source when the declaration shadows it.** Jedi infers the runtime `def` as the declaration's type (`Callable`), so `get_signatures()` is empty. When Jedi has no signature at all AND a TYPE_CHECKING-only binding of the same name shares the def's scope (`resolver.shadowed_by_type_only`), `inspect` renders the signature from the source def, the reconstruction #437 uses. Any other def without a Jedi signature (a `@property`) still has none, and signatures #999 filters out are still not shown.
- **Any runtime binding wins, not only a `def` or `class`** (ruling (i), designer via coordinator-3, 2026-11-23). This includes the idiom `if TYPE_CHECKING: from x import A` / `else: A = object`: `A` anchors on the runtime placeholder `A = object`, not on the import. That is what `A` is when the code runs; the type checker's view of it is not reported.
- **No new field.** A field exposing the type-only binding, additive like `overloads`, is noted for later, only if agents trip over it. It isn't filed.

**Anchor:** `pyeye.resolver.prefer_runtime_bindings`; `pyeye.resolver._anchor_on_bindings`; `pyeye._module_scope.type_only_lines`; #1106.

**Applies-to:**

- `pyeye._module_scope.type_only_lines` and `_guard_kind` (shared with `iter_module_scope_imports_guarded`);
- `pyeye.resolver.prefer_runtime_bindings` and `_anchor_on_bindings`, and through them `resolve`, `resolve_at` and `inspect`;
- `pyeye.mcp.operations.edges._collect_members` (`members`, and `outline`'s children);
- `pyeye.resolver.shadowed_by_type_only` and `pyeye.mcp.operations.inspect._build_signature`;
- the pinned answers that changed: `tests/test_reexport_relative_collapse.py`'s `type_checking_branch` case and `tests/test_docs_facts_review.py`'s `test_canonical_follows_a_branched_re_export[type_checking]` (both were the first binding, the import; both are now the placeholder).

**Verify:** gold. `uv run pytest tests/test_type_checking_runtime_anchor.py tests/test_reexport_relative_collapse.py tests/unit/mcp/operations/test_stubs.py` passes. The first file covers:

- the type-only lines: both guard orders, `typing.TYPE_CHECKING`, an aliased guard, and a plain `if` that is not one;
- the runtime def winning in `resolve`, `resolve_at` on the declaration, `inspect` (kind, signature, docstring, location, the runtime annotations), class and module `members`, and `outline`;
- a declaration alone, which is unchanged;
- `prefer_runtime_bindings`' unchanged cases (all type-only, several files, an unparseable file), and `shadowed_by_type_only` true only for a def beside a declaration;
- the `if TYPE_CHECKING:` import beside an `else:` placeholder anchoring on the placeholder.

`test_stubs.py`'s `test_property_no_signature` checks that a `@property` still has no signature.
