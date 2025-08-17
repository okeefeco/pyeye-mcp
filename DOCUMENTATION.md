# Python Code Intelligence MCP Server - Full Documentation

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Tools Reference](#tools-reference)
5. [Architecture](#architecture)
6. [Security](#security)
7. [Use Cases](#use-cases)
8. [Plugin Development](#plugin-development)
9. [Troubleshooting](#troubleshooting)

## Overview

The Python Code Intelligence MCP Server provides semantic code analysis for Python projects through the Model Context Protocol (MCP). It enables AI assistants like Claude to understand Python codebases deeply without reading every file.

### Key Capabilities

- **Semantic Analysis**: Understands Python code structure, not just text matching
- **Multi-Project**: Analyzes multiple projects and dependencies simultaneously
- **Auto-Update**: Reflects code changes in real-time
- **Extensible**: Plugin system for custom patterns
- **Efficient**: Intelligent caching reduces redundant analysis

## Installation

### Prerequisites

- Python 3.10 or higher
- Git
- uv (recommended) or pip

### Install from Source

```bash
# Clone repository
git clone https://github.com/hangie/python-code-intelligence-mcp.git
cd python-code-intelligence-mcp

# Install dependencies with uv
uv sync

# Or with pip
pip install -e .
```

### Configure for Claude Code

```bash
# Add globally (available in all projects)
claude mcp add python-intelligence -s user -- \
  uv run python ~/GitHub/python-code-intelligence-mcp/src/pycodemcp/server.py

# Or add to specific project
cd your-project
claude mcp add python-intelligence -- \
  uv run python ~/GitHub/python-code-intelligence-mcp/src/pycodemcp/server.py

# Verify connection
claude mcp list
```

### Configure for Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "python-intelligence": {
      "command": "uv",
      "args": [
        "run",
        "python",
        "/path/to/python-code-intelligence-mcp/src/pycodemcp/server.py"
      ]
    }
  }
}
```

## Configuration

### Configuration File (.pycodemcp.json)

Create in your project root:

```json
{
  "packages": [
    ".",                           // Current directory
    "../my-shared-library",        // Relative path
    "~/repos/company-utils",       // Home directory path
    "/absolute/path/to/package",   // Absolute path
    "~/repos/plugins/*"            // Glob pattern
  ],
  "namespaces": {
    "mycompany": [                 // Namespace package name
      "~/repos/mycompany-auth",    // Repository containing part of namespace
      "~/repos/mycompany-api",
      "~/repos/mycompany-core"
    ],
    "plugins": [
      "./plugins/*",                // Local plugins
      "~/repos/community-plugins/*" // External plugins
    ]
  },
  "exclude": [
    "**/tests/**",                  // Exclude test directories
    "**/migrations/**",             // Exclude Django migrations
    "**/__pycache__/**"            // Exclude Python cache
  ],
  "cache": {
    "ttl_seconds": 300,            // Cache time-to-live (5 minutes)
    "max_size_mb": 100             // Maximum cache size
  }
}
```

### Configuration in pyproject.toml

```toml
[tool.pycodemcp]
packages = [
    "../shared-lib",
    "~/repos/utils"
]

[tool.pycodemcp.namespaces]
company = [
    "~/repos/company-auth",
    "~/repos/company-api"
]
```

### Environment Variables

```bash
# Configure packages
export PYCODEMCP_PACKAGES=/path/to/pkg1:/path/to/pkg2

# Configure namespace packages
export PYCODEMCP_NAMESPACE_company=~/repos/company-auth:~/repos/company-api
export PYCODEMCP_NAMESPACE_plugins=~/repos/plugin-*

# Start Claude with configuration
claude
```

### Global Configuration

Create `~/.config/pycodemcp/config.json`:

```json
{
  "packages": [
    "~/my-common-libs",
    "~/work/shared-utils"
  ],
  "cache": {
    "ttl_seconds": 600
  }
}
```

### Configuration Precedence

1. Project `.pycodemcp.json` (highest)
2. Project `pyproject.toml`
3. Environment variables
4. Global config `~/.config/pycodemcp/config.json`
5. Auto-discovery (lowest)

## Tools Reference

### find_symbol

Find symbol definitions in the project.

**Parameters:**

- `name` (str): Symbol name to search for
- `project_path` (str): Root path of project (default: ".")
- `fuzzy` (bool): Use fuzzy matching (default: False)
- `use_config` (bool): Use configuration file (default: True)

**Returns:** List of symbol locations with file, line, column, and type

**Example:**

```python
find_symbol("User", fuzzy=True)
# Returns all symbols containing "User"
```

### goto_definition

Jump to symbol definition from a position.

**Parameters:**

- `file` (str): Path to file
- `line` (int): Line number (1-indexed)
- `column` (int): Column number (0-indexed)
- `project_path` (str): Root path (default: ".")

**Returns:** Definition location or None

**Example:**

```python
goto_definition("app.py", 45, 10)
# Jumps to definition of symbol at line 45, column 10
```

### find_references

Find all references to a symbol.

**Parameters:**

- `file` (str): Path to file
- `line` (int): Line number
- `column` (int): Column number
- `project_path` (str): Root path
- `include_definitions` (bool): Include definitions in results

**Returns:** List of reference locations

### get_type_info

Get type information at a position.

**Parameters:**

- `file` (str): Path to file
- `line` (int): Line number
- `column` (int): Column number
- `project_path` (str): Root path

**Returns:** Type information including inferred types and docstring

### find_imports

Find all imports of a module.

**Parameters:**

- `module_name` (str): Name of module
- `project_path` (str): Root path

**Returns:** List of import locations

### get_call_hierarchy

Get call hierarchy for a function.

**Parameters:**

- `function_name` (str): Function name
- `file` (str, optional): Specific file to search
- `project_path` (str): Root path

**Returns:** Call hierarchy with callers and callees

### configure_packages

Configure additional package locations.

**Parameters:**

- `packages` (List[str]): Package paths to include
- `namespaces` (Dict): Namespace packages with paths
- `save` (bool): Save to config file

**Returns:** Current configuration

### find_symbol_multi

Search across multiple projects.

**Parameters:**

- `name` (str): Symbol name
- `project_paths` (List[str]): Projects to search
- `fuzzy` (bool): Fuzzy matching

**Returns:** Results grouped by project

### configure_namespace_package

Set up distributed namespace packages.

**Parameters:**

- `namespace` (str): Package namespace
- `repo_paths` (List[str]): Repository paths

**Returns:** Configuration details and structure

### find_in_namespace

Search within namespace packages.

**Parameters:**

- `import_path` (str): Full import path
- `namespace_repos` (List[str]): Repos to search

**Returns:** Locations where import is found

### Framework-Specific Tools

The server automatically detects and activates framework-specific tools when it identifies framework usage in your project.

#### Django Tools (Auto-activated)

- **`find_django_models`** - Find all Django models with inheritance
- **`find_django_views`** - Find function and class-based views
- **`find_django_urls`** - Find URL patterns and configurations
- **`find_django_templates`** - Find Django templates
- **`find_django_migrations`** - Find migration files by app

#### Pydantic Tools (Auto-activated)

- **`find_pydantic_models`** - Discover all BaseModel classes with fields
- **`get_model_schema`** - Extract complete model schema including validators
- **`find_validators`** - Locate all validation methods (root, model validators)
- **`find_field_validators`** - Find field-specific validators
- **`find_model_config`** - Extract model configurations
- **`trace_model_inheritance`** - Map model inheritance hierarchies
- **`find_computed_fields`** - Find computed_field and @property fields

#### Flask Tools (Auto-activated)

- **`find_flask_routes`** - Discover all route decorators with methods and endpoints
- **`find_flask_blueprints`** - Locate Blueprint definitions and registrations
- **`find_flask_views`** - Find view functions and MethodView classes
- **`find_flask_templates`** - Locate Jinja2 templates and render_template calls
- **`find_flask_extensions`** - Identify Flask extensions (SQLAlchemy, Login, CORS, etc.)
- **`find_flask_config`** - Find configuration files and app.config usage
- **`find_error_handlers`** - Locate @app.errorhandler decorators
- **`find_cli_commands`** - Find Flask CLI commands (@app.cli.command)

## Architecture

### Component Overview

```text
┌─────────────────────────────────────────────────────┐
│                   MCP Client (Claude)                │
└─────────────────────────┬───────────────────────────┘
                          │ MCP Protocol
┌─────────────────────────▼───────────────────────────┐
│                    FastMCP Server                    │
├──────────────────────────────────────────────────────┤
│                   Project Manager                    │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐      │
│  │ Project A  │ │ Project B  │ │ Project C  │ ...  │
│  │ (LRU Cache)│ │ (LRU Cache)│ │ (LRU Cache)│      │
│  └────────────┘ └────────────┘ └────────────┘      │
├──────────────────────────────────────────────────────┤
│              Configuration System                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   JSON   │ │   TOML   │ │ Env Vars │           │
│  └──────────┘ └──────────┘ └──────────┘           │
├──────────────────────────────────────────────────────┤
│               Analysis Engines                       │
│  ┌──────────────┐        ┌──────────────┐          │
│  │     Jedi     │        │ Tree-sitter  │          │
│  │  (Semantic)  │        │  (Patterns)  │          │
│  └──────────────┘        └──────────────┘          │
├──────────────────────────────────────────────────────┤
│                 Caching Layer                        │
│  ┌──────────────┐        ┌──────────────┐          │
│  │ File Watcher │        │ Result Cache │          │
│  │  (Watchdog)  │        │  (DiskCache) │          │
│  └──────────────┘        └──────────────┘          │
├──────────────────────────────────────────────────────┤
│                 Plugin System                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  Django  │ │ Pydantic │ │  Flask   │ ...       │
│  └──────────┘ └──────────┘ └──────────┘           │
└──────────────────────────────────────────────────────┘
```

### Key Components

#### Project Manager

- Manages multiple Python projects simultaneously
- LRU eviction (max 10 projects by default)
- Maintains separate Jedi instance per project
- Handles project dependencies and include paths

#### Namespace Resolver

- Discovers namespace packages (PEP 420)
- Handles legacy namespace packages
- Resolves imports across repository boundaries
- Builds namespace structure maps

#### Configuration System

- Multiple configuration sources
- Precedence-based resolution
- Auto-discovery of packages
- Environment variable support

#### Cache System

- File-based result caching (5min TTL)
- Automatic invalidation on file changes
- Per-project cache isolation
- Memory-efficient LRU eviction

#### File Watching

- Real-time file change detection
- Automatic cache invalidation
- Per-project watchers
- Minimal performance overhead

## Security

### Input Validation

The MCP server implements comprehensive input validation to prevent security vulnerabilities:

#### Path Validation

All file paths are validated to prevent path traversal attacks:

- **Path Traversal Prevention**: Rejects paths containing `../` or similar patterns
- **Null Byte Protection**: Blocks paths with null bytes that could bypass security checks
- **Absolute Path Resolution**: Resolves all paths to absolute form to detect escape attempts
- **Base Directory Restriction**: Optional restriction to keep paths within project boundaries

Example of blocked patterns:

```python
# These paths will be rejected:
"../../etc/passwd"           # Path traversal
"/home/user/../../../etc"    # Absolute path traversal
"file\x00.txt"              # Null byte injection
```

#### Input Sanitization

All user inputs are sanitized before processing:

- **Identifier Validation**: Python identifiers must match `[a-zA-Z_][a-zA-Z0-9_]*`
- **Module Name Validation**: Module names allow dots but must be valid Python modules
- **Line/Column Validation**: Numbers are range-checked to prevent overflow
- **String Sanitization**: Control characters are removed, length is limited

#### Sensitive Path Warnings

The server warns when accessing potentially sensitive paths:

- `.git/` - Git repository data
- `.ssh/` - SSH keys
- `.aws/` - AWS credentials
- `.env` - Environment files
- `*.pem`, `*.key` - Certificate and key files

These paths are logged but not blocked (they may be legitimate for analysis).

### Configuration Security

When loading configuration from files:

- Paths from configuration files are validated
- Invalid paths are logged and skipped
- Glob patterns are expanded safely
- User home directory (`~`) is properly expanded

### Best Practices

1. **Restrict Base Directory**: Use the `base_path` parameter to limit file access:

   ```python
   PathValidator.validate_path(user_path, base_path="/project/root")
   ```

2. **Monitor Logs**: Watch for warnings about sensitive file access:

   ```text
   WARNING: Accessing potentially sensitive path: /home/user/.ssh/id_rsa
   ```

3. **File Size Limits**: Large files are rejected (default 10MB limit):

   ```python
   PathValidator.is_safe_to_read(path, max_size=5*1024*1024)  # 5MB limit
   ```

4. **Use Validation Decorator**: All MCP tools use the `@validate_mcp_inputs` decorator:

   ```python
   @mcp.tool()
   @validate_mcp_inputs
   def find_symbol(name: str, project_path: str = "."):
       # Inputs are automatically validated
       pass
   ```

### Security Testing

The validation module includes comprehensive tests:

```bash
# Run security tests
uv run pytest tests/test_validation.py -v
```

Tests cover:

- Path traversal attempts
- Null byte injection
- Invalid identifiers
- Boundary conditions
- Decorator validation

## Use Cases

### 1. Monorepo Development

```json
{
  "packages": [
    "./packages/core",
    "./packages/utils",
    "./packages/api",
    "./apps/web",
    "./apps/mobile"
  ]
}
```

### 2. Microservices Architecture

```json
{
  "packages": [
    "../auth-service",
    "../payment-service",
    "../notification-service",
    "../shared-libs"
  ]
}
```

### 3. Plugin-Based Application

```json
{
  "namespaces": {
    "myapp.plugins": [
      "./plugins/builtin/*",
      "~/repos/community-plugins/*",
      "~/my-plugins/*"
    ]
  }
}
```

### 4. Enterprise Namespace Packages

```json
{
  "namespaces": {
    "company": [
      "~/repos/company-common",
      "~/repos/company-auth",
      "~/repos/company-billing",
      "~/repos/company-analytics"
    ]
  }
}
```

## Plugin Development

### Creating a Plugin

```python
# src/pycodemcp/plugins/myframework.py
from pathlib import Path
from typing import List, Dict, Any
from .base import AnalyzerPlugin

class MyFrameworkPlugin(AnalyzerPlugin):
    """Plugin for MyFramework-specific intelligence."""

    def name(self) -> str:
        return "MyFramework"

    def detect(self) -> bool:
        """Detect if this is a MyFramework project."""
        # Check for framework-specific files
        return (self.project_path / "myframework.yaml").exists()

    def register_tools(self) -> Dict[str, callable]:
        """Register framework-specific MCP tools."""
        return {
            "find_controllers": self.find_controllers,
            "find_models": self.find_models,
            "find_routes": self.find_routes,
        }

    def find_controllers(self) -> List[Dict[str, Any]]:
        """Find all controllers in the project."""
        controllers = []
        # Your framework-specific logic
        for controller_file in self.project_path.rglob("*_controller.py"):
            # Parse and extract controller info
            pass
        return controllers

    def find_patterns(self, pattern_name: str) -> List[Dict[str, Any]]:
        """Find framework-specific patterns."""
        if pattern_name == "middleware":
            return self._find_middleware()
        elif pattern_name == "validators":
            return self._find_validators()
        return []
```

### Registering a Plugin

```python
# In server.py or plugin loader
from pycodemcp.plugins.myframework import MyFrameworkPlugin

# Auto-registration on project load
def load_plugins(project_path: str):
    plugins = [
        DjangoPlugin(project_path),
        PydanticPlugin(project_path),
        FlaskPlugin(project_path),
        FastAPIPlugin(project_path),  # Coming soon
        MyFrameworkPlugin(project_path),  # Your plugin
    ]

    active_plugins = []
    for plugin in plugins:
        if plugin.detect():
            active_plugins.append(plugin)
            logger.info(f"Activated {plugin.name()} plugin")

    return active_plugins
```

## Troubleshooting

### Server Not Starting

1. Check Python version: `python --version` (needs 3.10+)
2. Verify installation: `uv sync` or `pip install -e .`
3. Check logs: Run with `--debug` flag

### Packages Not Found

1. Verify paths in `.pycodemcp.json`
2. Check path resolution: Use absolute paths for testing
3. Verify packages exist and contain Python files
4. Check environment variables if using them

### Cache Issues

1. Clear cache: `rm -rf .pycodemcp_cache/`
2. Reduce cache TTL in config
3. Check disk space for cache storage

### File Changes Not Detected

1. Verify watchdog is installed: `pip show watchdog`
2. Check file system supports inotify (Linux) or FSEvents (macOS)
3. Increase logging level to see watcher events

### Performance Issues

1. Reduce number of included packages
2. Increase cache TTL
3. Use exclude patterns for large directories
4. Check if file watchers are overwhelming system

### MCP Connection Issues

1. Verify server is in allowed tools: `/permissions` in Claude
2. Check MCP server health: `claude mcp list`
3. Review Claude logs for connection errors
4. Try reconnecting: `claude mcp remove python-intelligence && claude mcp add ...`

## Environment Configuration

- `PYCODEMCP_PACKAGES`: Colon-separated list of package paths
- `PYCODEMCP_NAMESPACE_<name>`: Namespace package paths
- `PYCODEMCP_CACHE_TTL`: Cache TTL in seconds
- `PYCODEMCP_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `PYCODEMCP_MAX_PROJECTS`: Maximum cached projects (default: 10)

## Performance Considerations

### Memory Usage

- Each project: ~10-50MB depending on size
- Cache: Configurable, default 100MB max
- File watchers: ~1MB per project

### CPU Usage

- Initial indexing: One-time cost per project
- File watching: Minimal overhead
- Cache operations: O(1) lookups

### Optimization Tips

1. Use specific paths rather than globs when possible
2. Exclude test and build directories
3. Increase cache TTL for stable codebases
4. Limit number of watched projects

## Security Considerations

- The server has read access to all configured paths
- No code execution capabilities
- Cache stored locally in project directory
- No network access (except MCP protocol)
- Respects file system permissions

## Contributing

We welcome contributions! Areas for improvement:

1. Additional framework plugins
2. Performance optimizations
3. More sophisticated caching strategies
4. Additional analysis tools
5. Documentation improvements

See CONTRIBUTING.md for guidelines.

## License

MIT License - See LICENSE file for details.
