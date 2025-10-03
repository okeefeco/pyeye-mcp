API Reference
=============

This section provides detailed API documentation for the PyEye Server.

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

   pyeye.server.find_symbol
   pyeye.server.goto_definition
   pyeye.server.find_references
   pyeye.server.get_type_info
   pyeye.server.find_imports
   pyeye.server.get_call_hierarchy
   pyeye.server.find_subclasses

Project Management Tools
~~~~~~~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: generated

   pyeye.server.configure_packages
   pyeye.server.configure_namespace_package
   pyeye.server.find_symbol_multi
   pyeye.server.list_project_structure

Analysis Tools
~~~~~~~~~~~~~

.. autosummary::
   :toctree: generated

   pyeye.server.list_packages
   pyeye.server.list_modules
   pyeye.server.get_module_info
   pyeye.server.analyze_dependencies

Framework-Specific Tools
~~~~~~~~~~~~~~~~~~~~~~~

Framework-specific tools are available via MCP when the respective frameworks are detected in your project:

* **Pydantic**: find_models, get_model_schema, find_validators, etc.
* **Django**: find_django_models, find_django_views, etc.
* **Flask**: find_routes, find_blueprints, find_views, etc.

These tools are dynamically provided by the MCP server plugins and detailed in the main API documentation.
