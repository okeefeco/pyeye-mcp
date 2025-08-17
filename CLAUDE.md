# Python Code Intelligence MCP Server - Claude Instructions

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
8. `find_symbol_multi` - Search across multiple projects
9. `configure_namespace_package` - Set up distributed namespaces
10. `find_in_namespace` - Search within namespace packages
11. `list_project_structure` - View project file organization

### Pydantic-Specific Tools (auto-activated when Pydantic detected)
12. `find_pydantic_models` - Discover all BaseModel classes with fields
13. `get_model_schema` - Extract complete model schema
14. `find_validators` - Locate all validation methods
15. `find_field_validators` - Find field-specific validators
16. `find_model_config` - Extract model configurations
17. `trace_model_inheritance` - Map model inheritance hierarchies
18. `find_computed_fields` - Find computed_field and @property fields

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

```
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