Caching Strategy
================

pyeye caches parsed files and per-project indexes so repeated questions stay
fast, and drops them when the source changes. (The ``GranularCache``,
``ProjectCache``, ``DependencyTracker`` and connection-pool layers described in
earlier versions of this page were never wired in and were removed in #628.)

Cache Architecture
------------------

**Analyzer cache**
  ``ProjectManager`` keeps one ``JediAnalyzer`` per project root, LRU-bounded by
  ``PYEYE_MAX_PROJECTS`` (default 10).

**Scoped cache**
  Each analyzer's ``ScopedCache`` keeps scope file lists and lookup results,
  separately per scope (``main``, ``all``, ``namespace:<name>``, ...). Entries
  live ``PYEYE_CACHE_TTL`` seconds (default 300).

**Parsed-file cache**
  ``file_artifact_cache`` keeps parsed ASTs and Jedi scripts process-wide, in an
  LRU of ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`` entries (default 2000). This is the
  main memory lever.

**Name index and TypeRef cache**
  The whole-project name index (``project_graph``) and the TypeRef cache are
  process-wide and keyed on the project's effective layout, so a project with a
  different package configuration never reads another layout's entries.

Invalidation
------------

**File changes**: one watcher per watched root (the project, its packages,
namespaces and standalone directories). A debounced batch of changes drops each
changed file's parsed artifacts, and, for every project that reads from that
root, its name index, TypeRef cache and scoped cache. Projects that don't read
from the root keep their caches.

**Configuration changes**: ``configure_packages`` drops the project's cached
analyzer and its process-wide caches, so the next request rebuilds them.

**Time**: scoped-cache entries expire after ``PYEYE_CACHE_TTL`` seconds even
without a file change.

File System Watching
--------------------

Watchdog Integration
~~~~~~~~~~~~~~~~~~~

The system uses the ``watchdog`` library for efficient file system monitoring:

.. code-block:: python

   class CodebaseWatcher:
       def __init__(self, project_path: str, on_change_callback=None):
           self.observer = Observer()
           self.on_change_callback = on_change_callback

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

Cache Performance
-----------------

Hit Rate Optimization
~~~~~~~~~~~~~~~~~~~~

**Preloading**: Common operations are preloaded during project initialization

**Predictive Caching**: Analyze usage patterns to cache likely-needed results

**Cache Warming**: Background processes warm caches for recently active projects

Memory Management
~~~~~~~~~~~~~~~~

**Size Limits**: Configurable memory limits with LRU eviction

**Compression**: Large result sets are compressed using zlib

**Weak References**: Use weak references where possible to allow garbage collection

**Memory Monitoring**: Track cache memory usage with alerts for excessive growth

Persistence Options
------------------

In-Memory (Default)
~~~~~~~~~~~~~~~~~~

Fast access but lost on restart. Suitable for development and single-user scenarios.

**Pros**: Fastest access times, no I/O overhead
**Cons**: Lost on restart, memory usage scales with cache size

File-Based Persistence
~~~~~~~~~~~~~~~~~~~~~

Cache entries persisted to disk for durability across restarts.

**Location**: ``~/.cache/pyeye/`` or configurable directory
**Format**: JSON or pickle serialization with compression
**Cleanup**: Automatic cleanup of expired entries on startup

Redis Backend (Future)
~~~~~~~~~~~~~~~~~~~~~~

Distributed caching for multi-user or multi-instance deployments.

**Benefits**: Shared cache across instances, persistence, advanced eviction
**Configuration**: Redis connection parameters in configuration file
**Scaling**: Handles large teams with shared codebases

Cache Configuration
-------------------

Configuration Options
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: json

   {
     "cache": {
       "enabled": true,
       "ttl_seconds": 300,
       "max_entries": 10000,
       "max_memory_mb": 500,
       "persistence": "memory",
       "invalidation": {
         "file_watching": true,
         "dependency_tracking": true,
         "smart_invalidation": true
       }
     }
   }

Per-Operation Settings
~~~~~~~~~~~~~~~~~~~~~

Different operations can have different cache settings:

.. code-block:: json

   {
     "cache_settings": {
       "find_symbol": {"ttl": 600, "priority": "high"},
       "find_references": {"ttl": 300, "priority": "medium"},
       "get_type_info": {"ttl": 900, "priority": "high"},
       "analyze_dependencies": {"ttl": 1800, "priority": "low"}
     }
   }

Environment Overrides
~~~~~~~~~~~~~~~~~~~~~

Environment variables can override configuration:

.. code-block:: bash

   export PYEYE_CACHE_TTL=600                    # seconds (default 300)
   export PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=4000  # parsed files kept (default 2000)

There is no memory-size cap; ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`` is the memory
lever (roughly 200 KB per cached file).

Cache Monitoring
---------------

Metrics Collection
~~~~~~~~~~~~~~~~~

The cache system provides detailed metrics:

.. code-block:: python

   cache_metrics = {
       "hit_rate": 0.85,
       "miss_rate": 0.15,
       "total_requests": 1000,
       "cache_size": 5000,
       "memory_usage_mb": 150,
       "invalidations": 25,
       "average_response_time_ms": 15
   }

Performance Dashboard
~~~~~~~~~~~~~~~~~~~~

Built-in performance monitoring:

* Hit/miss ratios by operation type
* Memory usage trends
* Invalidation frequency
* Response time distributions
* Cache efficiency scores

Debugging Tools
~~~~~~~~~~~~~~

Development and debugging utilities:

.. code-block:: python

   # Cache inspection
   cache.get_stats()
   cache.list_entries(project_path="/path/to/project")
   cache.explain_invalidation(cache_key="...")

   # Cache manipulation
   cache.clear_project("/path/to/project")
   cache.force_refresh(cache_key="...")
   cache.disable_for_testing()

Best Practices
--------------

Development Guidelines
~~~~~~~~~~~~~~~~~~~~~

**Cache Key Design**: Use consistent, hierarchical cache keys that include
all relevant parameters

**Dependency Tracking**: Always record file dependencies when generating
cache entries

**Graceful Degradation**: Handle cache failures gracefully by falling back
to fresh analysis

**Testing**: Test both cache hits and misses in your test suite

Operational Guidelines
~~~~~~~~~~~~~~~~~~~~~

**Monitor Hit Rates**: Aim for >80% cache hit rate in normal operations

**Memory Monitoring**: Set up alerts for excessive cache memory usage

**Regular Cleanup**: Clean up expired entries and monitor cache growth

**Configuration Tuning**: Adjust TTL and size limits based on usage patterns

Common Pitfalls
~~~~~~~~~~~~~~~

**Over-Caching**: Don't cache operations that are already fast

**Under-Invalidation**: Ensure all relevant dependencies are tracked

**Memory Leaks**: Use weak references and proper cleanup

**Stale Data**: Balance TTL with data freshness requirements

Future Enhancements
-------------------

Planned Improvements
~~~~~~~~~~~~~~~~~~~

**Distributed Locking**: Coordinate cache updates across multiple instances

**Cache Replication**: Replicate hot cache entries across instances

**Machine Learning**: Use ML to predict optimal cache parameters

**Advanced Compression**: More efficient serialization for large results

**Query Planning**: Optimize cache usage based on query patterns
