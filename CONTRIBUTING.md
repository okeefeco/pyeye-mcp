# Contributing to PyEye Server

First off, thank you for considering contributing to PyEye Server! It's people like you that make this tool better for everyone.

This document provides guidelines for contributing to the project. Most of it is guidance, so use your best judgment. The [contribution policy](#contribution-policy) below is the exception: it is a rule.

## Contribution Policy

We welcome bug reports, ideas and fixes, but we don't accept unsolicited pull requests.

1. **Start with an issue.** Open a new issue, or comment on an existing one, to say what you'd like to work on.
2. **Wait to be assigned.** A maintainer will reply and, if the work fits the project, assign the issue to you.
3. **Then open your pull request**, linked to that issue with `Fixes #<issue-number>`.

Pull requests that aren't linked to an issue assigned to their author may be closed without review. This isn't a judgement on the work: it keeps review time for changes we've agreed on together, and makes sure nobody spends effort on something we can't merge.

## Table of Contents

- [Contribution Policy](#contribution-policy)
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

Everyone participating in this project is expected to be respectful and constructive. Please report unacceptable behavior to the project maintainers.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check [existing issues](https://github.com/okeefeco/pyeye-mcp/issues) as you might find that you don't need to create one. When you are creating a bug report, please include as many details as possible.

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

- [Issues labeled "good first issue"](https://github.com/okeefeco/pyeye-mcp/labels/good%20first%20issue) - issues which should only require a few lines of code
- [Issues labeled "help wanted"](https://github.com/okeefeco/pyeye-mcp/labels/help%20wanted) - issues which need extra attention

These labels mark issues that are open for help, not work that is pre-approved. Comment on the issue and wait to be assigned before you start (see the [contribution policy](#contribution-policy)).

### Pull Requests

The process described here has several goals:

- Maintain the project's quality
- Fix problems that are important to users
- Engage the community in working toward the best possible product
- Enable a sustainable system for maintainers to review contributions

Please follow these steps for your contribution:

1. **Create an issue first and get it assigned** - Before starting work, create or find an issue describing what you plan to do, and wait for a maintainer to assign it to you (see the [contribution policy](#contribution-policy))
2. **Fork the repository** and create your branch from `main`
3. **Make your changes** - See [Development Process](#development-process) below
4. **Add tests** - If you've added code, add tests
5. **Ensure tests pass** - Run the full test suite
6. **Update documentation** - If you've changed APIs, update the relevant documentation
7. **Add a changelog fragment** - For a user-facing change, add a fragment instead of editing `CHANGELOG.md`: [`changes/README.md`](changes/README.md) explains how.
8. **Record a design decision, if you made one** - A contract-significant decision gets its own entry: [`docs/decisions/DECISIONS.md`](docs/decisions/DECISIONS.md) explains the format and the tooling.
9. **Submit the pull request** - Link it to your assigned issue using "Fixes #issue-number"
10. **Address review feedback** - Maintainers will review your PR and may request changes

## Development Process

### Setting Up Your Environment

#### Prerequisites

- Python <!-- fact:begin project.requires_python -->`>=3.11`<!-- fact:end -->
- [uv](https://github.com/astral-sh/uv) package manager
- Git

#### Quick Start

1. Fork and clone the repository:

   ```bash
   git clone git@github.com:your-username/pyeye-mcp.git
   cd pyeye-mcp
   ```

2. Install dependencies (creates a uv-managed `.venv`; `dev` is uv's default group):

   ```bash
   uv sync --frozen
   ```

3. Install pre-commit and its hooks. pre-commit isn't in the project's
   dependencies, so install it once for your user (for example with
   `uv tool install pre-commit` or `pipx install pre-commit`), then:

   ```bash
   pre-commit install
   ```

   This installs every hook type the project configures (`pre-commit`,
   `commit-msg`, `post-commit`, `post-merge`, and `post-checkout`). The
   `post-merge`/`post-checkout` hooks keep the local `setuptools_scm` version
   file fresh after a pull or branch switch and start a dogfooding metrics
   session when you check out an issue branch. If you cloned before these hook
   types were added, re-run `pre-commit install` to pick them up. If you have a
   hand-written `.git/hooks/post-checkout` from an older setup, remove it (and
   any `.git/hooks/post-checkout.legacy` pre-commit leaves behind) so the
   metrics session does not start twice.

#### Dependency lockfile policy

`uv.lock` is **authoritative**: pre-commit hooks, CI, local dev and release
install the *exact* locked dependency set, and no command silently re-resolves. Resolution happens in exactly one place: a deliberate
`uv lock` / `uv add`, committed and reviewed.

- **Hooks** pin `uv run` <!-- fact:begin precommit.uv_run_flags -->`--frozen`<!-- fact:end --> (use the lock as-is; never block, never rewrite it).
- **Local setup** uses `uv sync --frozen` (install exactly what `uv.lock` says; never re-resolve). Run `uv lock --check` if you want the drift check locally — CI enforces it either way.
- **CI** pins `uv sync` <!-- fact:begin ci.uv_sync_flags -->`--locked`<!-- fact:end --> (assert `uv.lock` equals `pyproject.toml` and fail on drift). A per-step flag, not a `UV_LOCKED` env var — `UV_LOCKED` is mutually exclusive with the hooks' `--frozen`, and CI's `pre-commit` job runs those hooks.
- **Changing dependencies** is the only sanctioned re-resolution: edit `pyproject.toml`, run `uv lock` (or `uv add`), and commit the updated `uv.lock` in the same change.

If CI fails with *"the lockfile needs to be updated, but `--locked` was provided,"*
you changed `pyproject.toml` without re-locking — run `uv lock` and commit the result.

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
uv run pytest --cov=src/pyeye --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_specific.py

# Run with verbose output
uv run pytest -v
```

For comprehensive testing guidelines, including performance testing and cross-platform considerations, see the [testing strategy](docs/testing/STRATEGY.md).

To call tools by hand in a browser (optional; needs Node.js), start the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector) on the server:

```bash
npx @modelcontextprotocol/inspector uv run python -m pyeye.mcp
```

Tests are the main way tools are checked: they call them in-process with
`mcp.call_tool(...)`.

### Code Style

Pre-commit hooks format your code and run the linters, type checker and
security checks; [`.pre-commit-config.yaml`](.pre-commit-config.yaml) lists
them. To run them all manually:

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

The code lives in `src/pyeye/`. The [architecture pages](docs/architecture/)
describe how its parts fit together: [resolution](docs/architecture/resolution.md),
[caching](docs/architecture/caching.md) and the
[plugin system](docs/architecture/plugin-system.md). To see the current layout,
[connect pyeye](README.md#installation) to your MCP client, open its own
checkout, and `outline` the `pyeye` package.

## Community

### Getting Help

- **GitHub Issues** - For bug reports, feature requests and questions
- **Documentation** - Read the [docs site](https://okeefeco.github.io/pyeye-mcp/), built from the [docs](docs/) folder

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

## License

By contributing, you agree that your contributions will be licensed under the same [MIT License](LICENSE) that covers the project.

## Questions?

Feel free to open an issue with your question or reach out to the maintainers. We're here to help!

---

Thank you again for your interest in contributing to PyEye Server! 🎉
