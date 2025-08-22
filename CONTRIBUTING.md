# Contributing to Python Code Intelligence MCP Server

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

## 🚨 CRITICAL: GitHub Issue-Based Workflow (MANDATORY)

### All Work MUST Follow This Process

1. **BEFORE ANY WORK BEGINS**:

   ```bash
   # Check for existing issues
   gh issue list --state open

   # If no issue exists for the work, CREATE ONE or ask user to create it
   gh issue create --title "Brief description" --body "Details"
   ```

2. **BRANCH STRATEGY (REQUIRED)**:

   ```bash
   # Format: type/issue-number-brief-description
   # Examples:
   git checkout -b fix/22-merge-strategy-docs
   git checkout -b feat/23-add-validation
   git checkout -b docs/24-update-readme
   ```

3. **DISCOVERED PROBLEMS**:
   - If you find ANY bug, issue, or improvement opportunity:
     1. STOP current work
     2. Create or request issue creation
     3. Only proceed with fix after issue exists
   - Example response: "I found a bug in the validation logic. Let me create issue #25 to track this before fixing it."

4. **VALIDATION BEFORE STARTING**:

   ```bash
   # ALWAYS run these checks before starting work:
   gh issue view <issue-number>  # Verify issue exists and understand requirements
   git status                     # Ensure clean working directory
   git checkout main              # Start from main
   git pull origin main           # Get latest changes
   git checkout -b <branch-name>  # Create feature branch
   ```

5. **PR CREATION**:
   - Always reference issue: "Fixes #<issue-number>" or "Addresses #<issue-number>"
   - PR title should match branch naming convention
   - Never merge without issue reference

### Examples of Required Workflow

❌ **WRONG**: "I'll fix this typo real quick"
✅ **RIGHT**: "I found a typo. Let me create issue #26 for this, then fix it on branch `docs/26-fix-typo`"

❌ **WRONG**: Starting work immediately when user mentions a problem
✅ **RIGHT**: "I understand the issue. Let's create a GitHub issue to track this properly, then I'll work on it"

❌ **WRONG**: Making changes on main branch
✅ **RIGHT**: Always create issue-specific feature branch

### Issue Templates to Use

For bugs:

```markdown
## Bug Description
[Clear description of the issue]

## Steps to Reproduce
1. [Step 1]
2. [Step 2]

## Expected Behavior
[What should happen]

## Actual Behavior
[What actually happens]
```

For features:

```markdown
## Feature Description
[What needs to be added]

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Implementation Notes
[Any technical details]
```

## Development Setup

### Prerequisites

- Python 3.10+
- uv (for package management)
- Git

### Initial Setup

1. **Clone the repository**

```bash
git clone git@github.com:okeefeco/python-code-intelligence-mcp.git
cd python-code-intelligence-mcp
```

1. **Create a virtual environment**

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

1. **Install development dependencies**

```bash
uv pip install -e ".[dev]"
```

1. **Install pre-commit hooks**

```bash
pre-commit install
pre-commit install --hook-type commit-msg  # For commit message validation
```

1. **Create secrets baseline**

```bash
detect-secrets scan > .secrets.baseline
```

## Local Development Tools

### Personal Configuration Files (Claude Code)

For user-specific settings that shouldn't be committed (like worktree paths, personal aliases, etc.), use Claude's local configuration system:

1. **Create your personal config file**:

   ```bash
   mkdir -p ~/.claude/projects/{github-org}
   touch ~/.claude/projects/{github-org}/{repo-name}.md

   # For this project:
   mkdir -p ~/.claude/projects/okeefeco
   touch ~/.claude/projects/okeefeco/python-code-intelligence-mcp.md
   ```

2. **Structure**: The `{org}/{repo}` pattern prevents naming conflicts between:
   - Forks (e.g., `upstream/repo` vs `yourfork/repo`)
   - Different organizations with same repo names
   - Personal vs work projects

3. **Import in CLAUDE.md**: The project's CLAUDE.md includes an optional import that fails gracefully if your personal file doesn't exist

4. **Example personal config content**:

   ```markdown
   # Python Code Intelligence MCP - Local Settings

   ## Worktree Locations
   - Main: /home/user/GitHub/python-code-intelligence-mcp
   - Work: /home/user/GitHub/python-code-intelligence-mcp-work/

   ## Personal Aliases
   alias mcp-main="cd /home/user/GitHub/python-code-intelligence-mcp"
   alias mcp-work="cd /home/user/GitHub/python-code-intelligence-mcp-work"
   ```

### Git Worktrees (Recommended)

Git worktrees allow you to have multiple branches checked out simultaneously in different directories. This is especially useful for:

- Keeping the main branch stable for running the MCP server
- Working on multiple features/fixes without stashing
- Quick context switching between tasks

1. **Setup worktree with virtual environment**:

   ```bash
   # Create a directory for worktrees
   mkdir ../python-code-intelligence-mcp-work

   # Add a worktree (directory name matches branch pattern)
   git worktree add ../python-code-intelligence-mcp-work/feat-42-new-feature -b feat/42-new-feature main

   # Set up isolated virtual environment (required for each worktree)
   cd ../python-code-intelligence-mcp-work/feat-42-new-feature
   uv venv
   uv pip install -e ".[dev]"
   ```

2. **Recommended structure**:

   ```text
   python-code-intelligence-mcp/        # Main repo (keep on main branch)
   ├── .venv/                           # Main's virtual environment
   python-code-intelligence-mcp-work/   # Worktrees directory
   ├── feat-42-new-feature/             # Feature branch worktree
   │   ├── .venv/                       # Isolated virtual environment
   ├── fix-43-bug-name/                 # Bugfix branch worktree
   │   ├── .venv/                       # Isolated virtual environment
   └── docs-44-update-readme/           # Documentation branch worktree
       ├── .venv/                       # Isolated virtual environment
   ```

3. **Virtual Environment Strategy**:

   Each worktree gets its own `.venv` for complete isolation:
   - **Isolation**: Test dependency changes without affecting other branches
   - **Speed**: `uv` caches packages, so subsequent installs are fast (~10s)
   - **Safety**: Main branch stays stable even if a feature branch experiments
   - **IDE Support**: Each worktree's `.venv` is automatically detected

   Note: Do NOT copy/symlink venvs between worktrees - this defeats isolation and can cause issues.

4. **Worktree commands**:

   ```bash
   # List all worktrees
   git worktree list

   # Remove a worktree when done
   git worktree remove ../python-code-intelligence-mcp-work/feat-42

   # Prune stale worktree references
   git worktree prune
   ```

5. **Quick setup script** (optional):

   Create `setup-worktree.sh` in your main repo:

   ```bash
   #!/bin/bash
   # Usage: ./setup-worktree.sh feat 42 "add-new-feature"

   TYPE=$1
   ISSUE=$2
   DESC=$3
   BRANCH="$TYPE/$ISSUE-$DESC"
   DIR="../python-code-intelligence-mcp-work/$TYPE-$ISSUE-$DESC"

   git worktree add "$DIR" -b "$BRANCH" main
   cd "$DIR"
   uv venv
   uv pip install -e ".[dev]"
   echo "✅ Worktree ready at $DIR"
   ```

6. **Benefits**:
   - No need to stash changes when switching tasks
   - Main branch stays clean for testing/running
   - Each issue gets its own isolated workspace
   - Faster context switching

## Development Workflow

### Branch Protection

The `main` branch is protected. All changes must go through pull requests with:

- At least 1 approval
- All CI checks passing
- All conversations resolved

### Creating a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
# or
git checkout -b docs/documentation-update
```

### Pre-commit Checks

Before committing, pre-commit will automatically run:

- **Security scanning** (detect-secrets, bandit)
- **Code formatting** (black, isort)
- **Linting** (ruff)
- **Type checking** (mypy)
- **Documentation checks** (pydocstyle)

**IMPORTANT**: Pre-commit does NOT run tests. You MUST run tests manually:

```bash
# CRITICAL: Run ALL tests with coverage before pushing (not just your new tests!)
# This would have caught the ProjectCache/GranularCache issue in PR #77
pytest --cov=src/pycodemcp --cov-fail-under=85
```

To run manually:

```bash
pre-commit run --all-files
```

### Commit Messages

We use conventional commits. Format:

```text
type(scope): description

[optional body]

[optional footer]
```

Types:

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `perf`: Performance improvements

Examples:

```bash
git commit -m "feat(plugins): add FastAPI plugin support"
git commit -m "fix(cache): resolve file watcher memory leak"
git commit -m "docs: update installation instructions"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/pycodemcp --cov-report=term-missing

# Run specific test file
pytest tests/test_server.py

# Run with verbose output
pytest -v
```

#### Windows Test Compatibility

When writing tests that need to handle platform differences:

1. **File Permissions**

   Windows doesn't respect Unix-style chmod permissions the same way:
   - `chmod(0o000)` doesn't prevent file access on Windows
   - `chmod(0o555)` on directories doesn't prevent writes on Windows

   ```python
   import os
   import pytest

   # Skip permission tests on Windows
   @pytest.mark.skipif(os.name == "nt", reason="Windows handles permissions differently")
   async def test_read_file_permission_error(self, tmp_path):
       test_file = tmp_path / "no_read.txt"
       test_file.write_text("content")
       test_file.chmod(0o000)  # Doesn't work as expected on Windows

       with pytest.raises(PermissionError):
           await read_file_async(test_file)
   ```

2. **Temporary Directory Operations**

   Some tests that manipulate current working directory and temporary directories can cause stack overflow during cleanup on Windows CI:

   ```python
   # Be careful with tests that change cwd multiple times
   @pytest.mark.skipif(os.name == "nt", reason="Potential stack overflow on Windows CI")
   def test_complex_directory_operations(self, tmp_path):
       # Tests involving deep directory structures or multiple cwd changes
       pass
   ```

3. **Path Expansion**

   The `~/path` expansion works differently on Windows:

   ```python
   from pathlib import Path

   # Use Path.expanduser() explicitly
   def test_home_directory_paths(self):
       home_path = Path("~/.config/app").expanduser()
       # Make assertions platform-agnostic
       assert home_path.is_absolute()
   ```

4. **Common Patterns for Cross-Platform Tests**

   ```python
   import os
   import pytest
   from pathlib import Path

   class TestCrossPlatform:
       def test_basic_functionality(self):
           # Test core functionality that should work everywhere
           pass

       @pytest.mark.skipif(os.name == "nt", reason="Unix-specific behavior")
       def test_unix_specific(self):
           # Test Unix-specific features
           pass

       @pytest.mark.skipif(os.name != "nt", reason="Windows-specific behavior")
       def test_windows_specific(self):
           # Test Windows-specific features
           pass
   ```

**Reference**: See issue #120 (coverage improvement epic) and PR #122 for examples of fixing Windows test compatibility issues.

### Type Checking

```bash
mypy src/pycodemcp
```

### Security Checks

```bash
# Run bandit
bandit -r src/ -ll

# Check dependencies
safety check

# Scan for secrets
detect-secrets scan
```

## Cross-Platform Development

### Path Handling Guidelines

When working with file paths in this project, it's crucial to ensure cross-platform compatibility. Python's `pathlib` provides excellent tools, but they must be used correctly to avoid platform-specific issues.

#### Key Principles

1. **Always use `.as_posix()` for paths that will be stored or compared as strings**
   - Template names, configuration paths, dictionary keys
   - Any path displayed to users or stored in data structures
   - Paths used in assertions during testing

2. **Use path utilities for consistency**
   - Import from `src/pycodemcp/path_utils.py`
   - Use `path_to_key()` for dictionary keys
   - Use `ensure_posix_path()` to convert any path to forward slashes
   - Use `paths_equal()` for platform-safe path comparison

3. **Common Pitfalls to Avoid**

```python
# ❌ WRONG - Uses OS-native separators (breaks on Windows)
template_name = str(template_file.relative_to(template_dir))
# Windows: "admin\\dashboard.html"
# Unix: "admin/dashboard.html"

# ✅ CORRECT - Always forward slashes on all platforms
template_name = template_file.relative_to(template_dir).as_posix()
# All platforms: "admin/dashboard.html"

# ❌ WRONG - Direct string conversion for comparison
if str(path1) == str(path2):
    ...

# ✅ CORRECT - Use path utilities
from pycodemcp.path_utils import paths_equal
if paths_equal(path1, path2):
    ...
```

#### When to Use Each Method

| Use Case | Method | Example |
|----------|--------|---------|
| Display paths | `.as_posix()` | `print(f"File: {path.as_posix()}")` |
| Dictionary keys | `path_to_key()` | `cache[path_to_key(file_path)]` |
| Config values | `.as_posix()` | `config["template_dir"] = path.as_posix()` |
| Path comparison | `paths_equal()` | `if paths_equal(p1, p2):` |
| JSON/YAML storage | `.as_posix()` | `data["path"] = path.as_posix()` |
| Test assertions | `.as_posix()` | `assert result == expected.as_posix()` |

#### Testing Considerations

1. **CI runs on Windows, macOS, and Linux** - Your code must work on all three
2. **Common Windows test failures:**
   - `AssertionError: 'path/to/file' != 'path\\to\\file'`
   - Template paths with backslashes
   - Config file paths with mixed separators

3. **Best practices for tests:**

   ```python
   # Use pathlib for test fixtures
   from pathlib import Path

   test_file = Path("tests/fixtures/sample.py")

   # Always use .as_posix() in assertions
   assert result["file"] == test_file.as_posix()

   # Use path utilities for comparisons
   from pycodemcp.path_utils import paths_equal
   assert paths_equal(result_path, expected_path)
   ```

#### Related Resources

- PR #121 - Flask plugin cross-platform fixes (good reference implementation)
- `src/pycodemcp/path_utils.py` - Path utility functions
- Issue #110 - Original issue that discovered these problems

## Creating a Pull Request

1. **Push your branch**

```bash
git push -u origin feature/your-feature-name
```

1. **Create PR via CLI**

```bash
gh pr create --title "feat: your feature" --body "Description of changes"
```

1. **PR Requirements**

- Clear title and description
- Link to related issue (if applicable)
- All CI checks passing
- **MANDATORY**: Tests for ALL new functionality (coverage must not drop below 75%)
- **MANDATORY**: Tests for ALL bug fixes (include regression tests)
- Documentation updates (if needed)

### ⚠️ Test Requirements (MANDATORY)

**Every PR that adds or modifies code MUST include:**

1. **Unit tests** for new functions/methods
2. **Integration tests** for new features
3. **Regression tests** for bug fixes
4. **Coverage must not drop** - CI will fail if coverage drops below 75%

**Before marking any PR as ready:**

```bash
# MANDATORY: Run ALL tests with coverage (catches breaking changes to existing code)
pytest --cov=src/pycodemcp --cov-fail-under=85

# Note: This single command runs all tests AND checks coverage
# Do NOT just run tests for your new code - run the entire suite!
```

## Merge Strategy

### Our Approach

This project uses **regular merge commits** (not squash merges) to preserve development history and maintain full traceability.

### Why We Don't Use Squash Merge

- **Preserves development history**: Each commit tells part of the story
- **Better debugging**: `git bisect` works more effectively with granular commits
- **Proper attribution**: Individual commits show the evolution of the solution
- **No tracking issues**: Git properly recognizes merged branches (no confusing warnings)

### Why We Don't Recommend Rebase After Push

- **Safety**: Rebase rewrites history, which can cause problems for other developers who have pulled the branch
- **Collaboration**: Force pushing after rebase can overwrite others' work
- **Traceability**: Original commit timestamps and hashes are preserved

### Guidelines

1. **Keep commits clean and logical** - Since we preserve history, make each commit meaningful
2. **Use descriptive commit messages** - Follow our conventional commit format
3. **It's OK to have "fix" commits** - They show the review process and iterations
4. **Never force push to shared branches** - Especially after others have reviewed or pulled

### Merging Process

When your PR is approved:

```bash
# Regular merge (preserves all commits)
gh pr merge <PR-NUMBER> --merge

# NOT recommended:
# gh pr merge <PR-NUMBER> --squash  ❌
# gh pr merge <PR-NUMBER> --rebase  ❌ (especially after push)
```

### For Maintainers: GitHub Settings

To enforce this strategy, disable squash merging in repository settings:

1. Go to Settings → General → Pull Requests
2. **Enable**: "Allow merge commits" ✅
3. **Disable**: "Allow squash merging" ❌
4. **Disable**: "Allow rebase merging" ❌ (optional, but recommended)

## Code Style Guidelines

### Python Style

- Follow PEP 8 (enforced by black and ruff)
- Line length: 100 characters
- Use type hints for all functions
- Google-style docstrings

### Docstring Example

```python
def find_symbol(name: str, fuzzy: bool = False) -> List[Dict[str, Any]]:
    """Find symbol definitions in the project.

    Args:
        name: Symbol name to search for
        fuzzy: Enable fuzzy matching

    Returns:
        List of symbol matches with location information

    Raises:
        ValidationError: If symbol name is invalid
    """
```

## Project Structure

```text
src/pycodemcp/
├── server.py           # Main MCP server
├── project_manager.py  # Multi-project management
├── cache.py           # Caching layer
├── config.py          # Configuration
├── analyzers/         # Analysis engines
└── plugins/           # Framework plugins
```

## Testing Guidelines

### 🚨 MANDATORY Test Requirements

**ALL code changes MUST include tests. No exceptions.**

1. **New Features**: Must have comprehensive tests covering:
   - Happy path scenarios
   - Edge cases
   - Error conditions
   - Integration with existing code

2. **Bug Fixes**: Must include:
   - Test that reproduces the bug (fails before fix)
   - Test that verifies the fix (passes after fix)
   - Regression tests to prevent reoccurrence

3. **Refactoring**: Must maintain or improve test coverage

4. **Coverage Requirements**:
   - Minimum 85% coverage (enforced by CI)
   - New code should aim for >90% coverage
   - Use `# pragma: no cover` sparingly and with justification

### Test Structure

- Mirror the source structure in `tests/`
- Use pytest fixtures for common setup
- Mock external dependencies
- Test both success and failure cases

### Test Example

```python
def test_find_symbol_basic():
    """Test basic symbol finding."""
    result = find_symbol("MyClass", project_path="/test")
    assert len(result) > 0
    assert result[0]["name"] == "MyClass"

def test_find_symbol_invalid_input():
    """Test with invalid input."""
    with pytest.raises(ValidationError):
        find_symbol("", project_path="/test")
```

### Test Coverage Improvement Process

When adding tests to modules with low coverage, follow this systematic approach:

#### 1. Analysis Phase

```bash
# Check current coverage for specific modules
pytest --cov=src/pycodemcp/module_name --cov-report=term-missing

# Identify missing lines
pytest --cov=src/pycodemcp/module_name --cov-report=term-missing | grep "Missing"

# Generate detailed HTML report for analysis
pytest --cov=src/pycodemcp/module_name --cov-report=html
# Open htmlcov/index.html in browser
```

#### 2. Test Writing Patterns

**For Utility Modules:**

- Test all public functions with multiple scenarios
- Include edge cases: empty inputs, Unicode, very long inputs
- Platform-specific behavior: Windows vs Unix differences
- Error conditions: Invalid inputs, permission errors, etc.

**For Async Modules:**

- Use `@pytest.mark.asyncio` class decorators for async test classes
- Test concurrency: Batch operations, limits, timeouts
- Error propagation: How async functions handle and propagate errors
- Integration scenarios: Combining multiple async operations

#### 3. Test Organization

```python
# Group tests by functionality using test classes
@pytest.mark.asyncio
class TestReadFileAsync:
    """Test read_file_async function."""

    async def test_read_file_basic(self, tmp_path):
        """Test basic file reading."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")
        result = await read_file_async(test_file)
        assert result == "content"

    async def test_read_file_unicode(self, tmp_path):
        """Test Unicode content handling."""
        test_file = tmp_path / "unicode.txt"
        test_file.write_text("Hello 世界", encoding="utf-8")
        result = await read_file_async(test_file)
        assert result == "Hello 世界"

    async def test_read_file_not_found(self):
        """Test error handling for missing files."""
        with pytest.raises(FileNotFoundError):
            await read_file_async(Path("nonexistent.txt"))
```

#### 4. Coverage Verification

```bash
# Target-specific coverage check
pytest tests/test_module.py --cov=src/pycodemcp/module --cov-report=term

# Verify no regressions in full test suite
pytest --cov=src/pycodemcp --cov-fail-under=85
```

#### 5. Common High-Coverage Patterns

**Cross-Platform Testing:**

```python
import os
import pytest

class TestCrossPlatform:
    def test_basic_functionality(self):
        # Core functionality that works everywhere
        pass

    @pytest.mark.skipif(os.name == "nt", reason="Unix-specific")
    def test_unix_behavior(self):
        # Unix-specific tests
        pass
```

**Async Function Testing:**

```python
@pytest.mark.asyncio
class TestAsyncOperations:
    async def test_normal_execution(self):
        # Test happy path
        pass

    async def test_error_handling(self):
        # Test with mock exceptions
        with patch('module.dependency') as mock_dep:
            mock_dep.side_effect = Exception("Test error")
            with pytest.raises(Exception):
                await async_function()

    async def test_concurrency(self):
        # Test multiple async operations
        tasks = [async_function() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 5
```

**File Operation Testing:**

```python
class TestFileOperations:
    def test_various_file_contents(self, tmp_path):
        # Test empty files
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()

        # Test Unicode content
        unicode_file = tmp_path / "unicode.txt"
        unicode_file.write_text("Test 🚀", encoding="utf-8")

        # Test large files
        large_file = tmp_path / "large.txt"
        large_file.write_text("x" * 10000)

    def test_error_conditions(self, tmp_path):
        # Test permission errors, missing files, etc.
        pass
```

#### 6. Final Validation

Before submitting your PR:

1. **Check coverage target met**: `pytest --cov=src/pycodemcp/your_module --cov-report=term`
2. **Verify no regressions**: `pytest --cov=src/pycodemcp --cov-fail-under=85`
3. **Test cross-platform compatibility**: Ensure tests pass on Windows, macOS, Linux
4. **Review test quality**: Meaningful tests, not just coverage for coverage's sake

**Reference**: See issue #120 (coverage improvement epic) and PR #122 for examples of bringing modules from 0%/50% to 100% coverage.

## Coverage Goals and Requirements

### 📈 Progressive Coverage Targets

We're committed to continuously improving our test coverage through progressive milestones:

- **Phase 1**: 85% ✅ (Current CI threshold - achieved)
- **Phase 2**: 85% 🎯 (Active target)
- **Phase 3**: 90% 🚀 (Future goal when project is widely adopted)

**Current Coverage**: ~86% (See [codecov badge](https://codecov.io/gh/okeefeco/python-code-intelligence-mcp) for live status)

### Coverage Improvement Strategy

#### Ratchet Mechanism

Every PR must maintain or improve coverage - we never go backwards:

- Check current coverage before starting work: `pytest --cov=src/pycodemcp --cov-report=term`
- Your PR's coverage should be ≥ the baseline
- Aim to improve coverage by addressing low-coverage files when you touch them

#### Priority Areas for Improvement

Files currently below 75% that need attention:

- Files with 0-50% coverage must be improved to 85%+ when modified
- Files with 50-75% coverage should be improved when touched
- New code must have >90% coverage

#### Per-PR Guidelines

1. **Before starting work**: Note the current coverage percentage
2. **When modifying low-coverage files**: Improve them significantly
3. **For new features**: Include comprehensive tests (>90% coverage)
4. **For bug fixes**: Add regression tests that would have caught the bug
5. **Before submitting PR**: Verify coverage hasn't decreased

### Running Coverage Locally

```bash
# Check overall coverage
pytest --cov=src/pycodemcp --cov-report=term

# Check coverage with detailed line-by-line report
pytest --cov=src/pycodemcp --cov-report=term-missing

# Generate HTML coverage report for detailed inspection
pytest --cov=src/pycodemcp --cov-report=html
# Open htmlcov/index.html in your browser

# Check coverage for specific module
pytest --cov=src/pycodemcp/plugins/flask --cov-report=term-missing tests/plugins/test_flask.py

# Fail if coverage drops below current threshold
pytest --cov=src/pycodemcp --cov-fail-under=85
```

### When We Reach 85%

Once we consistently maintain 90% coverage:

1. Update CI threshold in `.github/workflows/ci.yml` from 85% to 90%
2. Celebrate the milestone! 🎉
3. Plan approach for Phase 3 (90% coverage)

For detailed coverage tracking and improvement guides, see [docs/COVERAGE.md](docs/COVERAGE.md).

## Getting Help

- Check existing [issues](https://github.com/okeefeco/python-code-intelligence-mcp/issues)
- Review the [documentation](README.md)
- Ask questions in discussions
- Contact maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
