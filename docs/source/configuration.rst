Configuration
=============

The Python Code Intelligence MCP Server supports flexible configuration through multiple sources with clear precedence rules.

Configuration Sources
---------------------

The server loads configuration from multiple sources in this order of precedence:

1. **Runtime Configuration** - Direct API calls (highest priority)
2. **Project Configuration** - `.pycodemcp.json` in project root
3. **pyproject.toml** - `[tool.pycodemcp]` section
4. **Environment Variables** - `PYCODEMCP_*` variables
5. **Global Configuration** - `~/.config/pycodemcp/config.json`
6. **Auto-Discovery** - Automatic detection of sibling packages (lowest priority)

Project Configuration
--------------------

.pycodemcp.json
~~~~~~~~~~~~~~~

Create a `.pycodemcp.json` file in your project root:

.. code-block:: json

   {
     "packages": [
       "../shared-library",
       "~/repos/common-utils",
       "/absolute/path/to/package"
     ],
     "namespaces": {
       "company": [
         "~/repos/company-auth",
         "~/repos/company-api",
         "~/repos/company-models"
       ],
       "internal": [
         "../internal-tools",
         "../internal-shared"
       ]
     },
     "cache": {
       "enabled": true,
       "ttl_seconds": 300,
       "max_entries": 10000
     },
     "analysis": {
       "max_workers": 4,
       "timeout_seconds": 30,
       "include_tests": false
     }
   }

pyproject.toml
~~~~~~~~~~~~~~

Add configuration to your `pyproject.toml`:

.. code-block:: toml

   [tool.pycodemcp]
   packages = [
     "../shared-library",
     "~/repos/common-utils"
   ]

   [tool.pycodemcp.namespaces]
   company = [
     "~/repos/company-auth",
     "~/repos/company-api"
   ]

   [tool.pycodemcp.cache]
   enabled = true
   ttl_seconds = 300
   max_entries = 10000

   [tool.pycodemcp.analysis]
   max_workers = 4
   timeout_seconds = 30
   include_tests = false

Environment Variables
--------------------

Override configuration using environment variables:

.. code-block:: bash

   # Package paths (colon-separated)
   export PYCODEMCP_PACKAGES="../lib1:../lib2:~/utils"

   # Namespace configuration (JSON format)
   export PYCODEMCP_NAMESPACES='{"company": ["~/auth", "~/api"]}'

   # Cache settings
   export PYCODEMCP_CACHE_TTL=600
   export PYCODEMCP_CACHE_MAX_ENTRIES=20000
   export PYCODEMCP_CACHE_ENABLED=true

   # Analysis settings
   export PYCODEMCP_MAX_WORKERS=8
   export PYCODEMCP_TIMEOUT=60
   export PYCODEMCP_INCLUDE_TESTS=true

   # Logging
   export PYCODEMCP_LOG_LEVEL=DEBUG
   export PYCODEMCP_LOG_FILE=/tmp/pycodemcp.log

Global Configuration
-------------------

Create a global configuration file at `~/.config/pycodemcp/config.json`:

.. code-block:: json

   {
     "default_packages": [
       "~/common-libraries/utils",
       "~/common-libraries/shared"
     ],
     "cache": {
       "enabled": true,
       "ttl_seconds": 600,
       "max_memory_mb": 500,
       "persistence": "file"
     },
     "performance": {
       "max_workers": 6,
       "connection_pool_size": 10,
       "file_watcher_enabled": true
     },
     "logging": {
       "level": "INFO",
       "file": "~/.cache/pycodemcp/server.log",
       "max_size_mb": 10,
       "backup_count": 5
     }
   }

Configuration Options
--------------------

Package Configuration
~~~~~~~~~~~~~~~~~~~~

**packages**
  List of additional package/project paths to include in analysis.

  - Supports relative paths (`../lib`), home directory (`~/utils`), and absolute paths
  - Paths are resolved relative to the project root
  - Invalid paths are logged and ignored

**namespaces**
  Dictionary mapping namespace prefixes to lists of repository paths.

  - Enables analysis across distributed namespace packages
  - Supports the same path formats as packages
  - Namespace resolution follows Python's namespace package rules

Cache Configuration
~~~~~~~~~~~~~~~~~~

**cache.enabled**
  Enable/disable result caching (default: `true`)

**cache.ttl_seconds**
  Time-to-live for cache entries in seconds (default: `300`)

**cache.max_entries**
  Maximum number of cache entries to maintain (default: `10000`)

**cache.max_memory_mb**
  Maximum memory usage for cache in megabytes (default: `500`)

**cache.persistence**
  Cache persistence strategy: `"memory"` (default), `"file"`, or `"redis"`

Analysis Configuration
~~~~~~~~~~~~~~~~~~~~~

**analysis.max_workers**
  Maximum number of worker threads for concurrent analysis (default: `4`)

**analysis.timeout_seconds**
  Timeout for individual analysis operations in seconds (default: `30`)

**analysis.include_tests**
  Include test files in analysis (default: `false`)

**analysis.exclude_patterns**
  Glob patterns for files/directories to exclude:

  .. code-block:: json

     "exclude_patterns": [
       "**/__pycache__/**",
       "**/.*/**",
       "**/venv/**",
       "**/node_modules/**"
     ]

Performance Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

**performance.connection_pool_size**
  Size of Jedi connection pool (default: `10`)

**performance.file_watcher_enabled**
  Enable file system watching for cache invalidation (default: `true`)

**performance.preload_common_symbols**
  Preload frequently used symbols on startup (default: `false`)

**performance.batch_size**
  Batch size for concurrent operations (default: `50`)

Plugin Configuration
~~~~~~~~~~~~~~~~~~~

**plugins.enabled**
  List of plugins to enable explicitly:

  .. code-block:: json

     "plugins": {
       "enabled": ["pydantic", "django", "flask"],
       "disabled": ["custom_plugin"]
     }

**plugins.pydantic.include_private_fields**
  Include private fields in Pydantic model analysis (default: `false`)

**plugins.django.include_migrations**
  Include migration files in Django analysis (default: `true`)

**plugins.flask.blueprint_prefix_resolution**
  Resolve blueprint URL prefixes (default: `true`)

Runtime Configuration
--------------------

API Configuration
~~~~~~~~~~~~~~~~

Configure packages and namespaces at runtime:

.. code-block:: python

   # Configure additional packages
   config = await configure_packages(
       packages=["../shared-lib", "~/utils"],
       save=True  # Save to .pycodemcp.json
   )

   # Configure namespace packages
   await configure_namespace_package(
       namespace="company",
       repo_paths=[
           "~/repos/company-auth",
           "~/repos/company-api"
       ]
   )

Dynamic Updates
~~~~~~~~~~~~~~

Configuration changes take effect immediately:

.. code-block:: python

   # Add a new package at runtime
   await configure_packages(
       packages=["../new-library"],
       save=False  # Don't persist to file
   )

   # The new package is immediately available for analysis
   results = await find_symbol("SomeClass")

Configuration Validation
------------------------

Validate Configuration
~~~~~~~~~~~~~~~~~~~~~~

The server validates configuration on startup:

.. code-block:: python

   # Check current configuration
   config = await configure_packages()
   print(f"Active packages: {config['packages']}")
   print(f"Active namespaces: {config['namespaces']}")

   # Validate paths exist and are readable
   from pycodemcp.config import validate_config

   validation_result = validate_config("/path/to/project")
   if not validation_result.valid:
       for error in validation_result.errors:
           print(f"Configuration error: {error}")

Common Patterns
~~~~~~~~~~~~~~

**Monorepo Configuration:**

.. code-block:: json

   {
     "packages": [
       "./services/auth",
       "./services/api",
       "./services/workers",
       "./shared/models",
       "./shared/utils"
     ]
   }

**Microservices Configuration:**

.. code-block:: json

   {
     "namespaces": {
       "services": [
         "../auth-service",
         "../user-service",
         "../order-service"
       ],
       "shared": [
         "../shared-models",
         "../shared-utils"
       ]
     }
   }

**Enterprise Configuration:**

.. code-block:: json

   {
     "packages": [
       "~/company/shared-libraries/core",
       "~/company/shared-libraries/utils",
       "~/company/shared-libraries/testing"
     ],
     "namespaces": {
       "company.auth": [
         "~/company/services/auth-api",
         "~/company/services/auth-ui"
       ],
       "company.billing": [
         "~/company/services/billing-api",
         "~/company/services/billing-workers"
       ]
     },
     "cache": {
       "persistence": "redis",
       "ttl_seconds": 1800,
       "max_memory_mb": 2048
     }
   }

Troubleshooting Configuration
----------------------------

Debug Configuration Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable debug logging to see configuration loading:

.. code-block:: bash

   export PYCODEMCP_LOG_LEVEL=DEBUG
   # Logs will show which configuration sources are loaded

Common Issues
~~~~~~~~~~~~

**Paths not resolved**
  - Check that relative paths are correct relative to project root
  - Ensure `~` expansion works in your environment
  - Use absolute paths if relative paths cause issues

**Namespace packages not found**
  - Verify all repository paths exist and contain Python code
  - Check that namespace directories have proper `__init__.py` files (or are PEP 420 packages)
  - Ensure namespace names match your import statements

**Configuration ignored**
  - Check precedence - runtime configuration overrides file configuration
  - Validate JSON syntax in configuration files
  - Check file permissions on configuration files

**Performance issues**
  - Reduce `max_workers` if system is overloaded
  - Increase `ttl_seconds` for more aggressive caching
  - Disable file watching if it's causing issues

Validation Commands
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Test configuration loading
   python -c "from pycodemcp.config import load_config; print(load_config('.'))"

   # Validate all configured paths exist
   python -c "
   from pycodemcp.config import ProjectConfig
   config = ProjectConfig('.')
   for path in config.get_package_paths():
       print(f'{path}: exists={Path(path).exists()}')"

   # Test namespace resolution
   python -c "
   from pycodemcp.namespace_resolver import NamespaceResolver
   resolver = NamespaceResolver('.')
   print(resolver.resolve_import('company.auth.models'))"
