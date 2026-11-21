---
date: "2026-11-22"
title: "A definition pyeye's parser can't read is never answered with phantoms, and is disclosed as unreadable_definitions (#1074)"
issues: [1074, 1075, 1006, 1065, 1049, 703, 599]
anchors: ["pyeye._parse_gaps", "pyeye.file_artifact_cache.FileArtifactCache.has_syntax_errors", "pyeye.resolver._path_gap", "pyeye.resolver._misplaced", "pyeye.mcp.operations.edges.resolve_members", "tests/unit/mcp/operations/test_parse_gaps.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — A definition pyeye's parser can't read is never answered with phantoms, and is disclosed as unreadable_definitions (#1074)

**Friction:** found in the Scrapy exploration trial. `scrapy.utils.asyncio.call_later(delay, func, *args: *_Ts)` uses PEP 646 syntax. Jedi's parser, parso 0.8.7 (the latest release), doesn't support it. It error-recovered by dropping the `def` and leaving the body's statements at module level. So `expand(module, "members")` listed `loop`, `asyncio` and `context` as module members, and `resolve`/`inspect` couldn't find `call_later`. Those are confident wrong answers plus a silent omission.

A survey ran across Python 3.11 to 3.14, with one fixture per syntax.

- **Damaging cases:** all in a definition's HEADER: PEP 646 `*args: *Ts`, a `tuple[*Ts]` annotation, a `Generic[*Ts]` base and a module-level `x: tuple[*Ts]`; PEP 695 `[*Ts, **P]` and `type Pair[T] = ...`.
- **Harmless cases** (error nodes, nothing lost): newer syntax in a BODY: PEP 701 f-strings, `match`, `except*`, parenthesised `with`, PEP 758, t-strings, `a[*b]`, and `Callable[[*Ts], object]`. Callees in them were all found.
- **The Scrapy `__getattr__` "omission"** was `members` truncating at 200 of 230, not a gap.

**Decision:** the maintainer's rulings via coordinator-3 and designer, 2026-11-22.

- **Detect, cheaply.** `file_artifact_cache.has_syntax_errors(script)` is Jedi's public `Script.get_syntax_errors()`, cached per Script. The resolver asks `file_has_syntax_errors(path, project)`, which is cached per file by its stat version. One `stat` per hit is what kept the check off the hot path. 44 of django's 2922 files have parso errors.
- **Guard: `ast` decides what a scope binds** (`pyeye._parse_gaps`, a lower layer, on `_bindings.binding_sites`, #1049). Only in a file with errors:
  - `members` (module and class) keeps a Jedi name only if `ast` binds it in that scope at that line;
  - `resolve_handle` answers not-found for a name in the wrong scope (`_misplaced`), and for a path whose module doesn't bind it (`_path_gap`, run on a miss or an alias hop, such as an `import asyncio` in a dropped body that Jedi follows to the stdlib).
- **Honest detail.** A definition only `ast` sees answers not-found in `resolve`, `inspect`, `expand` and `outline` with "<file>:<line> uses syntax pyeye's parser can't read (parso X); Read the file". It reuses the `unresolved` reason with a new `NotFound.parse_gap` flag, which `honest_detail` passes through.
- **Disclosure** (the maintainer's ruling via designer, a contract addition, named for pyeye's PARSER LIMIT rather than broken code):
  - `unreadable_definitions: [{name, kind, line, reason: "parser_unsupported_syntax"}]`, sorted by line, on `expand(..., "members")` (module and class) and on each `outline` node whose members were measured;
  - `inspect`'s `unreadable_definition_count`, present exactly when `edge_counts.members` is, so that count is never a silent undercount (#599);
  - `trace`'s `unreadable_definition_counts: {handle: count}`, present when `members` was walked, as #1006's `handleless_subclass_counts` is.
  - Absence vs zero: `[]`/`0` means measured and none lost, and the key is absent only where members weren't measured. Entries carry no file (the container is one file), so #717's respelling rule doesn't apply. `kind` is `function`, `method`, `class` or `variable`.
  - The linter enforces it: E.11, O.7, T.13 and B.5.
- **Not here:** #1075, AST-built anchors so a lost definition can still be resolved, inspected and outlined, at low priority. Nothing is filed upstream (the outside-repo rule).

**Cost, measured on django `cd385e6b8c`:** warm, alternating, over 190 resolves that hit, within noise (6.53 vs 6.43–6.67 ms each). Over 50 that miss, about +1 ms each, which is the module lookup a miss needs.

**Anchor:** `pyeye._parse_gaps.bound_in` / `scope_path_at` / `binding_line` / `unreadable_definitions`; `pyeye.file_artifact_cache.FileArtifactCache.has_syntax_errors` / `file_has_syntax_errors`; `pyeye.resolver.NotFound.parse_gap` / `_path_gap` / `_misplaced`; `pyeye.mcp.operations.edges.resolve_members` / `unreadable_definition_count`; #1074, #1075.

**Applies-to:** `pyeye._parse_gaps.unreadable_definitions`, `pyeye.file_artifact_cache.FileArtifactCache.has_syntax_errors`, `pyeye.file_artifact_cache.FileArtifactCache.file_has_syntax_errors`, `pyeye.resolver.resolve_handle`, `pyeye.resolver._path_gap`, `pyeye.resolver._misplaced`, `pyeye.mcp.operations.edges.resolve_members`, `pyeye.mcp.operations.edges._module_member_names`, `pyeye.mcp.operations.edges._class_members`, `pyeye.mcp.operations.edges.unreadable_definition_count`, `pyeye.mcp.operations.expand.expand_resolved`, `pyeye.mcp.operations.outline._child_adjacents`, `pyeye.mcp.operations.inspect.inspect`, `pyeye.mcp.operations.trace.trace`.

**Verify:** gold. `uv run pytest tests/unit/mcp/operations/test_parse_gaps.py tests/conformance` passes. It checks:

- for each damaging syntax (skipped on Pythons without it), `members` and `outline` list no phantoms, and list the lost definition in `unreadable_definitions`;
- `inspect` counts it;
- `resolve`/`inspect`/`expand`/`outline` of it answer not-found naming its line and the parser;
- each phantom doesn't resolve;
- each harmless body syntax loses nothing;
- a clean file measures `[]`/`0`;
- the keys are absent where members weren't measured;
- `trace` counts per node;
- the linter rejects every misplaced or malformed form (E.11, O.7, T.13, B.5).
