# Test Coverage Tracking and Guidelines

## 📊 Current Status

**CI Threshold**: <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end --> (pytest enforces it through pyproject's `addopts`)

The codecov badge shows live coverage.

[![codecov](https://codecov.io/gh/okeefeco/pyeye-mcp/graph/badge.svg?token=XE5T93O8EC)](https://codecov.io/gh/okeefeco/pyeye-mcp)

## 🎯 Coverage Milestones

The threshold was raised in stages to its current <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.

## 🔍 Finding Low-Coverage Files

Run `uv run pytest --cov-report=term-missing` and sort by the Miss column, or open the [Codecov dashboard](https://codecov.io/gh/okeefeco/pyeye-mcp).

## 🛠️ How to Improve Coverage

### Running Coverage Locally

pytest fails when coverage drops below <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end -->.

```bash
# Basic coverage report
uv run pytest --cov=src/pyeye --cov-report=term

# Detailed with missing lines
uv run pytest --cov=src/pyeye --cov-report=term-missing

# HTML report for exploration
uv run pytest --cov=src/pyeye --cov-report=html
# Open htmlcov/index.html

# Check specific module
uv run pytest --cov=pyeye.plugins.flask --cov-fail-under=0 tests/unit/plugins/test_flask_plugin.py

# Fails below the threshold; pyproject's addopts enforces it
uv run pytest
```

### Writing Effective Tests

#### 1. Test Structure Pattern

```python
def test_feature_happy_path():
    """Test normal operation."""
    # Given: Setup
    # When: Action
    # Then: Assert

def test_feature_edge_case():
    """Test boundary conditions."""

def test_feature_error_handling():
    """Test error scenarios."""
```

#### 2. Common Patterns to Test

##### Plugin Detection

```python
def test_plugin_detects_framework():
    """Test that plugin correctly identifies framework."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create marker files
        # Assert detection works
```

##### Error Handling

```python
def test_handles_invalid_input():
    """Test graceful error handling."""
    with pytest.raises(ValidationError):
        function_under_test(invalid_input)
```

##### Async Code

```python
@pytest.mark.asyncio
async def test_async_operation():
    """Test async functionality."""
    result = await async_function()
    assert result.expected_value
```

### Coverage Best Practices

1. **Focus on Critical Paths First**
   - Core functionality
   - User-facing APIs
   - Error handling

2. **Don't Chase Full Coverage**
   - Some code is hard to test (OS-specific, network)
   - Use `# pragma: no cover` sparingly with justification

3. **Test Behavior, Not Implementation**
   - Tests should survive refactoring
   - Focus on inputs/outputs, not internals

4. **Mock External Dependencies**

   ```python
   from unittest.mock import patch, MagicMock

   @patch('module.external_service')
   def test_with_mock(mock_service):
       mock_service.return_value = expected_data
   ```

## 📋 PR Checklist for Coverage

Before submitting a PR:

- [ ] Run `pytest --cov=src/pyeye --cov-report=term`
- [ ] Coverage is at or above <!-- fact:begin ci.coverage_threshold -->85%<!-- fact:end --> (pytest fails below it)
- [ ] Modified files' coverage didn't drop
- [ ] No untested error paths in new code

## ⬆️ Raising the Threshold

Change `--cov-fail-under` in pyproject's `addopts` and in `ci.yml` in one PR; `docs_facts.py generate` updates every page that binds `ci.coverage_threshold`.

## 🤝 Contributing to Coverage

1. **Pick a Low-Coverage File**: See [Finding Low-Coverage Files](#-finding-low-coverage-files)
2. **Write Comprehensive Tests**: Follow patterns in this guide
3. **Submit PR**: Reference this tracking in PR description

## Resources

- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Python testing best practices](https://docs.python-guide.org/writing/tests/)
- [Codecov dashboard](https://codecov.io/gh/okeefeco/pyeye-mcp)
