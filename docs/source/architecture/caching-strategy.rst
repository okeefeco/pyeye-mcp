Caching Strategy
================

The caching system is a critical component that enables high-performance code analysis
by intelligently caching results and invalidating them when source code changes.
The system uses multiple layers of caching with sophisticated invalidation strategies.

Cache Architecture
------------------

Multi-Level Caching
~~~~~~~~~~~~~~~~~~~

**GranularCache (L1)**
  File-level caching with dependency tracking. Stores analysis results with
  metadata about which files contributed to each result.

**ProjectCache (L2)**
  Project-level caching for expensive operations like full project indexing.
  Uses LRU eviction with configurable size limits.

**Connection Pool Cache (L3)**
  Caches Jedi Project instances to avoid expensive re-initialization.
  Maintains connection pools with automatic cleanup of stale connections.

Cache Keys and Scoping
~~~~~~~~~~~~~~~~~~~~~

Cache keys are hierarchical and include:

* **Project Path**: Identifies which project the cache entry belongs to
* **Operation Type**: Type of analysis (find_symbol, find_references, etc.)
* **Parameters**: Normalized parameters (symbol name, file path, etc.)
* **Scope**: Analysis scope (main, all, specific namespace)

Example cache key structure:

.. code-block:: text

   /path/to/project:find_symbol:MyClass:main:1234567890

Cache Entry Format
~~~~~~~~~~~~~~~~~~

Each cache entry contains:

.. code-block:: python

   {
       "result": [...],  # Analysis results
       "timestamp": 1234567890,  # Creation timestamp
       "dependencies": [  # Files that contributed to this result
           "/path/to/file1.py",
           "/path/to/file2.py"
       ],
       "scope": "main",  # Analysis scope
       "ttl": 300,  # Time-to-live in seconds
       "metadata": {  # Additional metadata
           "version": "0.1.0",
           "analyzer": "jedi"
       }
   }

Invalidation Strategies
----------------------

File-Based Invalidation
~~~~~~~~~~~~~~~~~~~~~~

**File Modification**: When a file changes, all cache entries that depend on
that file are invalidated immediately.

**Dependency Tracking**: The system tracks which files contribute to each
cached result, enabling precise invalidation.

**Batch Invalidation**: Multiple file changes trigger batch invalidation
to improve performance during large refactoring operations.

Smart Invalidation
~~~~~~~~~~~~~~~~~

**Symbol-Level**: Changes to specific symbols only invalidate related cache entries
rather than the entire project cache.

**Scope-Aware**: Cache invalidation respects analysis scopes - changes in one
namespace don't invalidate cache entries for other namespaces.

**Dependency Graph**: Uses import dependency graphs to propagate invalidation
through related modules.

Time-Based Invalidation
~~~~~~~~~~~~~~~~~~~~~~

**TTL (Time-To-Live)**: Default 5-minute TTL for all cache entries with
configurable per-operation overrides.

**Adaptive TTL**: Frequently accessed entries get longer TTL, rarely accessed
entries expire faster.

**Background Refresh**: Popular entries are refreshed in background before
expiration to maintain low latency.

File System Watching
--------------------

Watchdog Integration
~~~~~~~~~~~~~~~~~~~

The system uses the ``watchdog`` library for efficient file system monitoring:

.. code-block:: python

   class CodebaseWatcher:
       def __init__(self, project_path: Path, cache: GranularCache):
           self.observer = Observer()
           self.cache = cache

       def start(self):
           self.observer.schedule(
               FileSystemEventHandler(),
               str(self.project_path),
               recursive=True
           )
           self.observer.start()

Event Filtering
~~~~~~~~~~~~~~

**File Type Filtering**: Only monitor Python files and configuration files

**Directory Exclusions**: Skip common directories like ``.git``, ``__pycache__``,
``.venv`` to reduce noise

**Debouncing**: Group multiple rapid changes into single invalidation events

**Pattern Matching**: Use glob patterns to determine which files are relevant

Cache Configuration
-------------------

Caches are tuned only through the environment variables below. A ``cache``
section in ``.pyeye.json``, ``[tool.pyeye.cache]`` or the global config is
deprecated and has no effect (#581): pyeye never read it, and now logs a warning
when it is present. There is no persistent or shared cache backend; every cache
lives in the server process.

Environment Overrides
~~~~~~~~~~~~~~~~~~~~~

Set these on the MCP client's server entry:

.. code-block:: bash

   export PYEYE_CACHE_TTL=600                    # seconds (default 300)
   export PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=4000  # parsed files kept (default 2000)

There is no memory-size cap; ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`` is the memory
lever (roughly 200 KB per cached file).
