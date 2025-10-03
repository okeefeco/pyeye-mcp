<!--
Audience: Claude Code
Purpose: Define project-specific configuration and context for Python Code Intelligence MCP
When to update: When project structure, tools, or architecture changes
-->

# Python Code Intelligence MCP Server - Project Specific Configuration

## Project Overview

This is the Python Code Intelligence MCP Server - an extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis for AI assistants like Claude.

## Development Environment

- **Working Directory**: /home/mark/GitHub/pyeye-mcp-work
- **Python Environment**: uv managed
- **Package Manager**: `uv` (ALWAYS use `uv run` prefix)

## Key Features

- **Semantic Code Navigation**: Find symbols, go to definitions, find references using Jedi
- **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
- **Namespace Packages**: Handle packages distributed across multiple repositories
- **Auto-Update**: File watching automatically reflects code changes
- **Configuration System**: Flexible configuration via files, env vars, or auto-discovery
- **Plugin Architecture**: Extensible with custom analyzers for project patterns

## Architecture

- **Core Server**: FastMCP-based MCP server implementation
- **Project Manager**: Handles multiple projects with LRU caching (max 10)
- **Analysis Engine**: Jedi for semantic analysis and type inference
- **Caching Layer**: File watchers (watchdog) + result cache (5min TTL)
- **Plugin System**: Base class + framework plugins (Django, Pydantic, Flask)

## File Structure

```text
src/pyeye/
├── server.py              # Main MCP server with 17+ core tools
├── project_manager.py     # Multi-project management with LRU
├── namespace_resolver.py  # Distributed package handling
├── config.py             # Configuration system
├── cache.py              # Caching and file watching
├── path_utils.py         # Cross-platform path utilities
├── analyzers/
│   └── jedi_analyzer.py # Jedi wrapper for analysis
└── plugins/
    ├── base.py          # Plugin base class
    ├── django.py        # Django framework plugin
    ├── pydantic.py      # Pydantic models plugin
    └── flask.py         # Flask framework plugin
```

## Configuration

The server supports configuration via:

- `.pyeye.json` in project root
- `pyproject.toml` [tool.pyeye] section
- Environment variables (PYEYE_PACKAGES, etc.)
- Global config `~/.config/pyeye/config.json`
- Auto-discovery of sibling packages

Example `.pyeye.json`:

```json
{
  "packages": ["../my-lib", "~/repos/shared-utils"],
  "namespaces": {
    "company": ["~/repos/company-auth", "~/repos/company-api"]
  }
}
```

## Development Commands

```bash
# Run server in dev mode
uv run mcp dev src/pyeye/server.py

# Run tests with coverage
uv run pytest --cov=src/pyeye --cov-fail-under=85

# Format code
uv run black src/
uv run ruff check src/

# Type checking
uv run mypy src/pyeye

# Security checks
uv run pip-audit
uv run safety check
uv run bandit -r src/
```

## Context Loss Recovery

If context is lost:

1. **Check the GitHub issue** - `gh issue view <number>` (branch name shows issue number)
2. **Your todo list persists** - The TodoWrite tool maintains your session progress
3. **Check git state** - `git status`, `git log --oneline -5`, `git diff`
4. **Resume from todo list** - Continue from where your tasks show you stopped

The TodoWrite tool is your primary progress tracker - it persists across context resets without creating commits.

## Current Status

✅ **Fully functional** with all core features implemented:

- Basic navigation tools working
- Multi-project support with LRU caching
- Namespace package resolution
- Auto-updating on file changes
- Configuration system with multiple sources
- Plugin architecture with Django, Pydantic, and Flask plugins
- Comprehensive documentation
- Flask framework intelligence with 8 specialized tools

## Important Notes

- The server is configured globally for Claude Code via `claude mcp add`
- Each Claude instance gets its own MCP server instance (not shared)
- File watchers automatically update when code changes
- Configuration is loaded from multiple sources with precedence
- Plugins auto-activate based on project detection
- Framework plugins provide deep understanding beyond basic navigation

## Path Utilities Available

Always use these for cross-platform compatibility:

- `src/pyeye/path_utils.py` has helpers:
  - `path_to_key()` - For dictionary keys/comparison
  - `ensure_posix_path()` - Convert any path to forward slashes
  - `paths_equal()` - Platform-safe path comparison

## File Reference Pattern

Always use `file_path:line_number` format for easy navigation:

- `src/server.py:125` - Specific line reference
- `tests/test_validation.py:45-89` - Range reference
- `src/plugins/flask.py:find_routes` - Function reference
