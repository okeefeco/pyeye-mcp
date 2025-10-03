<!--
Audience: Claude Code
Purpose: Define mandatory requirements for pull requests including security, testing, and quality standards
When to update: When PR requirements or quality standards change
-->

# Pull Request Requirements and Quality Standards

## Security Tooling Requirements

### MANDATORY Security Checks

**These must pass before ANY PR can merge:**

1. **detect-secrets** - No hardcoded credentials
2. **bandit** - No Python security vulnerabilities
3. **pip-audit** - No vulnerable dependencies (OSV database)
4. **safety** - No vulnerable dependencies (Safety DB)

### Handling Security Findings

**If security issues are found:**

1. NEVER commit the vulnerability
2. Create an issue immediately
3. Fix before proceeding
4. Document the fix in commit message

## Test Requirements for Pull Requests

### MANDATORY: Every PR Must Include Tests

**Every PR that adds or modifies code MUST include:**

1. **Unit tests** for new functions/methods
2. **Integration tests** for new features
3. **Regression tests** for bug fixes
4. **Coverage must not drop** - CI will fail if coverage drops below 85%

**Before marking any PR as ready:**

```bash
# MANDATORY: Run ALL tests with coverage (catches breaking changes to existing code)
# This would have caught the ProjectCache/GranularCache issue in PR #77
pytest --cov=src/pycodemcp --cov-fail-under=85

# Note: Pre-commit does NOT run tests - you MUST run them manually!
```

## Development Setup Reminders

### Virtual Environment Per Worktree

**Each worktree MUST have its own `.venv`:**

```bash
# After creating worktree
cd ../python-code-intelligence-mcp-work/feat-42-new-feature
uv venv
uv pip install -e ".[dev]"
# Pre-commit hooks work automatically - no installation needed!
```

**NEVER copy or symlink venvs between worktrees** - this defeats isolation.

## Branch Protection Rules

**The `main` branch is protected. All changes require:**

- At least 1 approval
- All CI checks passing
- All conversations resolved

## Performance Test Requirements

**ALWAYS use the performance testing framework:**

```python
# ❌ WRONG
assert elapsed < 0.2  # Fails on slow CI

# ✅ RIGHT
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold
```

See `tests/utils/performance.py` for `CommonThresholds` constants.

## Windows Compatibility Requirements

**When writing tests that handle platform differences:**

1. Use `@pytest.mark.skipif(os.name == "nt")` for Unix-specific tests
2. Always use `.as_posix()` for paths in assertions
3. Be aware that `chmod` doesn't work the same on Windows

## Coverage Requirements

- **Current threshold**: 85% (enforced by CI)
- **New code target**: >90% coverage
- **Bug fixes**: MUST include regression tests
- **ALWAYS run full test suite before pushing** (learned from PR #77)
