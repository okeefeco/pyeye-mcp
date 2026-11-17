# Testing Strategy

## Overview

The PyEye project follows a comprehensive testing strategy designed to ensure reliability, maintainability, and performance across multiple platforms.

## Testing Philosophy

### Core Principles

1. **Test-Driven Development (TDD)**: Write tests first when possible
2. **Fast Feedback**: Unit tests should run in milliseconds
3. **Isolation**: Tests should not depend on external services or state
4. **Deterministic**: Tests must produce consistent results
5. **Meaningful**: Each test should verify specific behavior
6. **Maintainable**: Tests should be easy to understand and update

## Testing Pyramid

We aim for a pyramid: many fast unit tests, fewer integration tests, few end-to-end tests.

```text
       /\        E2E Tests
      /  \       - Complete user workflows
     /    \      - Critical path validation
    /------\
   /        \    Integration Tests
  /          \   - Component interactions
 /            \  - API contracts
/--------------\
                 Unit Tests
                 - Individual functions
                 - Class methods
                 - Pure logic
```

### Unit Tests

**Purpose**: Verify individual components in isolation

**Characteristics**:

- Fast execution
- No external dependencies
- Mock all I/O operations
- Test edge cases and error conditions

**Location**: `tests/unit/`

**Example**:

```python
def test_validate_path_with_valid_input():
    """Test path validation with valid input."""
    result = validate_path("/valid/path")
    assert result is True
```

### Integration Tests

**Purpose**: Verify component interactions and API contracts

**Characteristics**:

- Test real component interactions
- May use test databases or caches
- Verify MCP protocol compliance
- Test plugin integrations

**Location**: `tests/integration/`

**Example**:

```python
async def test_jedi_analyzer_finds_symbols():
    """Test Jedi analyzer integration."""
    analyzer = JediAnalyzer()
    symbols = await analyzer.find_symbol("TestClass")
    assert len(symbols) > 0
```

### End-to-End Tests

**Purpose**: Validate complete user workflows

**Characteristics**:

- Test full scenarios from user perspective
- Slower execution acceptable
- Verify critical business flows
- May involve multiple components

**Location**: `tests/e2e/`

**Example**:

```python
async def test_complete_refactoring_workflow():
    """Test complete refactoring workflow."""
    # Setup project
    # Find symbol
    # Get references
    # Perform refactoring
    # Verify results
```

## Coverage Requirements

### Overall Coverage Goals

- **Minimum**: <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end --> (CI enforced)

### Coverage Enforcement

pytest fails when coverage drops below <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.

```bash
# Fails below the threshold
uv run pytest

# Generate detailed report
uv run pytest --cov=src/pyeye --cov-report=html
```

## Performance Testing

### Performance Thresholds

Performance tests compare timings against `PerformanceThresholds`, which give a separate limit for local runs and each CI platform. Shared ones live in `CommonThresholds` (`tests/utils/performance.py`):

```python
from tests.utils.performance import PerformanceThresholds

SYMBOL_SEARCH = PerformanceThresholds(
    base=100.0,      # Local development
    linux_ci=150.0,  # Linux CI
    macos_ci=300.0,  # macOS CI
    windows_ci=300.0 # Windows CI
)
```

### Benchmark Tests

Located in `tests/performance/benchmarks/`:

- Symbol search performance
- Cache operations
- Concurrent request handling
- Large project analysis

## Cross-Platform Testing

### Supported Platforms

- Linux (Ubuntu latest)
- macOS (latest)
- Windows (latest)

### Platform-Specific Tests

```python
@pytest.mark.skipif(os.name == "nt", reason="Unix-specific test")
def test_unix_permissions():
    """Test Unix file permissions."""
    pass

@pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
def test_windows_paths():
    """Test Windows path handling."""
    pass
```

### Path Handling

Always use `.as_posix()` for cross-platform compatibility:

```python
# Correct
path_str = path.as_posix()

# Wrong
path_str = str(path)
```

## Test Data Management

### Fixtures

Shared fixtures in `tests/fixtures/`:

- Sample project structures
- Configuration files
- Test data sets

### Fixture Factories

Use factories for consistent test data:

```python
from tests.fixtures.factories import ProjectFactory

def test_with_project(tmp_path):
    project = ProjectFactory.create(tmp_path, name="test_project", modules=10)
```

### Cleanup

Always clean up test artifacts:

```python
@pytest.fixture
def temp_project(tmp_path):
    """Create and cleanup temporary project."""
    project = create_project(tmp_path)
    yield project
    cleanup_project(project)
```

## CI/CD Integration

### Test Stages

1. **Pre-commit**: linting, formatting, security, docs facts
2. **Tests**: the full suite with coverage, on each OS and Python in the CI matrix

## Quality Gates

### Pull Request Requirements

- [ ] All tests pass
- [ ] Coverage ≥ <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->
- [ ] No performance regressions
- [ ] Cross-platform validation
- [ ] Type checking passes

### Test Review Checklist

- [ ] Tests are meaningful and focused
- [ ] Edge cases covered
- [ ] Error conditions tested
- [ ] Mocks used appropriately
- [ ] No test interdependencies

## Best Practices

### DO

- Write descriptive test names
- Use fixtures for common setup
- Test one thing per test
- Use meaningful assertions
- Mock external dependencies
- Test error conditions

### DON'T

- Write tests that depend on test order
- Use production data in tests
- Test implementation details
- Ignore flaky tests
- Skip writing tests for "simple" code
- Use `time.sleep()` in tests

## Testing Tools

### Core Tools

- **pytest**: Test framework
- **pytest-asyncio**: Async test support
- **pytest-cov**: Coverage reporting
- **pytest-timeout**: per-test timeout, so a hang fails instead of stalling

Test data factories: `tests/fixtures/factories.py`.

## Continuous Improvement

### Metrics to Track

- Test execution time
- Coverage trends
- Flaky test rate
- Test maintenance cost
- Bug escape rate

## Getting Started

### Running Tests

```bash
# Run all tests (with coverage, via pyproject's addopts)
uv run pytest

# Run one directory
uv run pytest tests/unit
uv run pytest tests/integration
uv run pytest tests/e2e

# HTML coverage report
uv run pytest --cov-report=html
```

### Writing Your First Test

1. Choose appropriate test category (unit/integration/e2e)
2. Create test file following naming convention
3. Write focused, meaningful tests
4. Verify coverage improvement
5. Ensure cross-platform compatibility

## References

- [Testing Conventions](./CONVENTIONS.md)
- [Fixture Guide](./FIXTURES.md)
- [Performance Testing](./PERFORMANCE.md)
- [Coverage Tracking](../COVERAGE.md)
