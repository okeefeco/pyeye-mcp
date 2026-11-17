# Caching Strategy

pyeye caches parsed files and per-project indexes so repeated questions stay
fast, and drops them when the source changes. Every cache lives in the server
process; there is no persistent or shared backend. Correctness never depends on
a cache's size: the caps below trade memory for latency only.

## The caches

**Analyzer cache.** `ProjectManager` keeps one `JediAnalyzer` per project root,
LRU-bounded by `PYEYE_MAX_PROJECTS` (default 10).

**Scoped cache.** Each analyzer's `ScopedCache` keeps scope file lists and
lookup results, separately per scope (`main`, `all`, `namespace:<name>`, ...).
Entries live `PYEYE_CACHE_TTL` seconds (default 300).

**Parsed-file cache.** `pyeye.file_artifact_cache` keeps parsed ASTs and Jedi
scripts process-wide, in one LRU of `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` entries
(default 2000), with Jedi scripts further capped by
`PYEYE_SCRIPT_CACHE_MAX_ENTRIES`. Entries are re-checked by file mtime and size
on every read. This is the main memory lever.

**parso's parse cache.** Bounded by an LRU of `PYEYE_PARSO_CACHE_MAX_ENTRIES`
entries (`pyeye._parso_cache`, #713). Evicting an entry is harmless (see
[Resolution and Determinism](resolution.md)).

**Name index, TypeRef cache and re-export index.** The whole-project name index
(`pyeye.analyzers.project_graph`), the TypeRef cache and the re-export index
(`pyeye.canonicalization`) are process-wide and held per project. The name index
is keyed on the project's effective layout, so a project with a different
package configuration never reads another layout's entries (#618); the TypeRef
cache is keyed on the project root alone (#620). The name index lives outside
the parsed-file LRU, so an eviction can never make a definition disappear
(#457).

## Invalidation

**File changes.** `ProjectManager` runs one `CodebaseWatcher` (watchdog) per
watched root: the project, its packages, namespaces and standalone directories.
A root shared by several projects has one watcher. The watcher records `.py`
files and directories that are created, modified, deleted or moved, skips
anything under ignored directories below the root (`.git`, `__pycache__`,
`.venv`, `build`, `dist`, `node_modules` and the like), and delivers a debounced
batch (`PYEYE_WATCHER_DEBOUNCE`, default <!-- fact:begin env.PYEYE_WATCHER_DEBOUNCE.default -->0.5<!-- fact:end --> s) of every changed path (#617).

For each batch, every changed file's parsed artifacts are dropped, then, for
every project that reads from that root, its scoped cache, name index, TypeRef
cache and re-export index. Inputs are dropped before the generations that guard
the index builds move, so a build can't cache a stale result under a new
generation (#817). Projects that don't read from the root keep their caches.

A change made while a watcher is still starting is not delivered by the OS, so
catch-up sweeps shortly after start re-stat the root's `.py` files and
invalidate those changed since (#738). If a watcher can't start (for example at
the OS inotify limit), analysis still works and a warning says edits under that
root won't refresh the caches.

**Configuration changes.** `configure_packages` drops the project's cached
analyzer, its plugin state and its process-wide caches, so the next request
rebuilds them.

**Time.** Scoped-cache entries expire after `PYEYE_CACHE_TTL` seconds even
without a file change.

## Configuration

Caches are tuned only through the environment variables above, set on the MCP
client's server entry (the README's "Performance Settings" lists them all). A
`cache` section in `.pyeye.json`, `[tool.pyeye]` or the global config has no
effect: pyeye never read it, and it logs a warning when it is present (#581).
