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

We follow the testing pyramid approach with the following distribution:

```text
       /\        E2E Tests (10%)
      /  \       - Complete user workflows
     /    \      - Critical path validation
    /------\
   /        \    Integration Tests (20%)
  /          \   - Component interactions
 /            \  - API contracts
/--------------\
                 Unit Tests (70%)
                 - Individual functions
                 - Class methods
                 - Pure logic
```

### Unit Tests (70%)

**Purpose**: Verify individual components in isolation

**Characteristics**:

- Fast execution (<100ms per test)
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

### Integration Tests (20%)

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

### End-to-End Tests (10%)

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

- **Minimum**: 85% (CI enforced)
- **Target**: 90%
- **Aspirational**: 95%

### Per-Component Coverage

| Component | Minimum | Target |
|-----------|---------|---------|
| Core modules | 90% | 95% |
| Plugins | 85% | 90% |
| Utilities | 95% | 100% |
| Integration | 80% | 85% |

### Coverage Enforcement

```bash
# Run with coverage check
pytest --cov=src/pyeye --cov-fail-under=85

# Generate detailed report
pytest --cov=src/pyeye --cov-report=html
```

## Performance Testing

### Performance Thresholds

All performance-critical operations have defined thresholds:

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

### Load Testing

Located in `tests/performance/load_tests/`:

- Concurrent user simulation
- Sustained load scenarios
- Burst traffic handling
- Memory usage under load

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

def test_with_project():
    project = ProjectFactory.create(
        name="test_project",
        modules=10
    )
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

1. **Pre-commit**: Linting, formatting, security
2. **Unit Tests**: Fast feedback (< 2 minutes)
3. **Integration Tests**: Component validation (< 5 minutes)
4. **E2E Tests**: Full workflows (< 10 minutes)
5. **Performance Tests**: Regression detection (main branch only)

### Parallel Execution

```yaml
# CI configuration
test:
  strategy:
    matrix:
      test-type: [unit, integration, e2e]
  steps:
    - run: pytest tests/${{ matrix.test-type }} -n auto
```

## Quality Gates

### Pull Request Requirements

- [ ] All tests pass
- [ ] Coverage ≥ 85%
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
- **pytest-mock**: Enhanced mocking

### Additional Tools

- **hypothesis**: Property-based testing
- **pytest-benchmark**: Performance benchmarking
- **pytest-xdist**: Parallel execution
- **factory-boy**: Test data factories
- **faker**: Fake data generation

## Continuous Improvement

### Metrics to Track

- Test execution time
- Coverage trends
- Flaky test rate
- Test maintenance cost
- Bug escape rate

### Regular Reviews

- Monthly: Review and update slow tests
- Quarterly: Assess coverage gaps
- Bi-annually: Review testing strategy

## Getting Started

### Running Tests

```bash
# Run all tests
make test-all

# Run specific category
make test-unit
make test-integration
make test-e2e

# Run with coverage
make test-coverage

# Run in parallel
make test-parallel
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
- [Coverage Tracking](./COVERAGE.md)
