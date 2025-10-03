# Test Coverage Tracking and Guidelines

## 📊 Current Status

**Current Coverage**: 79% (as of January 2025)
**CI Threshold**: 75%
**Target**: 85% (Phase 2)

[![codecov](https://codecov.io/gh/okeefeco/pyeye-mcp/graph/badge.svg?token=XE5T93O8EC)](https://codecov.io/gh/okeefeco/pyeye-mcp)

## 🎯 Progressive Coverage Milestones

### Phase 1: 75% ✅ Achieved

- **Status**: Complete
- **CI Threshold**: Set and enforced
- **Achievement Date**: Project inception

### Phase 2: 85% 🎯 In Progress

- **Status**: Active target
- **Current**: 79%
- **Gap**: 6%
- **Strategy**: Focus on low-coverage files

### Phase 3: 90% 🚀 Future

- **Status**: Planned
- **Trigger**: When project reaches wide adoption
- **Focus**: Edge cases and error paths

## 📈 Coverage Improvement Opportunities

### Priority Files (Biggest Impact)

| File | Current Coverage | Lines to Cover | Impact on Total |
|------|-----------------|----------------|-----------------|
| `src/pyeye/plugins/flask.py` | 56% | ~119 lines | +3-4% |
| `src/pyeye/path_utils.py` | 0% | ~11 lines | +1% |
| `src/pyeye/async_utils.py` | 50% | ~17 lines | +1% |
| `src/pyeye/config.py` | 75% | ~35 lines | +1% |
| `src/pyeye/server.py` | 77% | ~76 lines | +2% |

### Quick Wins

Files with low coverage but easy to test:

- `path_utils.py`: Simple utility functions
- `async_utils.py`: Async wrappers
- `plugins/base.py`: Plugin interface

## 🛠️ How to Improve Coverage

### Running Coverage Locally

```bash
# Basic coverage report
uv run pytest --cov=src/pyeye --cov-report=term

# Detailed with missing lines
uv run pytest --cov=src/pyeye --cov-report=term-missing

# HTML report for exploration
uv run pytest --cov=src/pyeye --cov-report=html
# Open htmlcov/index.html

# Check specific module
uv run pytest --cov=src/pyeye/plugins/flask tests/plugins/test_flask.py

# Ensure minimum threshold
uv run pytest --cov=src/pyeye --cov-fail-under=75
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

2. **Don't Chase 100%**
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
- [ ] Coverage is ≥ baseline (currently 79%)
- [ ] New code has >90% coverage
- [ ] Modified files with <75% coverage have been improved
- [ ] No untested error paths in new code

## 🎉 When We Reach 85%

1. **Update CI Threshold**

   ```yaml
   # .github/workflows/ci.yml
   --cov-fail-under=85  # Update from 75
   ```

2. **Celebrate!**
   - Team announcement
   - Update README badges
   - Plan Phase 3 approach

3. **Maintain Momentum**
   - Keep ratchet mechanism
   - Continue improving low-coverage files
   - Set sights on 90%

## 📝 Tracking Progress

### Coverage History

- **January 2025**: 79% - Initial tracking, set 85% target
- (Updates will be added as milestones are reached)

### Files Improved

Track files that have been significantly improved:

- (List will be maintained as improvements are made)

## 🤝 Contributing to Coverage

1. **Pick a Low-Coverage File**: See priority list above
2. **Write Comprehensive Tests**: Follow patterns in this guide
3. **Submit PR**: Reference this tracking in PR description
4. **Update This Doc**: Add your contribution to history

## Resources

- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [Python testing best practices](https://docs.python-guide.org/writing/tests/)
- [Codecov dashboard](https://codecov.io/gh/okeefeco/pyeye-mcp)
