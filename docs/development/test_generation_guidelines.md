# Test Generation Guidelines

This document captures learnings from agent feedback loops to prevent common test generation failures.

## Common Failures and Solutions

### 1. Linting Failures (ARG002)

**Problem**: Unused fixture parameters

```python
# ❌ WRONG - causes ARG002 error
def test_something(self, mock_fixture, capsys):
    # mock_fixture never used
    output = capsys.readouterr()
```

**Solution**: Only include fixtures you use

```python
# ✅ CORRECT
def test_something(self, capsys):
    output = capsys.readouterr()
```

### 2. Import Order (E402)

**Problem**: Late imports after code

```python
# ❌ WRONG
cli_module = import_module('cli')
from pyeye.module import Class  # E402 error
```

**Solution**: All imports at top

```python
# ✅ CORRECT
from pyeye.module import Class
import importlib

cli_module = importlib.import_module('cli')
```

### 3. Performance Testing

**Problem**: Naive timing assertions fail in CI

```python
# ❌ WRONG - fails in CI
assert elapsed < 0.2
```

**Solution**: Use PerformanceThresholds

```python
# ✅ CORRECT
from tests.utils.performance import assert_performance_threshold, CommonThresholds

elapsed_ms = (time.perf_counter() - start) * 1000
assert_performance_threshold(elapsed_ms, CommonThresholds.SYMBOL_SEARCH_P95, "Search")
```

### 4. Cross-Platform Paths

**Problem**: Platform-specific separators

```python
# ❌ WRONG
assert str(path) == "folder/file.py"  # Fails on Windows
```

**Solution**: Use .as_posix()

```python
# ✅ CORRECT
assert path.as_posix() == "folder/file.py"
```

### 5. Mock Patterns

**Problem**: Mocking the wrong path

```python
# ❌ WRONG - datetime imported inside function
@patch('module.datetime')
def test_func(mock_dt):
    pass
```

**Solution**: Understand actual imports

```python
# ✅ CORRECT - mock where it's used
def test_func():
    with patch('module.function_that_uses_datetime'):
        pass
```

## Pre-Generation Checklist

Before generating ANY test:

- [ ] Read the actual module to understand API
- [ ] Check existing test patterns in directory
- [ ] Plan imports (all at top, only what used)
- [ ] Identify performance requirements
- [ ] Choose real objects over mocking when possible
- [ ] Use descriptive test names (3+ words)

## Test Behavior, Not Implementation

**Wrong**: Testing exact values

```python
assert session_id == "mcp_12345_2024-01-15T10:30:00"
```

**Right**: Testing behavior

```python
assert session_id.startswith("mcp_")
assert "T" in session_id  # Has timestamp
```

## When to Use Real Objects vs Mocks

### Use Real Objects

- File operations (use tmp_path)
- Simple data structures
- Path operations
- JSON parsing

### Use Mocks

- External API calls
- System calls
- Network operations
- Third-party libraries

## Platform Compatibility

### Windows Issues

- File permissions don't work as expected
- Use `pytest.mark.skipif(os.name == "nt")` when needed
- Always use `.as_posix()` for path comparisons

### CI Environment Considerations

- Performance varies greatly
- Never use fixed time thresholds
- Use PerformanceThresholds with platform-specific values

## Validation Script Usage

Run before committing:

```bash
python scripts/validate_test_code.py tests/
```

Catches:

- Import order violations
- Unused fixtures
- Naive timing assertions
- Poor naming
- Common indentation issues

## Key Principles

1. **Test the behavior users care about**, not implementation details
2. **Make tests independent** - no shared state or order dependencies
3. **Use proper async patterns** - @pytest.mark.asyncio for async tests
4. **Handle platform differences** - tests must pass on all CI platforms
5. **Keep tests simple** - complex mocking usually indicates a design issue

## Success Metrics

Good tests have:

- 100% CI pass rate across platforms
- Clear failure messages
- No flaky behavior
- Fast execution
- Easy maintenance

## References

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
- Project's CONTRIBUTING.md for CI requirements
