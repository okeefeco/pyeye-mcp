Python Code Intelligence MCP Server Documentation
==================================================

Welcome to the Python Code Intelligence MCP Server documentation. This project provides
intelligent Python code analysis capabilities for AI assistants like Claude through the
Model Context Protocol (MCP).

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   quickstart
   architecture/index
   api/index
   examples/index
   configuration
   contributing

Quick Start
-----------

The Python Code Intelligence MCP Server provides semantic code analysis for Python projects.
It supports multi-project analysis, namespace packages, and framework-specific intelligence
for Django, Flask, and Pydantic.

Key Features
~~~~~~~~~~~~

* **Semantic Code Navigation**: Find symbols, go to definitions, find references using Jedi
* **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
* **Namespace Packages**: Handle packages distributed across multiple repositories
* **Auto-Update**: File watching automatically reflects code changes
* **Configuration System**: Flexible configuration via files, env vars, or auto-discovery
* **Plugin Architecture**: Extensible with custom analyzers for project patterns

Installation
~~~~~~~~~~~~

.. code-block:: bash

   pip install python-code-intelligence-mcp

Configuration
~~~~~~~~~~~~~

Create a `.pycodemcp.json` configuration file in your project root:

.. code-block:: json

   {
     "packages": ["../my-lib", "~/repos/shared-utils"],
     "namespaces": {
       "company": ["~/repos/company-auth", "~/repos/company-api"]
     }
   }

Basic Usage
~~~~~~~~~~~

The server provides MCP tools for code analysis. Here are some key tools:

* ``find_symbol`` - Find class/function/variable definitions
* ``goto_definition`` - Jump to symbol definition
* ``find_references`` - Find all symbol usages
* ``get_type_info`` - Get type hints and docstrings
* ``analyze_dependencies`` - Analyze module imports and detect circular dependencies

Performance
-----------

The server is designed for high performance with:

* **5-minute result caching** with intelligent invalidation
* **LRU project management** (max 10 projects)
* **File watching** for automatic updates
* **Connection pooling** for Jedi analyzers

Framework Support
-----------------

The server automatically detects and provides specialized tools for:

**Pydantic**
  Find models, get schemas, locate validators, trace inheritance

**Django**
  Find models, views, URLs, templates, migrations

**Flask**
  Find routes, blueprints, templates, extensions, CLI commands

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
