# Test Migration Guide for Async Methods

## Overview

As part of the async file operations implementation (PR #56), many methods in the codebase have been converted to async. This requires updating the tests to properly handle async methods.

## Changes Required

### 1. Methods That Are Now Async

The following methods have been converted to async and require await when called:

#### JediAnalyzer

- `find_symbol()`
- `goto_definition()`
- `find_references()`
- `get_completions()`
- `get_signature_help()`
- `analyze_imports()`
- `list_packages()`
- `list_modules()`
- `analyze_dependencies()`
- `get_module_info()`
- `find_reexports()`
- `_serialize_name()`
- `_check_symbol_in_init()`

#### Plugin Methods

- `find_models()` (Django, Pydantic)
- `find_views()` (Django, Flask)
- `find_routes()` (Flask)
- `find_blueprints()` (Flask)
- `find_templates()` (Flask)
- `find_extensions()` (Flask)
- `find_config()` (Flask)
- `find_error_handlers()` (Flask)
- `find_cli_commands()` (Flask)
- `get_model_schema()` (Pydantic)
- `find_validators()` (Pydantic)
- `find_field_validators()` (Pydantic)
- `find_model_config()` (Pydantic)
- `trace_model_inheritance()` (Pydantic)
- `find_computed_fields()` (Pydantic)

#### Server Tool Functions

- `find_symbol()`
- `goto_definition()`
- `find_references()`
- `get_type_info()`
- `find_imports()`
- `get_call_hierarchy()`
- `list_packages()`
- `list_modules()`
- `analyze_dependencies()`
- `get_module_info()`

### 2. How to Update Tests

#### Before (Synchronous Test)

```python
def test_find_symbol(self, mock_project_class, temp_project_dir):
    """Test finding symbol definitions."""
    analyzer = JediAnalyzer(str(temp_project_dir))
    results = analyzer.find_symbol("test_function")
    assert len(results) == 1
```

#### After (Asynchronous Test)

```python
@pytest.mark.asyncio
async def test_find_symbol(self, mock_project_class, temp_project_dir):
    """Test finding symbol definitions."""
    analyzer = JediAnalyzer(str(temp_project_dir))
    results = await analyzer.find_symbol("test_function")
    assert len(results) == 1
```

### 3. Key Changes

1. **Add `@pytest.mark.asyncio` decorator** to test methods that call async functions
2. **Make test methods async** by adding `async` keyword
3. **Use `await`** when calling async methods
4. **Use `AsyncMock`** instead of `Mock` when mocking async methods

### 4. Testing Async Methods with Mocks

```python
from unittest.mock import AsyncMock

# Mock an async method
mock_analyzer = Mock()
mock_analyzer.find_symbol = AsyncMock(return_value=[{"name": "test"}])

# In the test
results = await mock_analyzer.find_symbol("test")
```

### 5. Files That Need Updates

The following test files need to be updated:

- `tests/test_jedi_analyzer.py`
- `tests/test_server.py`
- `tests/test_django_plugin.py`
- `tests/test_flask_plugin.py`
- `tests/test_pydantic_plugin.py`
- `tests/test_module_analysis.py`
- `tests/integration/test_end_to_end.py`

## Migration Strategy

1. **Prioritize critical tests** - Start with the most important test files
2. **Use pytest-asyncio** - Already installed, provides the `@pytest.mark.asyncio` decorator
3. **Run tests incrementally** - Update and test one file at a time
4. **Keep detect() methods sync** - Plugin detection methods remain synchronous for initialization

## Example Migration

See commit history for examples of how tests were migrated. The pattern is consistent:

1. Add `@pytest.mark.asyncio`
2. Make method `async`
3. Add `await` to async calls
4. Update mocks to use `AsyncMock` where needed
