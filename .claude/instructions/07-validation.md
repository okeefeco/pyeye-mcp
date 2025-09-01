<!--
Audience: Claude Code
Purpose: Define validation and testing requirements beyond core rules
When to update: When testing strategies or validation tools change
-->

# Validation and Testing Requirements

## This Project Uses `uv` Package Manager

**CRITICAL**: ALWAYS prefix Python commands with `uv run`:

- ❌ **WRONG**: `pytest tests/test_file.py`
- ✅ **RIGHT**: `uv run pytest tests/test_file.py`

This applies to ALL Python tools:

- `uv run pytest` - Run tests
- `uv run black` - Format code
- `uv run ruff` - Lint code
- `uv run mypy` - Type checking
- `uv run python` - Run Python scripts

**Why**: Dependencies are installed in the uv-managed virtual environment, not globally.

## Test-Driven Development Approach

1. **Write tests FIRST** (TDD approach recommended)
2. **Implement the feature/fix**
3. **Run tests locally with coverage**
4. **Fix any failing tests or coverage issues**
5. **NEVER commit code without tests**

## Coverage Goals

- **Current threshold**: 85% (enforced by CI)
- **New code target**: >90% coverage
- **Bug fixes**: MUST include regression tests
- **Refactoring**: Must maintain or improve coverage

## Performance Testing

**NEVER write naive timing assertions**:

```python
# ❌ WRONG
assert elapsed < 0.2  # Fails on slow CI

# ✅ RIGHT
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

threshold = PerformanceThresholds(
    base=100.0,      # Local dev
    linux_ci=150.0,   # Linux CI
    macos_ci=300.0,   # macOS CI
    windows_ci=300.0  # Windows CI
)
assert_performance_threshold(elapsed_ms, threshold, "Operation name")
```

## Pre-commit Hooks

Pre-commit runs automatically on commit and includes:

- **Security scanning** (detect-secrets, bandit, pip-audit)
- **Code formatting** (black, isort)
- **Linting** (ruff)
- **Type checking** (mypy)
- **Documentation checks** (pydocstyle)
- **Cross-platform path checking** (custom hook)

**IMPORTANT**: Pre-commit does NOT run tests. You MUST run tests manually.

## Security Validation

### Dependency Scanning

- `pip-audit` - OSV database
- `safety` - Safety DB
- Both run via pre-commit

### Static Analysis

- `bandit` - Python security patterns
- `detect-secrets` - Credential detection

### If Security Issues Found

1. **Never commit the vulnerability**
2. **Create issue immediately**
3. **Fix before proceeding**
4. **Document in commit message**

## Cross-Platform Testing

### Windows Compatibility

- File permissions work differently
- Path separators need `.as_posix()`
- Some tests may need `@pytest.mark.skipif(os.name == "nt")`

### Path Handling

- **Always** use `.as_posix()` for display/storage
- **Never** use `str(path)` for comparisons
- Use `path_utils.py` helpers

## Validation Commands Summary

```bash
# Before ANY commit or task completion:
uv run pytest --cov=src/pycodemcp --cov-fail-under=85

# Run specific test file
uv run pytest tests/test_specific.py

# Run with verbose output
uv run pytest -v

# Check type hints
uv run mypy src/pycodemcp

# Run security checks
uv run pip-audit
uv run safety check
uv run bandit -r src/

# Format code (usually automatic via pre-commit)
uv run black src/
uv run ruff check src/
```

## CI/CD Validation

CI runs on:

- **Platforms**: Windows, macOS, Linux
- **Python versions**: 3.10, 3.11, 3.12
- **All PRs**: Must pass all checks

CI will fail if:

- Coverage drops below 85%
- Any test fails
- Security issues detected
- Linting errors
- Type checking fails
