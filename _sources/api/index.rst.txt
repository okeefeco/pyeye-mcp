API Reference
=============

This section provides detailed API documentation for the Python Code Intelligence MCP Server.

.. toctree::
   :maxdepth: 2

   server
   analyzers
   plugins
   cache
   config
   utilities

Core MCP Tools
--------------

The server provides the following MCP tools for code analysis:

Navigation Tools
~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: generated

   pycodemcp.server.find_symbol
   pycodemcp.server.goto_definition
   pycodemcp.server.find_references
   pycodemcp.server.get_type_info
   pycodemcp.server.find_imports
   pycodemcp.server.get_call_hierarchy
   pycodemcp.server.find_subclasses

Project Management Tools
~~~~~~~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: generated

   pycodemcp.server.configure_packages
   pycodemcp.server.configure_namespace_package
   pycodemcp.server.find_symbol_multi
   pycodemcp.server.list_project_structure

Analysis Tools
~~~~~~~~~~~~~

.. autosummary::
   :toctree: generated

   pycodemcp.server.list_packages
   pycodemcp.server.list_modules
   pycodemcp.server.get_module_info
   pycodemcp.server.analyze_dependencies

Framework-Specific Tools
~~~~~~~~~~~~~~~~~~~~~~~

Framework-specific tools are available via MCP when the respective frameworks are detected in your project:

* **Pydantic**: find_models, get_model_schema, find_validators, etc.
* **Django**: find_django_models, find_django_views, etc.
* **Flask**: find_routes, find_blueprints, find_views, etc.

These tools are dynamically provided by the MCP server plugins and detailed in the main API documentation.
