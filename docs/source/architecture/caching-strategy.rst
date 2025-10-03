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

   export PYEYE_CACHE_TTL=600
   export PYEYE_CACHE_MAX_ENTRIES=20000
   export PYEYE_CACHE_MEMORY_MB=1000

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
