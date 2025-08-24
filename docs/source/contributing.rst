Contributing
============

Thank you for your interest in contributing to the Python Code Intelligence MCP Server! This guide will help you get started.

.. note::
   This is a condensed version of the contributing guide. For complete details including mandatory workflows, validation requirements, and development setup, see the main `CONTRIBUTING.md <https://github.com/okeefeco/python-code-intelligence-mcp/blob/main/CONTRIBUTING.md>`_ file.

Quick Start for Contributors
----------------------------

1. **Fork and Clone**

   .. code-block:: bash

      git clone https://github.com/yourusername/python-code-intelligence-mcp.git
      cd python-code-intelligence-mcp

2. **Set Up Development Environment**

   .. code-block:: bash

      uv venv
      uv pip install -e ".[dev]"
      pre-commit install

3. **Run Tests**

   .. code-block:: bash

      pytest --cov=src/pycodemcp --cov-fail-under=85

Development Workflow
--------------------

**CRITICAL**: This project follows a mandatory GitHub issue-based workflow:

1. **Always create or reference a GitHub issue** before starting work
2. **Use branch naming**: `type/issue-number-description` (e.g., `fix/42-symbol-search`)
3. **Never work directly on main branch**
4. **All changes require tests** with minimum 85% coverage

Code Standards
--------------

Critical Requirements
~~~~~~~~~~~~~~~~~~~~

These are **non-negotiable** and will cause CI failures:

1. **Cross-Platform Paths**: Always use `.as_posix()` for display/storage paths
2. **Performance Tests**: Use `PerformanceThresholds` framework, never naive timing assertions
3. **Comprehensive Tests**: All code changes require tests

Code Style
~~~~~~~~~~

- Follow PEP 8 (enforced by black and ruff)
- Line length: 100 characters
- Use type hints for all functions
- Google-style docstrings

Example docstring format:

.. code-block:: python

   def find_symbol(name: str, fuzzy: bool = False) -> List[Dict[str, Any]]:
       """Find symbol definitions in the project using semantic analysis.

       Searches for class, function, variable, and module definitions using Jedi's
       semantic analysis engine. Supports exact and fuzzy matching.

       Args:
           name: Symbol name to search for (e.g., 'MyClass', 'my_function')
           fuzzy: Enable fuzzy matching for partial names (default False)

       Returns:
           List of symbol matches with location and type information:
           [
               {
                   'name': 'MyClass',
                   'type': 'class',
                   'file': '/path/to/file.py',
                   'line': 10,
                   'column': 0
               }
           ]

       Raises:
           AnalysisError: If Jedi analysis fails
           ValidationError: If symbol name is invalid

       Example:
           >>> await find_symbol('User', project_path='/my/project')
           [{'name': 'User', 'type': 'class', ...}]
       """

Testing Guidelines
-----------------

Test Requirements
~~~~~~~~~~~~~~~~

- **All new features** must have comprehensive tests
- **All bug fixes** must include regression tests
- **Minimum 85% coverage** (CI enforced)
- Use the performance testing framework for timing-sensitive tests

Performance Testing
~~~~~~~~~~~~~~~~~~

Always use the performance framework:

.. code-block:: python

   from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

   # Define CI-aware thresholds
   search_threshold = PerformanceThresholds(
       base=100.0,        # 100ms for local development
       linux_ci=150.0,   # 150ms for Linux CI
       macos_ci=300.0,   # 300ms for macOS CI
       windows_ci=300.0, # 300ms for Windows CI
   )

   # Use in tests
   elapsed_ms = measure_operation()
   assert_performance_threshold(elapsed_ms, search_threshold, "Symbol search")

MCP-First Development
--------------------

**CRITICAL**: We build Python Code Intelligence MCP - we **must** dogfood our own tools!

Required Workflow
~~~~~~~~~~~~~~~~

When working on Python code, you **must** use MCP tools instead of traditional search:

❌ **Wrong**: `grep -r "class MyClass"`
✅ **Right**: `mcp__python-intelligence__find_symbol("MyClass")`

❌ **Wrong**: `find . -name "*.py" | xargs grep "import"`
✅ **Right**: `mcp__python-intelligence__find_imports("module")`

Before refactoring:
1. `mcp__python-intelligence__find_references()` - **NEVER skip this**
2. `mcp__python-intelligence__find_subclasses()` for inheritance
3. `mcp__python-intelligence__analyze_dependencies()` for impact

Documentation
-------------

Documentation Requirements
~~~~~~~~~~~~~~~~~~~~~~~~~

- **API changes**: Update docstrings and API documentation
- **New features**: Add examples and usage documentation
- **Architecture changes**: Update architecture documentation

Building Documentation
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Install documentation dependencies
   uv pip install sphinx sphinx-autodoc-typehints sphinx-rtd-theme

   # Build documentation
   cd docs
   sphinx-build -b html source build

   # Preview documentation
   python -m http.server 8000 -d build

Plugin Development
-----------------

Creating Custom Plugins
~~~~~~~~~~~~~~~~~~~~~~~

1. **Inherit from AnalyzerPlugin**:

   .. code-block:: python

      from pycodemcp.plugins.base import AnalyzerPlugin

      class MyFrameworkPlugin(AnalyzerPlugin):
          def name(self) -> str:
              return "MyFramework"

2. **Implement required methods**:

   .. code-block:: python

      def detect(self) -> bool:
          """Detect if this plugin should be activated."""
          return self.find_imports_in_files("myframework")

      def register_tools(self) -> Dict[str, Any]:
          """Return MCP tools provided by this plugin."""
          return {
              "find_my_components": self.find_components
          }

3. **Add comprehensive tests** and documentation

Submitting Changes
-----------------

Pull Request Process
~~~~~~~~~~~~~~~~~~~

1. **Ensure all tests pass**:

   .. code-block:: bash

      pytest --cov=src/pycodemcp --cov-fail-under=85

2. **Run pre-commit checks**:

   .. code-block:: bash

      pre-commit run --all-files

3. **Create pull request** with:
   - Clear title and description
   - Reference to GitHub issue
   - Tests for all changes
   - Updated documentation if needed

PR Requirements
~~~~~~~~~~~~~~

- ✅ All CI checks passing
- ✅ Tests with 85%+ coverage
- ✅ Pre-commit hooks passing
- ✅ Issue reference in PR description
- ✅ Documentation updates (if applicable)

Getting Help
-----------

- **GitHub Issues**: `Bug reports and feature requests <https://github.com/okeefeco/python-code-intelligence-mcp/issues>`_
- **Discussions**: `Ask questions and share ideas <https://github.com/okeefeco/python-code-intelligence-mcp/discussions>`_
- **Documentation**: This guide and API reference

Important Links
--------------

- `Complete Contributing Guide <https://github.com/okeefeco/python-code-intelligence-mcp/blob/main/CONTRIBUTING.md>`_ - **Read this first!**
- `GitHub Issues <https://github.com/okeefeco/python-code-intelligence-mcp/issues>`_
- `Architecture Documentation <architecture/index.html>`_
- `API Reference <api/index.html>`_

Recognition
----------

Contributors are recognized in:

- `CHANGELOG.md <https://github.com/okeefeco/python-code-intelligence-mcp/blob/main/CHANGELOG.md>`_
- GitHub contributors list
- Release notes for significant contributions

Thank you for contributing to making Python code analysis more intelligent and accessible!
