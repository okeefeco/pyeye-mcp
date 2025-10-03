# Python Code Intelligence MCP - API Reference

This directory contains comprehensive API documentation for all 30+ MCP tools provided by the Python Code Intelligence MCP Server.

## 📚 Documentation Structure

- **[Core Navigation Tools](./core-navigation.md)** - 11 tools for code navigation and symbol finding
- **[Module Analysis Tools](./module-analysis.md)** - 4 tools for package and module analysis
- **[Pydantic Tools](./pydantic-tools.md)** - 7 tools for Pydantic model analysis
- **[Flask Tools](./flask-tools.md)** - 8 tools for Flask application analysis
- **[Django Tools](./django-tools.md)** - 5 tools for Django project analysis
- **[Quick Reference](./quick-reference.md)** - Cheatsheet for common operations

## 🚀 Quick Start

### Finding Symbols

```python
# Find a class definition
find_symbol(name="MyClass", fuzzy=False)

# Find with fuzzy matching
find_symbol(name="MyCls", fuzzy=True)

# Search across multiple projects
find_symbol_multi(name="SharedClass", project_paths=[".", "../lib"])
```

### Navigating Code

```python
# Jump to definition
goto_definition(file="app.py", line=42, column=10)

# Find all references
find_references(file="models.py", line=15, column=4)

# Get type information
get_type_info(file="utils.py", line=100, column=20)
```

### Analyzing Dependencies

```python
# List all modules
list_modules(project_path=".")

# Analyze dependencies
analyze_dependencies(module_path="myapp.services")

# Get module details
get_module_info(module_path="myapp.models")
```

## 🔌 Framework-Specific Tools

The server automatically detects and activates framework-specific tools:

- **Django**: Models, views, URLs, templates, migrations
- **Flask**: Routes, blueprints, templates, extensions, error handlers
- **Pydantic**: Models, validators, schemas, inheritance

## ⚙️ Configuration

Tools respect configuration from multiple sources:

1. `.pyeye.json` in project root
2. `pyproject.toml` `[tool.pyeye]` section
3. Environment variables
4. Global config `~/.config/pyeye/config.json`

Example configuration:

```json
{
  "packages": ["../shared-lib", "~/repos/utils"],
  "namespaces": {
    "company": ["~/repos/company-auth", "~/repos/company-api"]
  }
}
```

## 📖 Tool Categories

### Core Navigation (11 tools)

Essential tools for navigating and understanding Python code:

- Symbol finding and navigation
- Definition and reference tracking
- Type information and call hierarchies
- Multi-project and namespace support

### Module Analysis (4 tools)

Tools for understanding project structure:

- Package and module listing
- Dependency analysis
- Circular dependency detection
- Module metrics and exports

### Framework Tools (20+ tools)

Specialized tools for popular frameworks:

- **Pydantic**: Model schemas, validators, inheritance
- **Flask**: Routes, blueprints, templates, extensions
- **Django**: Models, views, URLs, migrations

## 🎯 Common Use Cases

### Code Navigation

```python
# Find where a function is defined
result = find_symbol("process_data")
# Jump to its definition
goto_definition(file=result[0]["file"], line=result[0]["line"], column=0)
```

### Dependency Analysis

```python
# Check for circular dependencies
deps = analyze_dependencies("myapp.core")
if deps["circular_dependencies"]:
    print("Warning: Circular dependencies detected!")
```

### Framework Analysis

```python
# Find all Flask routes
routes = find_flask_routes()
# Get Pydantic model schema
schema = get_model_schema("UserModel")
```

## 📊 Return Value Patterns

Most tools return structured data with consistent patterns:

- **Location results**: Include `file`, `line`, `column` fields
- **List results**: Return arrays of matches
- **Analysis results**: Return dictionaries with categorized data
- **Error handling**: Tools raise exceptions for invalid inputs

## 🔍 Error Handling

Tools handle errors consistently:

- **Invalid parameters**: Raise `ValidationError`
- **File not found**: Return empty results or specific error
- **Timeout**: Configurable via `PYEYE_ANALYSIS_TIMEOUT`
- **Memory limits**: Configurable via environment variables

## 📝 Notes

- All file paths support both absolute and relative paths
- Line numbers are 1-indexed (matching editor display)
- Column numbers are 0-indexed (matching LSP standard)
- Results are cached for performance (TTL configurable)
- File watchers automatically invalidate cache on changes

For detailed documentation of each tool, see the category-specific documentation files.
