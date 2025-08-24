Plugin System
=============

The plugin system provides extensible framework-specific intelligence that goes beyond
basic semantic analysis. Plugins automatically detect project characteristics and
provide specialized tools and enhanced analysis.

Plugin Architecture
-------------------

Base Plugin Interface
~~~~~~~~~~~~~~~~~~~~~

All plugins inherit from the abstract ``AnalyzerPlugin`` base class:

.. code-block:: python

   from abc import ABC, abstractmethod
   from typing import Any, Dict

   class AnalyzerPlugin(ABC):
       def __init__(self, project_path: str):
           self.project_path = Path(project_path)

       @abstractmethod
       def name(self) -> str:
           """Return plugin name for logging and identification."""
           pass

       @abstractmethod
       def detect(self) -> bool:
           """Detect if this plugin should be activated."""
           pass

       @abstractmethod
       def register_tools(self) -> Dict[str, Any]:
           """Return dictionary of MCP tools provided by this plugin."""
           pass

Plugin Lifecycle
~~~~~~~~~~~~~~~~

1. **Detection Phase**: Server scans all registered plugin classes
2. **Activation Check**: Each plugin's ``detect()`` method determines activation
3. **Configuration**: Activated plugins receive namespace and package configuration
4. **Tool Registration**: Plugin tools are registered with the MCP server
5. **Runtime**: Plugin tools become available for client requests

Auto-Detection Logic
~~~~~~~~~~~~~~~~~~~~

Plugins use various strategies to detect if they should be activated:

* **Import Analysis**: Scan for framework-specific imports
* **File Patterns**: Look for characteristic files (models.py, urls.py, etc.)
* **Configuration Files**: Check for framework configuration files
* **Dependency Analysis**: Examine requirements.txt or pyproject.toml

Built-in Plugins
----------------

Pydantic Plugin
~~~~~~~~~~~~~~

**Detection**: Scans for ``from pydantic import BaseModel`` imports

**Specialized Tools**:

* ``find_models`` - Discover all BaseModel classes with field information
* ``get_model_schema`` - Extract complete JSON schema for models
* ``find_validators`` - Locate validation methods (@validator, @field_validator)
* ``find_field_validators`` - Find field-specific validation logic
* ``find_model_config`` - Extract model configuration classes
* ``trace_model_inheritance`` - Map model inheritance hierarchies
* ``find_computed_fields`` - Find @computed_field and @property fields

**Enhanced Analysis**:
- Field type analysis with constraints
- Validation chain tracing
- Schema inheritance resolution

Django Plugin
~~~~~~~~~~~~~

**Detection**: Looks for Django imports and settings.py files

**Specialized Tools**:

* ``find_django_models`` - Locate all Django model classes
* ``find_django_views`` - Find view functions and classes
* ``find_django_urls`` - Discover URL pattern definitions
* ``find_django_templates`` - Locate template files and usage
* ``find_django_migrations`` - Find migration files and dependencies

**Enhanced Analysis**:
- Model field analysis with Django-specific types
- URL pattern resolution with reverse lookups
- Template context analysis

Flask Plugin
~~~~~~~~~~~~

**Detection**: Scans for Flask app creation patterns

**Specialized Tools**:

* ``find_routes`` - Discover route decorators with methods and endpoints
* ``find_blueprints`` - Locate Blueprint definitions and registrations
* ``find_views`` - Find view functions and MethodView classes
* ``find_templates`` - Locate Jinja2 templates and render calls
* ``find_extensions`` - Identify Flask extensions (SQLAlchemy, Login, etc.)
* ``find_config`` - Find configuration files and app.config usage
* ``find_error_handlers`` - Locate error handler decorators
* ``find_cli_commands`` - Find Flask CLI command definitions

**Enhanced Analysis**:
- Route method and endpoint analysis
- Blueprint hierarchy and URL prefix resolution
- Extension configuration tracking

Custom Plugin Development
-------------------------

Creating a Custom Plugin
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Inherit from AnalyzerPlugin**:

.. code-block:: python

   from pycodemcp.plugins.base import AnalyzerPlugin

   class FastAPIPlugin(AnalyzerPlugin):
       def name(self) -> str:
           return "FastAPI"

2. **Implement Detection Logic**:

.. code-block:: python

   def detect(self) -> bool:
       # Check for FastAPI imports
       return any(
           self.find_imports_in_files("fastapi", ["*.py"])
       )

3. **Define Plugin Tools**:

.. code-block:: python

   def register_tools(self) -> Dict[str, Any]:
       return {
           "find_fastapi_routes": self.find_routes,
           "find_fastapi_models": self.find_models,
       }

4. **Implement Tool Methods**:

.. code-block:: python

   async def find_routes(self, scope: str = "main") -> List[Dict[str, Any]]:
       """Find FastAPI route definitions."""
       # Implementation here
       pass

Plugin Best Practices
~~~~~~~~~~~~~~~~~~~~~

**Detection Efficiency**:
- Use efficient file scanning techniques
- Cache detection results when possible
- Fail fast for negative detection

**Tool Naming**:
- Use consistent naming: ``find_{framework}_{component}``
- Provide clear, descriptive tool names
- Avoid conflicts with core tools

**Error Handling**:
- Handle missing dependencies gracefully
- Provide meaningful error messages
- Fall back to basic analysis when possible

**Performance**:
- Use async methods for I/O operations
- Leverage existing caching infrastructure
- Minimize file system operations

Plugin Configuration
--------------------

Namespace Support
~~~~~~~~~~~~~~~~

Plugins automatically receive namespace configuration:

.. code-block:: python

   def set_namespace_paths(self, namespaces: Dict[str, List[Path]]) -> None:
       """Configure namespace package paths."""
       self.namespace_paths = namespaces

   def set_additional_paths(self, paths: List[Path]) -> None:
       """Configure additional package paths."""
       self.additional_paths = paths

Scope Resolution
~~~~~~~~~~~~~~~

Plugin tools support scope-based analysis:

* ``main`` - Only the primary project
* ``all`` - Main project plus configured namespaces
* ``namespace:name`` - Specific namespace only
* ``["main", "namespace:x"]`` - Multiple specific scopes

Framework Integration
~~~~~~~~~~~~~~~~~~~~

Plugins can enhance core analysis results:

.. code-block:: python

   def augment_symbol_results(self, results: List[Dict]) -> List[Dict]:
       """Add framework-specific metadata to symbol results."""
       for result in results:
           if self.is_framework_component(result):
               result["framework_metadata"] = self.get_metadata(result)
       return results

Plugin Registry
---------------

Registration Process
~~~~~~~~~~~~~~~~~~~

Plugins are registered in the server initialization:

.. code-block:: python

   # In server.py
   plugin_classes = [PydanticPlugin, DjangoPlugin, FlaskPlugin]

   for plugin_class in plugin_classes:
       plugin = plugin_class(project_path)
       if plugin.detect():
           _plugins.append(plugin)
           # Register plugin tools with MCP server

Dynamic Loading
~~~~~~~~~~~~~~

Future enhancement will support dynamic plugin loading:

.. code-block:: python

   # Planned enhancement
   from pycodemcp.plugins import load_plugin

   custom_plugin = load_plugin("my_custom_plugin.FastAPIPlugin")

Plugin Testing
--------------

Test Structure
~~~~~~~~~~~~~

Plugin tests should follow this pattern:

.. code-block:: python

   class TestPydanticPlugin:
       def test_detection_positive(self):
           """Test plugin detects Pydantic projects."""
           pass

       def test_detection_negative(self):
           """Test plugin doesn't activate on non-Pydantic projects."""
           pass

       def test_tool_registration(self):
           """Test all expected tools are registered."""
           pass

       def test_find_models(self):
           """Test model discovery functionality."""
           pass

Mock Strategies
~~~~~~~~~~~~~~

Use project fixtures for testing:

.. code-block:: python

   @pytest.fixture
   def pydantic_project(tmp_path):
       """Create a test Pydantic project."""
       models_file = tmp_path / "models.py"
       models_file.write_text("""
       from pydantic import BaseModel

       class User(BaseModel):
           name: str
           email: str
       """)
       return tmp_path
