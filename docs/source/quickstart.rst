Quick Start Guide
=================

Get up and running with the Python Code Intelligence MCP Server in minutes.

Installation
------------

Using pip:

.. code-block:: bash

   pip install python-code-intelligence-mcp

Using uv (recommended for development):

.. code-block:: bash

   git clone https://github.com/okeefeco/python-code-intelligence-mcp.git
   cd python-code-intelligence-mcp
   uv venv
   uv pip install -e ".[dev]"

MCP Server Setup
---------------

The server runs as an MCP (Model Context Protocol) server that AI assistants can connect to.

For Claude Code
~~~~~~~~~~~~~~

Add the server to Claude Code:

.. code-block:: bash

   claude mcp add python-code-intelligence-mcp \
     --command "uv run mcp dev src/pycodemcp/server.py" \
     --directory "/path/to/your/project"

For Other MCP Clients
~~~~~~~~~~~~~~~~~~~~

The server can be used with any MCP-compatible client:

.. code-block:: bash

   # Run the server directly
   uv run mcp dev src/pycodemcp/server.py

Basic Configuration
------------------

Create a `.pycodemcp.json` file in your project root:

.. code-block:: json

   {
     "packages": ["../shared-lib", "~/utils"],
     "namespaces": {
       "mycompany": [
         "~/repos/mycompany-auth",
         "~/repos/mycompany-api"
       ]
     }
   }

Alternative: Use pyproject.toml:

.. code-block:: toml

   [tool.pycodemcp]
   packages = ["../shared-lib", "~/utils"]

   [tool.pycodemcp.namespaces]
   mycompany = ["~/repos/mycompany-auth", "~/repos/mycompany-api"]

First Steps
-----------

Once configured, try these basic operations:

1. **Find a Symbol**

   Search for any class, function, or variable:

   .. code-block:: python

      find_symbol("MyClass")

2. **Navigate Code**

   Jump to definitions and find references:

   .. code-block:: python

      goto_definition(file="main.py", line=25, column=10)
      find_references(file="models.py", line=15, column=6)

3. **Explore Project Structure**

   Understand your codebase organization:

   .. code-block:: python

      list_packages()
      list_modules()
      get_module_info("myproject.services")

4. **Analyze Dependencies**

   Check imports and find circular dependencies:

   .. code-block:: python

      analyze_dependencies("myproject.models")

Framework Detection
------------------

The server automatically detects and provides specialized tools for:

**Pydantic Projects**
  - ``find_models`` - Find Pydantic model classes
  - ``get_model_schema`` - Extract JSON schemas
  - ``find_validators`` - Locate validation methods

**Django Projects**
  - ``find_django_models`` - Find Django model classes
  - ``find_django_views`` - Find view functions/classes
  - ``find_django_urls`` - Find URL patterns

**Flask Projects**
  - ``find_routes`` - Find route decorators
  - ``find_blueprints`` - Find Blueprint definitions
  - ``find_templates`` - Find Jinja2 templates

Performance Features
-------------------

The server is optimized for speed:

- **5-minute caching** with intelligent invalidation
- **File watching** for automatic cache updates
- **Connection pooling** for Jedi analyzers
- **Concurrent analysis** across multiple projects

Typical response times:
- Cache hits: < 1ms
- Symbol searches: 10-50ms
- Large project analysis: 200-500ms

Troubleshooting
--------------

Common Issues
~~~~~~~~~~~~

**"No symbols found"**
  - Check if the project path is correct
  - Verify Python files are readable
  - Try with ``fuzzy=True`` for partial matching

**"Project not found"**
  - Ensure the project path exists and is accessible
  - Check file permissions
  - Verify the path doesn't contain special characters

**Slow performance**
  - Enable caching (enabled by default)
  - Check if file watching is working
  - Consider reducing the scope of analysis

Debug Mode
~~~~~~~~~

Enable debug logging for troubleshooting:

.. code-block:: bash

   export PYCODEMCP_LOG_LEVEL=DEBUG
   uv run mcp dev src/pycodemcp/server.py

Configuration Validation
~~~~~~~~~~~~~~~~~~~~~~~~

Test your configuration:

.. code-block:: python

   configure_packages()  # Returns current configuration

   # Check if paths are accessible
   list_project_structure()

Next Steps
----------

- Read the :doc:`examples/index` for detailed usage patterns
- Explore :doc:`architecture/index` to understand the system design
- Check :doc:`api/index` for complete API reference
- Learn about :doc:`contributing` to the project

Support
-------

- GitHub Issues: `Report bugs and request features <https://github.com/okeefeco/python-code-intelligence-mcp/issues>`_
- Documentation: This guide and API reference
- Examples: See the ``examples/`` directory in the repository
