# Contributing to Python Code Intelligence MCP Server

First off, thank you for considering contributing to Python Code Intelligence MCP Server! It's people like you that make this tool better for everyone.

This document provides guidelines for contributing to the project. These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Your First Code Contribution](#your-first-code-contribution)
  - [Pull Requests](#pull-requests)
- [Development Process](#development-process)
  - [Setting Up Your Environment](#setting-up-your-environment)
  - [Making Changes](#making-changes)
  - [Running Tests](#running-tests)
  - [Code Style](#code-style)
- [Project Structure](#project-structure)
- [Community](#community)
- [Recognition](#recognition)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check [existing issues](https://github.com/okeefeco/python-code-intelligence-mcp/issues) as you might find that you don't need to create one. When you are creating a bug report, please include as many details as possible using the issue template.

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, please include:

- **Use case** - Explain why this enhancement would be useful
- **Proposed solution** - Describe how you envision it working
- **Alternatives considered** - What other solutions did you consider?
- **Additional context** - Add any other context or screenshots

### Your First Code Contribution

Unsure where to begin contributing? You can start by looking through these issues:

- [Issues labeled "good first issue"](https://github.com/okeefeco/python-code-intelligence-mcp/labels/good%20first%20issue) - issues which should only require a few lines of code
- [Issues labeled "help wanted"](https://github.com/okeefeco/python-code-intelligence-mcp/labels/help%20wanted) - issues which need extra attention

### Pull Requests

The process described here has several goals:

- Maintain the project's quality
- Fix problems that are important to users
- Engage the community in working toward the best possible product
- Enable a sustainable system for maintainers to review contributions

Please follow these steps for your contribution:

1. **Create an issue first** - Before starting work, create or find an issue describing what you plan to do
2. **Fork the repository** and create your branch from `main`
3. **Make your changes** - See [Development Process](#development-process) below
4. **Add tests** - If you've added code, add tests
5. **Ensure tests pass** - Run the full test suite
6. **Update documentation** - If you've changed APIs, update the relevant documentation
7. **Submit the pull request** - Link it to the issue using "Fixes #issue-number"
8. **Address review feedback** - Maintainers will review your PR and may request changes

## Development Process

### Setting Up Your Environment

#### Prerequisites

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- Git

#### Quick Start

1. Fork and clone the repository:

   ```bash
   git clone git@github.com:your-username/python-code-intelligence-mcp.git
   cd python-code-intelligence-mcp
   ```

2. Create a virtual environment and install dependencies:

   ```bash
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   uv pip install -e ".[dev]"
   ```

3. Install pre-commit hooks:

   ```bash
   pre-commit install
   ```

For detailed setup instructions, including worktree configuration and advanced development workflows, see [Development Setup Guide](docs/development-setup.md).

### Making Changes

1. **Create a feature branch**:

   ```bash
   # Use descriptive branch names with issue numbers
   git checkout -b feat/42-add-fastapi-plugin
   git checkout -b fix/43-cache-memory-leak
   git checkout -b docs/44-update-readme
   ```

2. **Write your code**:
   - Follow the existing code style
   - Add docstrings to new functions/classes
   - Use type hints
   - Keep changes focused and atomic

3. **Write tests**:
   - All new features must have tests
   - Bug fixes should include regression tests
   - Aim for >90% coverage on new code

4. **Commit your changes**:

   ```bash
   # Use conventional commit format
   git commit -m "feat(plugins): add FastAPI plugin support"
   git commit -m "fix(cache): resolve memory leak in file watcher"
   git commit -m "docs: update installation instructions"
   ```

### Running Tests

Run the test suite before submitting:

```bash
# Run all tests with coverage
uv run pytest --cov=src/pycodemcp --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_specific.py

# Run with verbose output
uv run pytest -v
```

For comprehensive testing guidelines, including performance testing and cross-platform considerations, see [Testing Guide](docs/testing-guide.md).

### Code Style

This project uses several tools to maintain code quality:

- **black** - Code formatting
- **ruff** - Linting
- **mypy** - Type checking
- **pre-commit** - Git hooks for automatic checks

Pre-commit hooks will automatically format your code and catch common issues. To run manually:

```bash
pre-commit run --all-files
```

#### Python Style Guidelines

- Follow PEP 8
- Use descriptive variable names
- Write docstrings for all public functions/classes
- Use type hints wherever possible
- Keep functions small and focused

## Project Structure

```text
src/pycodemcp/
├── server.py              # Main MCP server implementation
├── project_manager.py     # Multi-project management
├── namespace_resolver.py  # Distributed package handling
├── config.py             # Configuration system
├── cache.py              # Caching and file watching
├── analyzers/            # Code analysis engines
│   └── jedi_analyzer.py # Jedi integration
└── plugins/              # Framework plugins
    ├── base.py          # Plugin base class
    ├── django.py        # Django support
    ├── pydantic.py      # Pydantic models
    └── flask.py         # Flask support
```

## Community

### Getting Help

- **GitHub Issues** - For bug reports and feature requests
- **GitHub Discussions** - For questions and general discussion
- **Documentation** - Check the [docs](docs/) folder for guides

### Communication Guidelines

- Be respectful and considerate
- Be patient - maintainers are volunteers
- Search existing issues before creating new ones
- Provide context and be specific in questions
- Celebrate contributions of all sizes

## Recognition

We value all contributions! Contributors are recognized in several ways:

- Your name in the commit history
- Mention in release notes for significant contributions
- The satisfaction of improving a tool used by developers worldwide

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](LICENSE) that covers the project.

## Questions?

Feel free to open an issue with your question or reach out to the maintainers. We're here to help!

---

Thank you again for your interest in contributing to Python Code Intelligence MCP Server! 🎉
