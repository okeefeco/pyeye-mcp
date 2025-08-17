# Contributing to Python Code Intelligence MCP Server

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing to the project.

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
- Tests for new functionality
- Documentation updates (if needed)

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
