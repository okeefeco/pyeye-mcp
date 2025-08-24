Architecture Overview
====================

The Python Code Intelligence MCP Server is built with a modular architecture that emphasizes
performance, extensibility, and reliability. This document provides a high-level overview
of the system components and their interactions.

System Components
-----------------

Core Server Layer
~~~~~~~~~~~~~~~~~

**FastMCP Server**
  The foundation built on the FastMCP framework, providing the Model Context Protocol
  interface for AI assistants. Handles request routing, validation, and response formatting.

**Tool Registry**
  Dynamic registration system for MCP tools, including both core navigation tools and
  framework-specific tools from plugins.

Analysis Layer
~~~~~~~~~~~~~~

**Project Manager**
  Central coordinator that manages multiple Python projects simultaneously with LRU caching.
  Handles project lifecycle, resource cleanup, and cross-project operations.

**Jedi Analyzer**
  Wrapper around the Jedi library providing semantic analysis capabilities. Handles
  symbol resolution, type inference, and code navigation with namespace awareness.

**Plugin System**
  Extensible framework for adding domain-specific intelligence. Automatically detects
  and activates plugins based on project characteristics.

Caching Layer
~~~~~~~~~~~~~

**GranularCache**
  Intelligent caching system with file-level invalidation and dependency tracking.
  Provides 5-minute TTL with smart invalidation based on file modifications.

**CodebaseWatcher**
  File system monitoring using the watchdog library to automatically invalidate
  cached results when source files change.

Data Flow
---------

Request Processing
~~~~~~~~~~~~~~~~~~

1. **Request Validation**: All MCP requests are validated for security and correctness
2. **Project Resolution**: Determine which project(s) the request applies to
3. **Cache Check**: Check if results are available in cache and still valid
4. **Analysis Execution**: Perform semantic analysis using Jedi if cache miss
5. **Plugin Enhancement**: Apply framework-specific plugins to enhance results
6. **Response Formatting**: Format results according to MCP specification
7. **Cache Storage**: Store results for future requests

Cross-Project Analysis
~~~~~~~~~~~~~~~~~~~~~~

For operations spanning multiple projects:

1. **Scope Resolution**: Determine which projects are in scope
2. **Parallel Analysis**: Execute analysis across projects concurrently
3. **Result Aggregation**: Combine and deduplicate results
4. **Dependency Resolution**: Handle cross-project dependencies and imports

Configuration System
--------------------

The server supports multiple configuration sources with clear precedence:

1. **Runtime Configuration**: Direct API calls to configure_packages
2. **Project Configuration**: .pycodemcp.json in project root
3. **pyproject.toml**: [tool.pycodemcp] section
4. **Environment Variables**: PYCODEMCP_* environment variables
5. **Global Configuration**: ~/.config/pycodemcp/config.json
6. **Auto-Discovery**: Automatic detection of sibling packages

Namespace Resolution
~~~~~~~~~~~~~~~~~~~

For distributed namespace packages:

* **Namespace Registry**: Maintains mapping of namespace prefixes to repository paths
* **Import Resolution**: Resolves imports across multiple repositories
* **Path Aggregation**: Combines sys.path entries from all namespace repositories

Performance Characteristics
---------------------------

Scalability
~~~~~~~~~~~

* **Project Limit**: Maximum 10 active projects with LRU eviction
* **Cache Size**: Configurable cache size with memory-aware eviction
* **Connection Pooling**: Reuses Jedi Project instances to reduce startup overhead

Response Times
~~~~~~~~~~~~~~

* **Cache Hit**: < 1ms for cached results
* **Cold Start**: 50-200ms for initial project analysis
* **Symbol Search**: 10-50ms for uncached symbol searches
* **Large Projects**: Scales linearly with project size

Memory Usage
~~~~~~~~~~~~

* **Base Memory**: ~50MB for server and core libraries
* **Per Project**: ~10-20MB per active project
* **Cache Overhead**: ~1-5MB per cached analysis result

Error Handling
--------------

Graceful Degradation
~~~~~~~~~~~~~~~~~~~~

The server is designed to handle failures gracefully:

* **Plugin Failures**: Continue operation if plugins fail to load
* **Analysis Errors**: Return partial results when possible
* **Cache Corruption**: Fall back to fresh analysis
* **Project Errors**: Isolate failures to specific projects

Error Categories
~~~~~~~~~~~~~~~~

* **ValidationError**: Input validation failures
* **AnalysisError**: Jedi analysis failures
* **ConfigurationError**: Configuration loading issues
* **ProjectNotFoundError**: Project path resolution failures
* **TimeoutError**: Analysis timeout exceeded

Security Considerations
-----------------------

Input Validation
~~~~~~~~~~~~~~~~

* **Path Validation**: Ensure all file paths are within allowed directories
* **Input Sanitization**: Sanitize all string inputs to prevent injection
* **Resource Limits**: Enforce timeouts and memory limits

Access Control
~~~~~~~~~~~~~~

* **File System Access**: Only read access to configured project directories
* **Network Access**: No network access by design
* **Process Isolation**: Runs as unprivileged process

Future Architecture
-------------------

Planned Enhancements
~~~~~~~~~~~~~~~~~~~~

* **Tree-sitter Integration**: Pattern-based analysis for complex queries
* **Language Server Protocol**: LSP adapter for IDE integration
* **Distributed Caching**: Redis-backed caching for multi-instance deployments
* **Metrics Collection**: Detailed performance and usage metrics

Extension Points
~~~~~~~~~~~~~~~~

* **Custom Analyzers**: Plugin interface for alternative analysis engines
* **Result Transformers**: Post-processing pipeline for results
* **Cache Backends**: Pluggable cache storage backends
* **Authentication**: Pluggable authentication mechanisms
