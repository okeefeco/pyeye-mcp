# Caching Strategy

pyeye caches parsed files and per-project indexes so repeated questions stay
fast, and drops them when the source changes. Every cache lives in the server
process; there is no persistent or shared backend. Correctness never depends on
a cache's size: the caps below trade memory for latency only.

## The caches

**Analyzer cache.** `ProjectManager` keeps one `JediAnalyzer` per project root,
LRU-bounded by `PYEYE_MAX_PROJECTS` (default <!-- fact:begin env.PYEYE_MAX_PROJECTS.default -->10<!-- fact:end -->).

**Scoped cache.** Each analyzer's `ScopedCache` keeps the list of files each
scope covers, separately per scope (`main`, `all`, `namespace:<name>`, ...).
Entries live `PYEYE_CACHE_TTL` seconds (default <!-- fact:begin env.PYEYE_CACHE_TTL.default -->300<!-- fact:end -->).
It also holds the `imports` edge's resolutions of targets outside the project,
in an LRU of `PYEYE_RESOLVE_CACHE_MAX_ENTRIES` entries (#925). A miss or a
project target is resolved every time, and a watcher event clears the lot, so a
new project module that shadows a stdlib name is seen.

**Parsed-file cache.** `pyeye.file_artifact_cache` keeps parsed ASTs and Jedi
scripts process-wide, in one LRU of `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` entries
(default <!-- fact:begin env.PYEYE_ARTIFACT_CACHE_MAX_ENTRIES.default -->2000<!-- fact:end -->), with Jedi scripts further capped by
`PYEYE_SCRIPT_CACHE_MAX_ENTRIES`. Entries are re-checked by file mtime and size
on every read. Each cached Jedi script keeps alive every module it inferred, so
the script cap, not the parso cap, is what bounds the memory of Jedi's parse
trees. Its stats count evictions by cause (#401): `cap_evictions` are entries
dropped to stay under the caps, so a steadily rising count means the caps are
too small for the working set, while `stale_evictions` are entries dropped
because their file changed, which is normal on a repo being edited.
`evictions` is their total. `get_performance_metrics` reports all three.

**parso's parse cache.** Bounded by an LRU of `PYEYE_PARSO_CACHE_MAX_ENTRIES`
entries (`pyeye._parso_cache`, #713). Evicting an entry is harmless (see
[Resolution and Determinism](resolution.md)).

**Project graphs, TypeRef cache and re-export index.** The whole-project name
and member indexes and each project's resolved class graph and reverse import
graph (`pyeye.analyzers.project_graph`, #397, backing `subclasses` and
`imported_by`), the TypeRef cache and the re-export index
(`pyeye.canonicalization`) are process-wide and held per project. The indexes
and graphs are keyed on the project's effective layout, so a project with a
different package configuration never reads another layout's entries (#618).
The TypeRef cache is keyed per annotation site and project root, not on the
layout (#620), so a layout change has to clear it explicitly. The indexes and
graphs live outside the parsed-file LRU and are rebuilt, never evicted, so an
eviction can never make a definition disappear (#457).

## Invalidation

**File changes.** `ProjectManager` runs one `CodebaseWatcher` (watchdog) per
watched root: the project, its packages, namespaces and standalone directories.
A root shared by several projects has one watcher. The watcher records `.py`
files and directories that are created, modified, deleted or moved, skips
anything under ignored directories below the root (`.git`, `__pycache__`,
`.venv`, `build`, `dist`, `node_modules` and the like), and delivers a debounced
batch (`PYEYE_WATCHER_DEBOUNCE`, default <!-- fact:begin env.PYEYE_WATCHER_DEBOUNCE.default -->0.5<!-- fact:end --> s) of every changed path (#617).

For each batch, every changed file's parsed artifacts are dropped, then, for
every project that reads from that root, its scoped cache, name and member
indexes, class and import graphs, TypeRef cache and re-export index. Inputs are dropped before the generations that guard
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
