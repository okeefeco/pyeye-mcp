Configuration
=============

The PyEye Server supports flexible configuration through multiple sources with clear precedence rules.

Configuration Sources
---------------------

The server loads configuration from multiple sources in this order of precedence:

1. **Runtime Configuration** - Direct API calls (highest priority)
2. **Project Configuration** - `.pyeye.json` in project root
3. **pyproject.toml** - `[tool.pyeye]` section
4. **Environment Variables** - `PYEYE_*` variables
5. **Global Configuration** - `~/.config/pyeye/config.json`
6. **Auto-Discovery** - Automatic detection of sibling packages (lowest priority)

Project Configuration
--------------------

.pyeye.json
~~~~~~~~~~~~~~~

Create a `.pyeye.json` file in your project root:

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
     }
   }

pyproject.toml
~~~~~~~~~~~~~~

Add configuration to your `pyproject.toml`:

.. code-block:: toml

   [tool.pyeye]
   packages = [
     "../shared-library",
     "~/repos/common-utils"
   ]

   [tool.pyeye.namespaces]
   company = [
     "~/repos/company-auth",
     "~/repos/company-api"
   ]

Environment Variables
--------------------

Environment variables tune performance and logging. They don't configure
packages or namespaces; use the configuration files above, or the
``configure_packages`` tool, for that.

.. code-block:: bash

   # Cache settings
   export PYEYE_CACHE_TTL=600                    # seconds (default 300)
   export PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=4000  # parsed files kept (default 2000)
   export PYEYE_MAX_PROJECTS=20                  # projects kept (default 10)

   # File watching
   export PYEYE_WATCHER_DEBOUNCE=1.0             # seconds (default 0.5)

   # Logging
   export PYEYE_LOG_LEVEL=DEBUG
   export PYEYE_LOG_FILE=/tmp/pyeye.log

The MCP client starts the server, so set these on the client's server entry
(for example ``claude mcp add pyeye -s user -e PYEYE_LOG_LEVEL=DEBUG -- python -m pyeye.mcp``),
not just in your shell. The full list, with ranges, is in the README's
*Performance Settings* table.

Global Configuration
-------------------

Create a global configuration file at `~/.config/pyeye/config.json`:

.. code-block:: json

   {
     "packages": [
       "~/common-libraries/utils",
       "~/common-libraries/shared"
     ]
   }

It takes the same keys as a project config; a project config overrides it.

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

**standalone.dirs**
  Directories of standalone scripts (not packages); every ``.py`` file under them
  is analysed.

**scope_defaults** / **scope_aliases**
  Default scopes for the framework plugin tools, and named scope shortcuts.

Deprecated Keys (No Effect)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Earlier versions of this page documented these top-level keys, but pyeye has
never read them. They are deprecated: a config that sets one still loads, a
warning names it, and ``configure_packages`` reports it under ``warnings`` (#581).

* Deprecated, no effect: ``cache`` (``ttl_seconds``, ``enabled``, ``max_entries``, ``max_memory_mb``, ``persistence``). Use ``PYEYE_CACHE_TTL`` and ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES``.
* Deprecated, no effect: ``analysis`` (``max_workers``, ``timeout_seconds``, ``include_tests``, ``exclude_patterns``).
* Deprecated, no effect: ``exclude`` and ``exclude_patterns``. There is no file-exclusion setting.
* Deprecated, no effect: ``performance`` (``connection_pool_size``, ``file_watcher_enabled``, ``preload_common_symbols``, ``batch_size``).
* Deprecated, no effect: ``plugins`` (``enabled``, ``disabled`` and per-plugin options). Plugins activate when they detect their framework.
* Deprecated, no effect: ``default_packages`` (use ``packages``), ``logging`` (use ``PYEYE_LOG_LEVEL`` / ``PYEYE_LOG_FILE``) and ``watch_exclude``.

Runtime Configuration
--------------------

API Configuration
~~~~~~~~~~~~~~~~

Configure packages and namespaces at runtime:

.. code-block:: python

   # Configure additional packages
   config = await configure_packages(
       packages=["../shared-lib", "~/utils"],
       save=True  # Save to .pyeye.json
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
   from pyeye.config import validate_config

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
     }
   }

Troubleshooting Configuration
----------------------------

Debug Configuration Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~

Enable debug logging to see configuration loading:

.. code-block:: bash

   export PYEYE_LOG_LEVEL=DEBUG
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
  - Include fewer packages and namespaces
  - Raise ``PYEYE_CACHE_TTL`` or ``PYEYE_ARTIFACT_CACHE_MAX_ENTRIES`` (see Environment Variables)
  - Raise ``PYEYE_WATCHER_DEBOUNCE`` if file watching is noisy

Validation Commands
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Test configuration loading
   python -c "from pyeye.config import load_config; print(load_config('.'))"

   # Validate all configured paths exist
   python -c "
   from pyeye.config import ProjectConfig
   config = ProjectConfig('.')
   for path in config.get_package_paths():
       print(f'{path}: exists={Path(path).exists()}')"

   # Test namespace resolution
   python -c "
   from pyeye.namespace_resolver import NamespaceResolver
   resolver = NamespaceResolver('.')
   print(resolver.resolve_import('company.auth.models'))"
