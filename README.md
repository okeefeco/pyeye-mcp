# Python Code Intelligence MCP Server

[![CI](https://github.com/okeefeco/python-code-intelligence-mcp/workflows/CI/badge.svg)](https://github.com/okeefeco/python-code-intelligence-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/okeefeco/python-code-intelligence-mcp/graph/badge.svg?token=XE5T93O8EC)](https://codecov.io/gh/okeefeco/python-code-intelligence-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

An extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis, navigation, and understanding capabilities for AI assistants like Claude.

## Features

- 🔍 **Semantic Code Navigation**: Find symbols, go to definitions, find references
- 📊 **Module & Package Analysis**: List packages/modules, analyze dependencies, detect circular imports
- 🏗️ **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
- 📦 **Namespace Packages**: Handle packages distributed across multiple repositories
- 🔄 **Auto-Update**: Automatically detects and reflects file changes
- ⚙️ **Configuration System**: Flexible configuration via files, env vars, or auto-discovery
- 🔌 **Extensible Plugin System**: Add custom analyzers for your project patterns
- 🚀 **Fast & Cached**: Intelligent caching with LRU eviction
- 🎯 **Type-Aware**: Full understanding of Python type hints and annotations

## Installation

The Python Code Intelligence MCP can be installed in two ways:

### Option 1: Project-Specific Installation (Recommended)

Install directly into your Python project's virtual environment:

```bash
# Activate your project's virtual environment
source /path/to/your/project/venv/bin/activate

# Install from PyPI (when available)
pip install python-code-intelligence-mcp

# Or install from source
git clone https://github.com/hangie/python-code-intelligence-mcp.git
pip install -e ./python-code-intelligence-mcp
```

Then create a `.mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "python-intelligence": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "pycodemcp.server"],
      "env": {}
    }
  }
}
```

This way, the MCP server uses your project's environment and has access to all your project's dependencies.

### Option 2: Global Installation

For analyzing multiple projects or using with global Python:

```bash
# Install globally with pipx (recommended for isolation)
pipx install python-code-intelligence-mcp

# Or with pip
pip install --user python-code-intelligence-mcp

# Or from source
git clone https://github.com/hangie/python-code-intelligence-mcp.git
cd python-code-intelligence-mcp
pip install --user .
```

#### Configure with Claude Code (Global)

```bash
# Add the MCP server globally (available in all projects)
claude mcp add python-intelligence -s user -- python -m pycodemcp.server

# Verify it's connected
claude mcp list
```

### Configure with Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "python-intelligence": {
      "command": "python",
      "args": ["-m", "pycodemcp.server"],
      "env": {}
    }
  }
}
```

Note: Use the full path to Python if needed (e.g., `/usr/local/bin/python3` or `C:\\Python311\\python.exe`).

### Configure with GitHub Copilot (VS Code)

As of 2025, GitHub Copilot has full MCP support in VS Code, JetBrains, Eclipse, and Xcode. Follow these steps to use this Python Code Intelligence server with GitHub Copilot:

#### Prerequisites

- **GitHub Copilot Business or Enterprise subscription** (required for MCP support)
- **VS Code version 1.102 or later** (MCP support is GA)
- **Organization MCP policy enabled** by your admin

#### Step 1: Enable MCP in Your Organization

Your GitHub Copilot administrator needs to enable the MCP servers policy:

1. Go to your organization settings on GitHub
2. Navigate to **Copilot** → **Policies**
3. Enable **"MCP servers in Copilot"** policy
4. Save changes

#### Step 2: Install the MCP Server

Install the Python Code Intelligence MCP server in your project or globally:

```bash
# Option A: Install in your project's virtual environment (recommended)
pip install python-code-intelligence-mcp

# Option B: Install globally with pipx
pipx install python-code-intelligence-mcp

# Option C: Install from source
git clone https://github.com/hangie/python-code-intelligence-mcp.git
pip install -e ./python-code-intelligence-mcp
```

#### Step 3: Configure VS Code

Add the MCP server configuration to your VS Code settings:

**User Settings** (applies to all projects):

```json
// File: ~/.config/Code/User/settings.json (Linux/Mac)
// or %APPDATA%\Code\User\settings.json (Windows)
{
  "github.copilot.chat.mcpServers": {
    "python-intelligence": {
      "command": "python",
      "args": ["-m", "pycodemcp.server"],
      "env": {}
    }
  }
}
```

**Workspace Settings** (project-specific):

```json
// File: .vscode/settings.json in your project root
{
  "github.copilot.chat.mcpServers": {
    "python-intelligence": {
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "pycodemcp.server"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}"
      }
    }
  }
}
```

#### Step 4: Verify Connection

1. Open VS Code in your Python project
2. Open the GitHub Copilot Chat panel
3. Type: `@mcp list` to see available MCP servers
4. You should see `python-intelligence` in the list
5. Test with: `@mcp python-intelligence find_symbol MyClass`

#### Troubleshooting

**MCP not available:**

- Ensure you have Copilot Business/Enterprise (not Free/Pro)
- Check that your organization admin enabled the MCP policy
- Update VS Code to version 1.102 or later

**Server not connecting:**

- Verify Python path in the configuration
- Check that `pycodemcp` is installed: `python -m pycodemcp.server --help`
- Look for errors in VS Code Output panel → GitHub Copilot Logs

**Import errors:**

- If using a virtual environment, ensure the path points to the venv Python
- Add `PYTHONPATH` to the env configuration if needed

#### Other IDEs

**JetBrains IDEs** (IntelliJ, PyCharm, etc.):

- MCP support is GA - configure in Settings → Tools → GitHub Copilot → MCP Servers

**Visual Studio**:

- MCP support is in preview - configure in Tools → Options → GitHub Copilot → MCP Servers

**Eclipse & Xcode**:

- MCP support is GA - see IDE-specific documentation for configuration

## Configuration

The server can be configured to analyze packages in other locations. Create a `.pycodemcp.json` file in your project:

```json
{
  "packages": [
    "../my-shared-library",
    "~/repos/company-utils",
    "/absolute/path/to/package"
  ],
  "namespaces": {
    "mycompany": [
      "~/repos/mycompany-auth",
      "~/repos/mycompany-api"
    ]
  }
}
```

### Configuration Methods

Configuration is loaded in the following order (later sources override earlier ones):

1. **Global Config**: `~/.config/pycodemcp/config.json` or `~/.pycodemcp.json` - User defaults
2. **Project Config**: `.pycodemcp.json` in project root or `[tool.pycodemcp]` in `pyproject.toml`
3. **Override File**: `.pycodemcp.override.json` - Local development overrides (git-ignored)
4. **Auto-Discovery**: Automatically finds sibling packages if no packages configured

### Using Override Files

Override files are perfect for local development configurations that shouldn't be committed:

```json
// .pycodemcp.override.json (git-ignored)
{
  "packages": [
    "../my-local-dev-package",
    "~/dev/experimental"
  ],
  "namespaces": {
    "company.feature": ["/home/user/feature-branch"]
  }
}
```

### Performance Settings

All performance-critical settings can be configured via environment variables to tune for your specific workload:

| Environment Variable | Default | Description | Valid Range |
|---------------------|---------|-------------|-------------|
| `PYCODEMCP_MAX_PROJECTS` | 10 | Maximum number of projects in memory | 1-1000 |
| `PYCODEMCP_CACHE_TTL` | 300 | Cache time-to-live in seconds | 0-86400 (24h) |
| `PYCODEMCP_WATCHER_DEBOUNCE` | 0.5 | File watcher debounce delay in seconds | 0.0-10.0 |
| `PYCODEMCP_MAX_FILE_SIZE` | 1048576 | Maximum file size to analyze (bytes) | 1KB-100MB |
| `PYCODEMCP_MAX_WORKERS` | 4 | Maximum concurrent analysis workers | 1-32 |
| `PYCODEMCP_ANALYSIS_TIMEOUT` | 30.0 | Analysis timeout in seconds | 1.0-300.0 |
| `PYCODEMCP_ENABLE_MEMORY_PROFILING` | false | Enable memory profiling | true/false |
| `PYCODEMCP_ENABLE_PERFORMANCE_METRICS` | false | Enable performance metrics | true/false |

#### Performance Tuning Examples

**Large codebase with stable files:**

```bash
export PYCODEMCP_MAX_PROJECTS=50        # Handle more projects
export PYCODEMCP_CACHE_TTL=1800         # 30 minute cache
export PYCODEMCP_WATCHER_DEBOUNCE=2.0   # Less frequent updates
```

**Active development with frequent changes:**

```bash
export PYCODEMCP_MAX_PROJECTS=5         # Fewer projects, faster switching
export PYCODEMCP_CACHE_TTL=60           # 1 minute cache
export PYCODEMCP_WATCHER_DEBOUNCE=0.1   # Near real-time updates
```

**Memory-constrained environment:**

```bash
export PYCODEMCP_MAX_PROJECTS=3         # Minimal project cache
export PYCODEMCP_MAX_FILE_SIZE=524288   # 512KB file limit
export PYCODEMCP_MAX_WORKERS=2          # Fewer workers
```

This file is automatically ignored by git and takes precedence over all other configuration sources.

## Core Tools

### Basic Navigation

- **`find_symbol`** - Find class, function, or variable definitions with re-export tracking
  - Now includes `import_paths` field showing all available import paths for a symbol
  - Automatically detects re-exports through `__init__.py` files
  - Lists shorter/preferred import paths first (e.g., `from models import User` before `from models.user import User`)
- **`goto_definition`** - Jump to where a symbol is defined
- **`find_references`** - Find all places where a symbol is used
- **`get_type_info`** - Get type hints and docstrings
- **`find_imports`** - Track module imports across the project
- **`get_call_hierarchy`** - Analyze function call relationships

### Multi-Project Tools

- **`configure_packages`** - Set up additional package locations
- **`find_symbol_multi`** - Search across multiple projects
- **`configure_namespace_package`** - Set up distributed namespace packages
- **`find_in_namespace`** - Search within namespace packages

### Project Structure & Analysis

- **`list_project_structure`** - View Python project file organization
- **`list_packages`** - List all Python packages with structure
- **`list_modules`** - List modules with exports, classes, functions, and metrics
- **`analyze_dependencies`** - Analyze module imports and detect circular dependencies
- **`get_module_info`** - Get detailed module information including metrics and dependencies

### Framework-Specific Tools (Auto-Activated)

#### Django (when Django is detected)

- **`find_django_models`** - Find all Django models
- **`find_django_views`** - Find all views
- **`find_django_urls`** - Find URL patterns
- **`find_django_templates`** - Find templates
- **`find_django_migrations`** - Find migrations

#### Pydantic (when Pydantic is detected)

- **`find_pydantic_models`** - Discover all BaseModel classes
- **`get_model_schema`** - Extract complete model schema
- **`find_validators`** - Locate all validation methods
- **`find_field_validators`** - Find field-specific validators
- **`find_model_config`** - Extract model configurations
- **`trace_model_inheritance`** - Map model inheritance hierarchies
- **`find_computed_fields`** - Find computed_field and @property fields

#### Flask (when Flask is detected)

- **`find_flask_routes`** - Discover all route decorators with methods and endpoints
- **`find_flask_blueprints`** - Locate Blueprint definitions and registrations
- **`find_flask_views`** - Find view functions and MethodView classes
- **`find_flask_templates`** - Locate Jinja2 templates and render_template calls
- **`find_flask_extensions`** - Identify Flask extensions (SQLAlchemy, Login, CORS, etc.)
- **`find_flask_config`** - Find configuration files and app.config usage
- **`find_error_handlers`** - Locate @app.errorhandler decorators
- **`find_cli_commands`** - Find Flask CLI commands (@app.cli.command)

## Advanced Features

### Multi-Project Support

Analyze your main project along with local dependencies:

```python
# Configure to analyze multiple packages
configure_packages(
    packages=["../my-lib", "~/repos/shared-utils"],
    namespaces={"company": ["~/repos/company-*"]}
)
```

### Namespace Packages

Handle packages distributed across multiple repositories:

```python
# company.auth in repo A, company.api in repo B
configure_namespace_package(
    namespace="company",
    repo_paths=["~/repos/company-auth", "~/repos/company-api"]
)
```

### Auto-Update on File Changes

The server uses file watching to automatically update when code changes:

- Detects modifications in real-time
- Invalidates cache for changed files
- Maintains separate watchers per project

## Architecture

```text
Python Code Intelligence MCP
├── Core Server (FastMCP)
├── Project Manager
│   ├── Multi-project support (LRU cache)
│   ├── Namespace resolver
│   └── Configuration loader
├── Analysis Engines
│   ├── Jedi (semantic analysis)
│   └── Tree-sitter (pattern matching)
├── Caching Layer
│   ├── File watchers (watchdog)
│   └── Result cache (5min TTL)
└── Plugin System
    ├── Base plugin class
    └── Framework plugins (Django, Pydantic, Flask)
```

## Plugin Development

Create custom plugins for your project patterns:

```python
from pycodemcp.plugins.base import AnalyzerPlugin

class MyProjectPlugin(AnalyzerPlugin):
    def name(self) -> str:
        return "MyProject"

    def detect(self) -> bool:
        # Return True if this plugin should activate
        return (self.project_path / "my_framework.conf").exists()

    def find_patterns(self, pattern_name: str):
        # Find your custom patterns
        pass
```

## Development

```bash
# Install development dependencies
uv add --dev pytest black ruff mypy

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/

# Test the server
uv run mcp dev src/pycodemcp/server.py
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Acknowledgments

Built on top of:

- [Jedi](https://github.com/davidhalter/jedi) - Python static analysis
- [Tree-sitter](https://tree-sitter.github.io/) - Incremental parsing
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
