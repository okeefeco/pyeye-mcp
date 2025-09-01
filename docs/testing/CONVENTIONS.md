# Testing Conventions

## Test File Organization

### Directory Structure

```text
tests/
├── unit/              # Isolated unit tests
│   ├── core/         # Core module tests
│   ├── plugins/      # Plugin tests
│   ├── utils/        # Utility tests
│   └── analyzers/    # Analyzer tests
├── integration/       # Component interaction tests
│   ├── mcp_protocol/ # MCP protocol tests
│   ├── jedi_integration/ # Jedi integration
│   └── cache_system/ # Cache integration
├── e2e/              # End-to-end tests
│   └── scenarios/    # User scenarios
├── performance/       # Performance tests
│   ├── benchmarks/   # Performance benchmarks
│   └── load_tests/   # Load testing
└── fixtures/         # Shared test data
    ├── projects/     # Sample projects
    └── data/        # Test data files
```

## Naming Conventions

### Test Files

```python
# Pattern: test_<module_name>.py
test_validation.py      # Tests for validation module
test_server.py         # Tests for server module
test_flask_plugin.py   # Tests for Flask plugin
```

### Test Classes

```python
# Pattern: Test<ComponentName>
class TestPathValidator:
    """Tests for PathValidator class."""

class TestMCPServer:
    """Tests for MCP server."""

class TestFlaskPlugin:
    """Tests for Flask plugin."""
```

### Test Functions

```python
# Pattern: test_<what>_<condition>_<expected>
def test_validate_path_with_valid_input_returns_true():
    """Test path validation with valid input returns true."""

def test_find_symbol_with_fuzzy_match_finds_partial():
    """Test symbol finding with fuzzy match finds partial matches."""

def test_cache_get_with_expired_key_returns_none():
    """Test cache get with expired key returns None."""
```

### Fixtures

```python
# Pattern: <scope>_<what>
@pytest.fixture
def mock_project():
    """Create a mock project."""

@pytest.fixture(scope="session")
def test_database():
    """Create test database for session."""

@pytest.fixture
def temp_cache_dir(tmp_path):
    """Create temporary cache directory."""
```

## Test Structure

### Arrange-Act-Assert Pattern

```python
def test_symbol_search():
    # Arrange
    analyzer = JediAnalyzer()
    test_code = "class TestClass: pass"

    # Act
    result = analyzer.find_symbol("TestClass", test_code)

    # Assert
    assert len(result) == 1
    assert result[0]["name"] == "TestClass"
```

### Given-When-Then Pattern (BDD)

```python
def test_user_refactoring_workflow():
    # Given a project with a symbol to rename
    project = create_test_project()
    old_name = "OldClass"
    new_name = "NewClass"

    # When the user performs refactoring
    result = refactor_symbol(project, old_name, new_name)

    # Then all references are updated
    assert result.success
    assert count_references(project, old_name) == 0
    assert count_references(project, new_name) > 0
```

## Assertion Best Practices

### Use Specific Assertions

```python
# Good - specific and clear
assert result == expected_value
assert len(items) == 5
assert error_message in str(exc_info.value)

# Bad - too generic
assert result
assert items
assert exc_info
```

### Meaningful Assertion Messages

```python
# Good - provides context on failure
assert len(results) > 0, f"No results found for query: {query}"
assert path.exists(), f"Expected path does not exist: {path}"

# Bad - no context
assert len(results) > 0
assert path.exists()
```

### Multiple Assertions

```python
# Good - test one concept
def test_symbol_metadata():
    result = get_symbol_metadata("TestClass")
    assert result["name"] == "TestClass"
    assert result["type"] == "class"
    assert result["line"] == 10

# Bad - testing multiple unrelated things
def test_everything():
    # Tests configuration AND symbol search AND caching
    config = load_config()
    assert config.valid

    symbols = find_symbols()
    assert len(symbols) > 0

    cache = get_cache()
    assert cache.size < 1000
```

## Mock Usage Guidelines

### When to Mock

```python
# Mock external services
@patch('requests.get')
def test_api_call(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}

# Mock file I/O
@patch('builtins.open')
def test_file_reading(mock_open):
    mock_open.return_value.__enter__.return_value.read.return_value = "content"

# Mock time-dependent behavior
@patch('time.time')
def test_cache_expiry(mock_time):
    mock_time.return_value = 1234567890
```

### Mock Naming

```python
# Clear mock naming
mock_analyzer = Mock(spec=JediAnalyzer)
mock_project = Mock(spec=Project)
mock_cache = Mock(spec=Cache)

# Configure mock behavior
mock_analyzer.find_symbol.return_value = [{"name": "TestClass"}]
```

### Avoid Over-Mocking

```python
# Good - mock external dependency
@patch('pycodemcp.external_api.fetch')
def test_data_processing(mock_fetch):
    mock_fetch.return_value = test_data
    result = process_data()  # Real processing logic
    assert result.valid

# Bad - mocking the system under test
@patch('pycodemcp.processor.process')  # Don't mock what you're testing!
def test_processor(mock_process):
    mock_process.return_value = "expected"
    result = process_data()
    assert result == "expected"  # Not actually testing anything
```

## Async Test Patterns

### Async Test Functions

```python
@pytest.mark.asyncio
async def test_async_operation():
    """Test async operation."""
    result = await async_function()
    assert result == expected

@pytest.mark.asyncio
class TestAsyncComponent:
    """Test async component."""

    async def test_async_method(self):
        """Test async method."""
        obj = AsyncComponent()
        result = await obj.async_method()
        assert result.success
```

### Async Fixtures

```python
@pytest.fixture
async def async_client():
    """Create async client."""
    client = AsyncClient()
    await client.connect()
    yield client
    await client.disconnect()
```

## Parametrized Tests

### Basic Parametrization

```python
@pytest.mark.parametrize("input,expected", [
    ("valid/path", True),
    ("../invalid", False),
    ("/absolute/path", True),
    ("", False),
])
def test_path_validation(input, expected):
    """Test path validation with various inputs."""
    assert validate_path(input) == expected
```

### Multiple Parameters

```python
@pytest.mark.parametrize("symbol_type,count", [
    ("class", 5),
    ("function", 10),
    ("variable", 3),
])
@pytest.mark.parametrize("fuzzy", [True, False])
def test_symbol_search_combinations(symbol_type, count, fuzzy):
    """Test symbol search with different combinations."""
    results = find_symbols(type=symbol_type, fuzzy=fuzzy)
    assert len(results) == count
```

## Test Markers

### Standard Markers

```python
@pytest.mark.unit
def test_unit_functionality():
    """Unit test."""

@pytest.mark.integration
def test_component_integration():
    """Integration test."""

@pytest.mark.e2e
def test_end_to_end_workflow():
    """E2E test."""

@pytest.mark.slow
def test_slow_operation():
    """Slow test that should be skipped in quick runs."""

@pytest.mark.flaky(reruns=3)
def test_flaky_network_operation():
    """Test that may fail due to network issues."""
```

### Platform-Specific Markers

```python
@pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
def test_unix_specific():
    """Unix-specific test."""

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_windows_specific():
    """Windows-specific test."""
```

## Error Testing

### Exception Testing

```python
def test_raises_validation_error():
    """Test that validation error is raised."""
    with pytest.raises(ValidationError) as exc_info:
        validate_input("invalid")

    assert "Invalid input" in str(exc_info.value)
    assert exc_info.value.code == "INVALID_INPUT"
```

### Warning Testing

```python
def test_deprecation_warning():
    """Test deprecation warning."""
    with pytest.warns(DeprecationWarning):
        old_function()
```

## Test Documentation

### Docstrings

```python
def test_complex_scenario():
    """Test complex refactoring scenario.

    This test verifies that when performing a complex refactoring:
    1. All symbol references are found
    2. References are updated correctly
    3. No unintended changes occur
    4. Performance remains acceptable

    See issue #123 for context.
    """
```

### Comments

```python
def test_edge_case():
    # Setup: Create a project with circular dependencies
    project = create_circular_project()

    # This should not cause infinite recursion
    result = analyze_dependencies(project)

    # Verify the circular dependency is detected but handled
    assert result.has_circular
    assert len(result.cycles) == 1
```

## Performance Test Patterns

### Benchmark Tests

```python
def test_search_performance(benchmark):
    """Benchmark symbol search performance."""
    project = create_large_project(modules=100)

    result = benchmark(search_symbols, project, "TestClass")

    assert len(result) > 0
    assert benchmark.stats["mean"] < 0.1  # 100ms mean
```

### Timing Assertions

```python
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

def test_operation_performance():
    """Test operation performance."""
    threshold = PerformanceThresholds(
        base=100.0,
        linux_ci=150.0,
        macos_ci=300.0,
        windows_ci=300.0
    )

    start = time.perf_counter()
    perform_operation()
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert_performance_threshold(elapsed_ms, threshold, "Operation")
```

## Common Patterns

### Setup and Teardown

```python
class TestComponent:
    """Test component with setup/teardown."""

    def setup_method(self):
        """Setup before each test method."""
        self.component = Component()
        self.test_data = create_test_data()

    def teardown_method(self):
        """Cleanup after each test method."""
        self.component.cleanup()
        remove_test_data(self.test_data)

    def test_functionality(self):
        """Test component functionality."""
        result = self.component.process(self.test_data)
        assert result.success
```

### Temporary Resources

```python
def test_with_temp_file(tmp_path):
    """Test with temporary file."""
    temp_file = tmp_path / "test.txt"
    temp_file.write_text("content")

    result = process_file(temp_file)
    assert result == "processed content"
    # tmp_path is automatically cleaned up
```

### Monkey Patching

```python
def test_with_monkeypatch(monkeypatch):
    """Test with monkeypatched environment."""
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setattr("module.function", lambda: "mocked")

    result = function_using_env()
    assert result == "expected"
```

## Anti-Patterns to Avoid

### Don't Test Implementation Details

```python
# Bad - testing private methods
def test_private_method():
    obj = MyClass()
    assert obj._private_method() == "internal"

# Good - test public interface
def test_public_behavior():
    obj = MyClass()
    assert obj.get_result() == "expected"
```

### Don't Use Production Data

```python
# Bad - using real credentials
def test_api():
    client = APIClient(api_key="real-production-key")

# Good - use test credentials
def test_api():
    client = APIClient(api_key="test-key-12345")
```

### Don't Create Test Dependencies

```python
# Bad - tests depend on order
def test_create_user():
    global user_id
    user_id = create_user("test")

def test_delete_user():
    delete_user(user_id)  # Depends on previous test

# Good - independent tests
def test_create_user():
    user_id = create_user("test")
    assert user_exists(user_id)
    cleanup_user(user_id)

def test_delete_user():
    user_id = create_user("test")
    delete_user(user_id)
    assert not user_exists(user_id)
```

## References

- [Testing Strategy](./STRATEGY.md)
- [Fixture Guide](./FIXTURES.md)
- [Performance Testing](./PERFORMANCE.md)
- [pytest Documentation](https://docs.pytest.org/)
