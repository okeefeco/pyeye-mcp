# Python Code Intelligence MCP Server - Claude Instructions

## 📚 Required Context Files

These files are automatically loaded to provide essential workflow context:

@CONTRIBUTING.md - GitHub issue workflow, merge strategy, validation rules, development setup
@docs/LABELS.md - GitHub issue labeling system and priorities

**CRITICAL**: The workflows in CONTRIBUTING.md are MANDATORY. Always follow the GitHub issue-based workflow and NEVER use squash merges.

## 📝 Optional User-Specific Configuration

For personal development settings (worktrees, local paths, etc.):

- Create: `~/.claude/projects/{org}/{repo}.md`
- Example: `~/.claude/projects/okeefeco/python-code-intelligence-mcp.md`
- This file is ignored if it doesn't exist and won't be committed to the repository

@~/.claude/projects/okeefeco/python-code-intelligence-mcp.md

## Development Environment

- **Working Directory**: /home/mark/GitHub/python-code-intelligence-mcp
- **Python Environment**: uv managed

## 🚨 MANDATORY: Test-Driven Development Workflow

**ALL code changes MUST include tests. This is enforced by CI.**

When implementing ANY feature or fix:

1. **Write tests FIRST** (TDD approach recommended)
2. **Implement the feature/fix**
3. **Run tests locally with coverage check**:

   ```bash
   # IMPORTANT: Run ALL tests, not just your new tests!
   pytest --cov=src/pycodemcp --cov-fail-under=80
   ```

4. **Fix any failing tests or coverage issues**
5. **NEVER commit code without tests**

### Coverage Requirements

- **Minimum 80% total coverage** (CI will fail below this)
- **New code should have >90% coverage**
- **All bug fixes MUST include regression tests**
- **ALWAYS run full test suite before pushing** (learned from PR #77)

### Before Marking Tasks Complete

Always run these validation commands:

```bash
# MANDATORY: Run ALL tests with coverage (not just your new tests!)
pytest --cov=src/pycodemcp --cov-fail-under=80

# Note: Linting/type checks are handled by pre-commit hooks automatically
```

## Project Overview

This is the Python Code Intelligence MCP Server - an extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis for AI assistants like Claude.

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
- **Analysis Engines**: Jedi for semantic analysis, Tree-sitter ready for patterns
- **Caching Layer**: File watchers (watchdog) + result cache (5min TTL)
- **Plugin System**: Base class + framework plugins (Django example included)

## MCP Tools Available

### Core Navigation Tools

1. `configure_packages` - Set up additional package locations
2. `find_symbol` - Find class/function/variable definitions
3. `goto_definition` - Jump to symbol definition
4. `find_references` - Find all symbol usages
5. `get_type_info` - Get type hints and docstrings
6. `find_imports` - Track module imports
7. `get_call_hierarchy` - Analyze function calls
8. `find_subclasses` - Find all classes inheriting from a base class
9. `find_symbol_multi` - Search across multiple projects
10. `configure_namespace_package` - Set up distributed namespaces
11. `find_in_namespace` - Search within namespace packages
12. `list_project_structure` - View project file organization

### Module & Package Analysis Tools

1. `list_packages` - List all Python packages with structure
2. `list_modules` - List modules with exports, classes, functions, and metrics
3. `analyze_dependencies` - Analyze module imports and detect circular dependencies
4. `get_module_info` - Get detailed module information including metrics and dependencies

### Pydantic-Specific Tools (auto-activated when Pydantic detected)

1. `find_pydantic_models` - Discover all BaseModel classes with fields
2. `get_model_schema` - Extract complete model schema
3. `find_validators` - Locate all validation methods
4. `find_field_validators` - Find field-specific validators
5. `find_model_config` - Extract model configurations
6. `trace_model_inheritance` - Map model inheritance hierarchies
7. `find_computed_fields` - Find computed_field and @property fields

### Django-Specific Tools (auto-activated when Django detected)

- `find_django_models` - Find all Django models
- `find_django_views` - Find all views
- `find_django_urls` - Find URL patterns
- `find_django_templates` - Find templates
- `find_django_migrations` - Find migrations

### Flask-Specific Tools (auto-activated when Flask detected)

- `find_flask_routes` - Discover all route decorators with methods and endpoints
- `find_flask_blueprints` - Locate Blueprint definitions and registrations
- `find_flask_views` - Find view functions and MethodView classes
- `find_flask_templates` - Locate Jinja2 templates and render_template calls
- `find_flask_extensions` - Identify Flask extensions (SQLAlchemy, Login, CORS, etc.)
- `find_flask_config` - Find configuration files and app.config usage
- `find_error_handlers` - Locate @app.errorhandler decorators
- `find_cli_commands` - Find Flask CLI commands (@app.cli.command)

## Configuration

The server supports configuration via:

- `.pycodemcp.json` in project root
- `pyproject.toml` [tool.pycodemcp] section
- Environment variables (PYCODEMCP_PACKAGES, etc.)
- Global config `~/.config/pycodemcp/config.json`
- Auto-discovery of sibling packages

Example `.pycodemcp.json`:

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
uv run mcp dev src/pycodemcp/server.py

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/
```

## Current Status

✅ **Fully functional** with all core features implemented:

- Basic navigation tools working
- Multi-project support with LRU caching
- Namespace package resolution
- Auto-updating on file changes
- Configuration system with multiple sources
- Plugin architecture with Django, Pydantic, and Flask plugins
- Comprehensive documentation
- **NEW**: Flask framework intelligence with 8 specialized tools for routes, blueprints, templates, and more

## Next Steps / Improvements

Potential enhancements to consider:

- Add more framework plugins (FastAPI)
- Implement Tree-sitter for pattern matching
- Add test coverage
- Publish to PyPI for easier installation
- Add more sophisticated caching strategies
- Create VS Code extension integration

## Important Notes

- The server is configured globally for Claude Code via `claude mcp add`
- Each Claude instance gets its own MCP server instance (not shared)
- File watchers automatically update when code changes
- Configuration is loaded from multiple sources with precedence
- Plugins auto-activate based on project detection (Django, Pydantic, Flask)
- Framework plugins provide deep understanding beyond basic navigation

## File Structure

```text
src/pycodemcp/
├── server.py              # Main MCP server with 11+ tools
├── project_manager.py     # Multi-project management with LRU
├── namespace_resolver.py  # Distributed package handling
├── config.py             # Configuration system
├── cache.py              # Caching and file watching
├── analyzers/
│   └── jedi_analyzer.py # Jedi wrapper for analysis
└── plugins/
    ├── base.py          # Plugin base class
    ├── django.py        # Django framework plugin
    ├── pydantic.py      # Pydantic models plugin
    └── flask.py         # Flask framework plugin (NEW)
```

## Context Loss Recovery

If context is lost:

1. **Check the GitHub issue** - `gh issue view <number>` (branch name shows issue number)
2. **Your todo list persists** - The TodoWrite tool maintains your session progress
3. **Check git state** - `git status`, `git log --oneline -5`, `git diff`
4. **Resume from todo list** - Continue from where your tasks show you stopped

The TodoWrite tool is your primary progress tracker - it persists across context resets without creating commits.

## Task Management with TodoWrite Tool

Use the **TodoWrite tool** for all task tracking - it persists across context resets without creating commits.

### Best Practices

- **Break tasks into small chunks** - 5-10 minute increments
- **Include file:line references** - e.g., "Fix validation in server.py:125-150"
- **Mark complete immediately** - Update status as you finish each task
- **Keep ONE task in_progress** - Focus on single task at a time
- **Never track in files** - Use TodoWrite tool, not CLAUDE.md or other files

### File Reference Pattern

Always use `file_path:line_number` format for easy navigation:

- `src/server.py:125` - Specific line reference
- `tests/test_validation.py:45-89` - Range reference
- `src/plugins/flask.py:find_routes` - Function reference
