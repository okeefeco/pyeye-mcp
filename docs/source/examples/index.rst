Examples
========

This section provides practical examples of using the Python Code Intelligence MCP Server.

.. toctree::
   :maxdepth: 2

   basic-usage
   multi-project
   custom-plugins
   performance-tuning

Quick Start Examples
-------------------

Basic Symbol Search
~~~~~~~~~~~~~~~~~~~

Find all definitions of a symbol:

.. code-block:: python

   # Find all classes named 'User'
   results = await find_symbol('User')
   for result in results:
       print(f"Found {result['type']} at {result['file']}:{result['line']}")

Fuzzy search for partial matches:

.. code-block:: python

   # Find all symbols containing 'parse'
   results = await find_symbol('parse', fuzzy=True)
   # Returns: parse_json, html_parser, argument_parser, etc.

Navigate to Definition
~~~~~~~~~~~~~~~~~~~~~

Jump to a symbol's definition from a usage:

.. code-block:: python

   # From a position in code, go to definition
   definition = await goto_definition(
       file="src/main.py",
       line=25,
       column=10
   )

   if definition:
       print(f"Definition at {definition['file']}:{definition['line']}")

Find All References
~~~~~~~~~~~~~~~~~~

Find all usages of a symbol:

.. code-block:: python

   # Find all references to a symbol at a specific position
   references = await find_references(
       file="src/models.py",
       line=15,
       column=6,
       include_definitions=True
   )

   for ref in references:
       print(f"Reference at {ref['file']}:{ref['line']}")

Type Information
~~~~~~~~~~~~~~~

Get type hints and documentation:

.. code-block:: python

   # Get type information at cursor position
   type_info = await get_type_info(
       file="src/api.py",
       line=42,
       column=15
   )

   print(f"Type: {type_info['type']}")
   print(f"Docstring: {type_info['docstring']}")

Project Structure Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~

Analyze project organization:

.. code-block:: python

   # List all packages in the project
   packages = await list_packages()
   for package in packages:
       print(f"Package: {package['name']} ({package['file_count']} files)")

   # Get detailed module information
   module_info = await get_module_info("myproject.models")
   print(f"Exports: {module_info['exports']}")
   print(f"Classes: {module_info['classes']}")
   print(f"Functions: {module_info['functions']}")

Dependency Analysis
~~~~~~~~~~~~~~~~~~

Analyze module dependencies and detect circular imports:

.. code-block:: python

   # Analyze dependencies for a module
   deps = await analyze_dependencies("myproject.services.user")

   print("Imports:")
   for imp in deps['imports']:
       print(f"  {imp}")

   print("Imported by:")
   for ref in deps['imported_by']:
       print(f"  {ref}")

   if deps['circular_dependencies']:
       print("⚠️  Circular dependencies detected!")
       for cycle in deps['circular_dependencies']:
           print(f"  {' -> '.join(cycle)}")

Framework-Specific Examples
---------------------------

Pydantic Models
~~~~~~~~~~~~~~

Work with Pydantic models and schemas:

.. code-block:: python

   # Find all Pydantic models
   models = await find_models()
   for model in models:
       print(f"Model: {model['name']} in {model['file']}")

       # Get the full schema
       schema = await get_model_schema(model['name'])
       print(f"Schema: {schema['schema']}")

       # Find validators
       validators = await find_validators(scope="main")
       for validator in validators:
           if validator['model'] == model['name']:
               print(f"  Validator: {validator['name']}")

Django Projects
~~~~~~~~~~~~~~

Analyze Django applications:

.. code-block:: python

   # Find all Django models
   models = await find_django_models()
   for model in models:
       print(f"Model: {model['name']} ({model['app']})")
       print(f"  Fields: {', '.join(model['fields'])}")

   # Find views and their URL patterns
   views = await find_django_views()
   urls = await find_django_urls()

   # Match views to URLs
   for view in views:
       matching_urls = [u for u in urls if u['view'] == view['name']]
       if matching_urls:
           print(f"View {view['name']} -> {matching_urls[0]['pattern']}")

Flask Applications
~~~~~~~~~~~~~~~~~

Explore Flask routes and blueprints:

.. code-block:: python

   # Find all routes
   routes = await find_routes()
   for route in routes:
       methods = ', '.join(route['methods'])
       print(f"{methods} {route['rule']} -> {route['endpoint']}")

   # Find blueprints and their routes
   blueprints = await find_blueprints()
   for bp in blueprints:
       print(f"Blueprint: {bp['name']} (prefix: {bp['url_prefix']})")

       # Find templates used by this blueprint
       templates = await find_templates()
       bp_templates = [t for t in templates if bp['name'] in t['file']]
       for template in bp_templates:
           print(f"  Template: {template['template']}")

Multi-Project Configuration
---------------------------

Configure analysis across multiple related projects:

.. code-block:: python

   # Configure additional packages
   config = await configure_packages(
       packages=["../shared-lib", "~/repos/common-utils"],
       namespaces={
           "company": [
               "~/repos/company-auth",
               "~/repos/company-api",
               "~/repos/company-models"
           ]
       }
   )

   print(f"Configured packages: {config['packages']}")
   print(f"Configured namespaces: {config['namespaces']}")

   # Search across all configured projects
   results = await find_symbol_multi(
       name="UserService",
       project_paths=config['packages']
   )

   for project, project_results in results.items():
       if project_results:
           print(f"\nFound in {project}:")
           for result in project_results:
               print(f"  {result['name']} at {result['file']}")

Performance Examples
-------------------

Efficient Analysis Patterns
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Batch operations for better performance
   symbol_names = ["User", "Product", "Order", "Invoice"]

   # Use list comprehension for concurrent searches
   import asyncio
   results = await asyncio.gather(*[
       find_symbol(name) for name in symbol_names
   ])

   # Combine results
   all_symbols = {}
   for name, result in zip(symbol_names, results):
       all_symbols[name] = result

Cache-Aware Operations
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # First call - cache miss (slower)
   start_time = time.time()
   results = await find_symbol("MyClass")
   print(f"First call: {time.time() - start_time:.2f}s")

   # Second call - cache hit (much faster)
   start_time = time.time()
   results = await find_symbol("MyClass")
   print(f"Second call: {time.time() - start_time:.2f}s")

   # Cache is automatically invalidated when files change
   # Edit a file and the cache will be updated automatically

Error Handling
-------------

Robust Error Handling
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from pycodemcp.exceptions import (
       AnalysisError,
       FileAccessError,
       ValidationError
   )

   try:
       results = await find_symbol("MySymbol", project_path="/invalid/path")
   except FileAccessError as e:
       print(f"Project not found: {e}")
   except ValidationError as e:
       print(f"Invalid input: {e}")
   except AnalysisError as e:
       print(f"Analysis failed: {e}")
       # Might include additional context in e.context

Graceful Degradation
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Handle partial failures gracefully
   try:
       # Try comprehensive analysis first
       results = await analyze_dependencies("mymodule")
   except AnalysisError:
       # Fall back to simpler analysis
       results = await find_imports("mymodule")
       print("⚠️ Using simplified analysis due to errors")

Integration Examples
-------------------

With IDEs and Editors
~~~~~~~~~~~~~~~~~~~~

The server integrates well with development tools:

.. code-block:: python

   # Simulate IDE "Go to Definition" functionality
   async def ide_goto_definition(filename, line, column):
       definition = await goto_definition(filename, line, column)
       if definition:
           return {
               'file': definition['file'],
               'line': definition['line'],
               'column': definition['column']
           }
       return None

   # Simulate "Find All References"
   async def ide_find_references(filename, line, column):
       references = await find_references(filename, line, column)
       return [
           {'file': ref['file'], 'line': ref['line']}
           for ref in references
       ]

With CI/CD Pipelines
~~~~~~~~~~~~~~~~~~~

Use for code quality checks:

.. code-block:: python

   # Check for circular dependencies in CI
   async def check_circular_imports():
       all_modules = await list_modules()
       circular_deps = []

       for module in all_modules:
           deps = await analyze_dependencies(module['import_path'])
           if deps.get('circular_dependencies'):
               circular_deps.extend(deps['circular_dependencies'])

       if circular_deps:
           print("❌ Circular dependencies found:")
           for cycle in circular_deps:
               print(f"  {' -> '.join(cycle)}")
           return False
       else:
           print("✅ No circular dependencies found")
           return True
