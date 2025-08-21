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
# Run tests with coverage before committing
pytest --cov=src/pycodemcp --cov-fail-under=75
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
# Check coverage locally
pytest --cov=src/pycodemcp --cov-fail-under=75

# Ensure all tests pass
pytest -v
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
   - Minimum 75% coverage (enforced by CI)
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

## Getting Help

- Check existing [issues](https://github.com/okeefeco/python-code-intelligence-mcp/issues)
- Review the [documentation](README.md)
- Ask questions in discussions
- Contact maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
