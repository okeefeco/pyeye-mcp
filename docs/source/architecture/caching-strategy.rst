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
