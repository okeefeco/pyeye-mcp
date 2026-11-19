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
import importlib

from pyeye.module import Class

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
import time

from tests.utils.performance import CommonThresholds, assert_performance_threshold

start = time.perf_counter()
...  # the operation
elapsed_ms = (time.perf_counter() - start) * 1000
assert_performance_threshold(elapsed_ms, CommonThresholds.GOTO_DEFINITION_P95, "Goto definition")
```

### 4. Cross-Platform Paths

**Problem**: Platform-specific separators

```python
# ❌ WRONG
assert str(path) == "folder/file.py"  # Fails on Windows
```

**Solution**: Compare a path with a path through `paths_equal()` (#717); use
`.as_posix()` only to check a path's string form, such as one in a response

```python
from pyeye.path_utils import paths_equal

# ✅ CORRECT - two paths
assert paths_equal(result_path, tmp_path / "folder" / "file.py")

# ✅ CORRECT - a path as text
assert Path(response["file"]).relative_to(tmp_path).as_posix() == "folder/file.py"
```

### 5. Mock Patterns

**Problem**: Patching the name where it's defined, not where the code looks it up

```python
# module.py does `from datetime import datetime` at the top

# ❌ WRONG - module.py already holds its own reference to the real class
@patch("datetime.datetime")
def test_func(mock_dt):
    pass
```

**Solution**: Patch the name in the module that uses it

```python
# ✅ CORRECT - replaces the name module.py looks up
@patch("module.datetime")
def test_func(mock_dt):
    pass
```

## Pre-Generation Checklist

Before generating ANY test:

- [ ] Read the actual module to understand API
- [ ] Check existing test patterns in directory
- [ ] Plan imports (all at top, only what used)
- [ ] Identify performance requirements
- [ ] Choose real objects over mocking when possible
- [ ] Use descriptive test names

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
- Compare paths with `paths_equal()`; use `.as_posix()` for a path's string form

### CI Environment Considerations

CI runners are slower and noisier than a developer machine; never assert a fixed
time limit. See [Performance Testing](../testing/PERFORMANCE.md) for
`PerformanceThresholds`.

## Key Principles

1. **Test the behavior users care about**, not implementation details
2. **Make tests independent** - no shared state or order dependencies
3. **Use proper async patterns** - write `async def` tests; `asyncio_mode = "auto"`
   (pyproject) runs them, so `@pytest.mark.asyncio` is optional
4. **Handle platform differences** - tests must pass on all CI platforms
5. **Keep tests simple** - complex mocking usually indicates a design issue

## Success Metrics

Good tests have:

- CI passes on every platform
- Clear failure messages
- No flaky behavior
- Fast execution
- Easy maintenance

## References

- [pytest documentation](https://docs.pytest.org/)
- [unittest.mock documentation](https://docs.python.org/3/library/unittest.mock.html)
- Project's CONTRIBUTING.md for CI requirements
