# Lookup Performance Cache — Design Spec

## Problem

On large codebases the unified `lookup` MCP tool takes dozens of seconds per call. Investigation shows the lookup pipeline rebuilds expensive state on every invocation and runs redundant project-wide Jedi searches.

Concrete fan-out per call (function lookup):

- `ProjectManager.get_analyzer()` constructs a fresh `JediAnalyzer` and a fresh `jedi.Project` every call (`src/pyeye/project_manager.py:248`, `src/pyeye/analyzers/jedi_analyzer.py:123`/`128`). The connection pool exists but is only wired into `get_project`, not `get_analyzer`, so it does not help the lookup path.
- `_search_all_scopes` (project-wide `project.search`) runs **twice** per function lookup — once in `find_symbol`, once again inside `get_call_hierarchy` (`src/pyeye/analyzers/jedi_analyzer.py:1354`).
- `script.get_references` (project-wide reference search, the most expensive Jedi operation) runs **twice** — once in `get_call_hierarchy` and again in `find_references` from the function-result builder (`src/pyeye/mcp/lookup_builders.py:308` and `:339`).
- The same source file is read from disk and re-parsed into a fresh `jedi.Script` **3–4 times** per call across `_module_ref_for_file`, `_make_script`/`_get_jedi_names`, `get_call_hierarchy`, and `find_references`.
- For class lookups, `find_subclasses` AST-parses every Python file in scope every call (`src/pyeye/analyzers/jedi_analyzer.py:2914-2937`); only the file list is cached, not the parses.

The codebase has the necessary infrastructure (`GranularCache` with watcher-driven invalidation in `src/pyeye/cache.py`; `CodebaseWatcher` already running) but **none of it is wired into the lookup pipeline**. `GranularCache` has zero callers in `lookup.py`, `lookup_builders.py`, or `mcp/server.py`.

## Goals

- Reduce typical `lookup` latency on a multi-thousand-file codebase from tens of seconds to low single-digit seconds (cold) and sub-second (warm).
- Make the daemon's long-running nature pay off: warm caches should survive across calls and across sessions for the lifetime of the server process.
- Guarantee read-after-write consistency for the agent's own edits — the next lookup after an `Edit`/`Write`/`MultiEdit` must see the change.
- Keep the MCP tool surface unchanged: caching is an implementation detail, not a parameter on every call.

## Non-goals

- Per-call freshness flags on the MCP tool surface. Rejected because LLM agents cargo-cult `force=True`-style flags and would erode the cache hit rate. Caching must be correct without caller participation.
- Replacing Jedi or rewriting the analyzer. The work is purely additive: wrap existing primitives in caches and remove redundant calls.
- Multi-process cache sharing across Claude instances. Each Claude Code instance gets its own MCP server (per project convention); inter-instance consistency continues to ride on the file watcher.

## Design overview: layered cache

Four cache layers, each with its own key, invalidation source, and miss cost:

| Layer | Key | Invalidation | Miss cost |
|---|---|---|---|
| **Response** — full `lookup()` JSON | `(project, identifier-or-coords, limit)` | Hook + watcher: any file the response references is mutated → drop entry | Full builder fan-out (seconds) |
| **Primitive** — `find_references`, `find_subclasses`, `find_symbol`, `get_call_hierarchy`, `get_module_info` | Per-method natural key (e.g. `(file, line, col)` for references) | Hook + watcher via `GranularCache.invalidate_file` | One Jedi project-wide search (seconds) |
| **File artifact** — `(source_text, ast.Module, jedi.Script)` per file | `(path, mtime)` | mtime mismatch on hit; hook/watcher pre-evicts | One disk read + parse (~10–100ms) |
| **Analyzer/project** — `JediAnalyzer` + its `jedi.Project` | resolved `project_path` | Config change only | `jedi.Project` construction + Jedi internal warm-up |

Higher layers shortcut the lower ones; lower layers make first-time misses cheap.

**The file artifact layer is the most leveraged** — every other layer's miss path reads files. Today, `_make_script`, `_get_jedi_names`, `_module_ref_for_file`, `find_references`, `find_subclasses`, `get_call_hierarchy`, and `get_module_info` each issue independent file reads. With this layer they share.

## Invalidation strategy

Three mechanisms, in order of authority:

1. **Plugin hook on `Edit`/`Write`/`MultiEdit`** — primary. Because pyeye-mcp runs as a Claude Code plugin and AI is the dominant editor, the agent's own writes are the dominant change source. A `PostToolUse` hook calls a new `invalidate(file)` MCP tool on the running server, evicting cache entries before the next lookup can hit. This gives a hard read-after-write guarantee without per-call coordination.
2. **`CodebaseWatcher` (existing)** — secondary. Catches what the hook can't see: `Bash`-driven edits (sed, formatters, codegen, `git checkout`, `git pull`), edits from sibling Claude instances in other worktrees, external tooling. Already invalidates `GranularCache` entries via `invalidate_file` when wired.
3. **mtime-gate on root file at primitive cache hit** — tertiary, belt-and-braces. Single `stat()` (~5µs) on the entry's keying file when serving a hit. Catches the rare case where both hook and watcher miss. Does **not** apply to project-wide derived results (those rely on the watcher) — only to entries keyed on a single file.

TTL is a backstop, not a primary mechanism. Default 1 hour; tunable via `PYEYE_CACHE_TTL`.

## Stale-tolerance posture

Stale-tolerant for external edits, hook-fresh for self-edits. AI-primary framing means the dominant edit pathway is observable, so this collapses to: **the agent always sees its own writes, may see external changes up to the watcher debounce window** (default 0.5s).

## Memory model

Long-running daemon means unbounded growth is a real risk on big codebases. Each cache layer has a budget:

- File artifact source cache: cap by **bytes** (`PYEYE_FILE_CACHE_MAX_BYTES`, default ~100MB). LRU.
- File artifact AST/Script cache: cap by **count** (`PYEYE_AST_CACHE_MAX_ENTRIES`, default ~500). LRU. (parso trees are large.)
- Primitive caches: cap by **count** + TTL + watcher invalidation (existing `GranularCache` semantics).
- Response cache: cap by **count** + TTL + invalidation.

Eviction of a file artifact entry must cascade to drop primitive cache entries that depend on that file (the existing `GranularCache.invalidate_file` is the right call).

## API surface changes

- **No** new parameters on existing tools. Caching stays invisible to callers.
- **One new MCP tool: `invalidate(file: str | None = None, project_path: str = ".")`.** Drops cache entries touching `file` (or all entries for the project when `file is None`). Parameter name `project_path` matches the convention used by every other pyeye tool. Used by the plugin hook; also available to agents that did out-of-band edits via Bash.
- New env-var config knobs in `src/pyeye/settings.py` (see Config below).
- Optional `cache_age_ms` field on responses gated by `PYEYE_CACHE_DEBUG=1`. Off by default; enables agent self-introspection if confused-decision incidents occur in real use.

## Config knobs (additive)

| Env var | Default | Purpose |
|---|---|---|
| `PYEYE_CACHE_TTL` | existing 300s | Bump default to 3600s (1 hour). Backstop only. |
| `PYEYE_LOOKUP_CACHE_TTL` | inherits `CACHE_TTL` | Separate knob to disable response cache without losing primitive cache wins. |
| `PYEYE_FILE_CACHE_MAX_BYTES` | 100MB | Source text cache size cap. |
| `PYEYE_AST_CACHE_MAX_ENTRIES` | 500 | Parsed-AST/`jedi.Script` LRU cap. |
| `PYEYE_PRIMITIVE_CACHE_MAX_ENTRIES` | 1000 | Per-method primitive cache LRU cap. |
| `PYEYE_RESPONSE_CACHE_MAX_ENTRIES` | 500 | `lookup()` response cache LRU cap. |
| `PYEYE_PRELOAD_PATHS` | unset | Comma-separated globs to AST-parse and Jedi-prime at startup. |
| `PYEYE_DISABLE_CACHES` | false | Escape hatch — bypasses all caches for debugging. |
| `PYEYE_CACHE_DEBUG` | false | Adds `cache_age_ms` to responses. |

## Risks and open questions

- **WSL watcher reliability.** Watchdog has known reliability issues on WSL2 (the project's primary platform per environment note). If the watcher silently misses events, stale data persists indefinitely and the hook becomes load-bearing for *all* edit detection. Mitigation: a startup health probe (write temp file, assert event fires within ~2s; log loud warning + tighten TTL backstop on failure).
- **Hook coverage gaps.** `Bash` edits, sub-agent edits in other worktrees, formatters in pre-commit hooks. Watcher catches these but adds latency proportional to debounce. Acceptable for the AI-coding use case.
- **Multi-agent edit coordination.** Per project convention, each Claude Code instance has its own MCP server. Cross-instance edits flow only via the watcher in the receiving instance. Same risk as WSL above; same mitigation.
- **Cache thrashing during burst-edit refactors.** AI-driven multi-file refactors invalidate frequently. Acceptable: caches don't help during edit bursts but resume helping when the agent shifts back to querying. Bounded by edit count, not query count.
- **Memory caps interact with deep `find_subclasses` walks.** A class lookup may need many file ASTs cached; a small `AST_CACHE_MAX_ENTRIES` causes thrash. Defaults assume a typical Python project of 1k-10k files; very large monorepos may need tuning.
- **Hook implementation lives in `.claude/hooks/`.** Coupling between the plugin hooks directory and the MCP server's `invalidate` tool needs documentation — the hook calls into pyeye-mcp via the standard MCP transport, not via in-process import.

## Content-bucket taxonomy

The Task 1.5 audit and inline `TODO(api-redesign)` comments classify each data read into one of five buckets. Future tasks (Phases 2–3) and the API redesign use the same labels so reviewers can grep for a bucket and get a consistent picture.

| Bucket | Label | Definition |
|--------|-------|------------|
| 1 | **Analysis input** | Structural data (AST, `jedi.Script`) consumed to produce semantic facts. These are the payloads the caches are designed to supply; reads here should come from `file_artifact_cache.get_ast()` / `get_script()`, not from disk. |
| 2 | **Derived fact** | A value computed from bucket-1 inputs and stored as a result (e.g. resolved type ref, call-hierarchy edge). Lives in the primitive or response cache once computed. |
| 3 | **Metadata** | Lightweight file-system facts (path, mtime, existence) that are cheap to re-read and do not need caching. |
| 4 | **Bridge read** | A disk or source-text read that exists only because a callee's signature still requires raw source text rather than a pre-parsed artifact. Marked with `TODO(api-redesign)` at the call site. Should be eliminated when the callee is reshaped to accept `ast.Module` or `jedi.Script` directly. |
| 5 | **Line-counting metric** | A read whose sole purpose is to measure file size in lines (e.g. for truncation or display). Not a semantic read; tolerable outside the cache. |

Buckets 1 and 4 are the audit's primary focus: bucket 1 reads are the cache-hit target; bucket 4 reads are the known technical debt to eliminate in later phases.

## Out of scope (future work)

- Request coalescing (`asyncio.Future` sharing for concurrent identical lookups). Worth doing later but not load-bearing for the latency wins targeted here.
- Cross-process cache sharing.
- Persisting caches across server restarts.
- Smart predictive prefetch.
