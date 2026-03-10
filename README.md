# PyEye 👁️

## PyEye Server

[![CI](https://github.com/okeefeco/pyeye-mcp/workflows/CI/badge.svg)](https://github.com/okeefeco/pyeye-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/okeefeco/pyeye-mcp/graph/badge.svg?token=XE5T93O8EC)](https://codecov.io/gh/okeefeco/pyeye-mcp)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

An extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis, navigation, and understanding capabilities for AI assistants like Claude.

## Features

- 🔍 **Semantic Code Navigation**: Find symbols, go to definitions, find references using Jedi
- 📊 **Module & Package Analysis**: List packages/modules, analyze dependencies, detect circular imports
- 🏗️ **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
- 📦 **Namespace Packages**: Handle packages distributed across multiple repositories
- 📝 **Standalone Scripts**: Analyze notebooks, scripts, and examples alongside formal packages
- 🔄 **Auto-Update**: Automatically detects and reflects file changes with smart cache invalidation
- ⚙️ **Configuration System**: Flexible configuration via files, env vars, or auto-discovery
- 🔌 **Extensible Plugin System**: Framework-specific analyzers (Pydantic, Django, Flask)
- 🚀 **Fast & Cached**: Intelligent caching with LRU eviction and performance optimization
- 🎯 **Type-Aware**: Full understanding of Python type hints and annotations
- 📈 **Performance Monitoring**: Built-in metrics tracking with p50/p95/p99 latencies
- 🛡️ **Input Validation**: Secure parameter validation and path checking
- 🤖 **Development Automation**: Release automation, dogfooding metrics, and worktree safety

## Installation

The PyEye can be installed in two ways:

### Option 1: Project-Specific Installation (Recommended)

Install directly into your Python project's virtual environment:

```bash
# Activate your project's virtual environment
source /path/to/your/project/venv/bin/activate

# Install from PyPI
pip install pyeye-mcp

# Or install from source
git clone https://github.com/okeefeco/pyeye-mcp.git
pip install -e ./pyeye-mcp
```

Then create a `.mcp.json` file in your project root:

```json
{
  "mcpServers": {
    "pyeye": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "pyeye.mcp"],
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
pipx install pyeye-mcp

# Or with pip
pip install --user pyeye-mcp

# Or from source
git clone https://github.com/okeefeco/pyeye-mcp.git
cd pyeye-mcp
pip install --user .
```

#### Configure with Claude Code (Global)

```bash
# Add the MCP server globally (available in all projects)
claude mcp add pyeye -s user -- python -m pyeye.mcp

# Verify it's connected
claude mcp list
```

### Configure with Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "python",
      "args": ["-m", "pyeye.mcp"],
      "env": {}
    }
  }
}
```

Note: Use the full path to Python if needed (e.g., `/usr/local/bin/python3` or `C:\\Python311\\python.exe`).

### Configure with GitHub Copilot (VS Code)

As of 2025, GitHub Copilot has full MCP support in VS Code, JetBrains, Eclipse, and Xcode. Follow these steps to use this PyEye server with GitHub Copilot:

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

Install the PyEye server in your project or globally:

```bash
# Option A: Install in your project's virtual environment (recommended)
pip install pyeye-mcp

# Option B: Install globally with pipx
pipx install pyeye-mcp

# Option C: Install from source
git clone https://github.com/okeefeco/pyeye-mcp.git
pip install -e ./pyeye-mcp
```

#### Step 3: Configure VS Code

Add the MCP server configuration to your VS Code settings:

**User Settings** (applies to all projects):

```json
// File: ~/.config/Code/User/settings.json (Linux/Mac)
// or %APPDATA%\Code\User\settings.json (Windows)
{
  "github.copilot.chat.mcpServers": {
    "pyeye": {
      "command": "python",
      "args": ["-m", "pyeye.mcp"],
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
    "pyeye": {
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "pyeye.mcp"],
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
4. You should see `pyeye` in the list
5. Test with: `@mcp pyeye find_symbol MyClass`

#### Troubleshooting

**MCP not available:**

- Ensure you have Copilot Business/Enterprise (not Free/Pro)
- Check that your organization admin enabled the MCP policy
- Update VS Code to version 1.102 or later

**Server not connecting:**

- Verify Python path in the configuration
- Check that `pyeye` is installed: `python -m pyeye.mcp --help`
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

The server can be configured to analyze packages in other locations. Create a `.pyeye.json` file in your project:

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

1. **Global Config**: `~/.config/pyeye/config.json` or `~/.pyeye.json` - User defaults
2. **Project Config**: `.pyeye.json` in project root or `[tool.pyeye]` in `pyproject.toml`
3. **Override File**: `.pyeye.override.json` - Local development overrides (git-ignored)
4. **Auto-Discovery**: Automatically detects source layouts and sibling packages if no packages configured

### Using Override Files

Override files are perfect for local development configurations that shouldn't be committed:

```json
// .pyeye.override.json (git-ignored)
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
| `PYEYE_MAX_PROJECTS` | 10 | Maximum number of projects in memory | 1-1000 |
| `PYEYE_CACHE_TTL` | 300 | Cache time-to-live in seconds | 0-86400 (24h) |
| `PYEYE_WATCHER_DEBOUNCE` | 0.5 | File watcher debounce delay in seconds | 0.0-10.0 |
| `PYEYE_MAX_FILE_SIZE` | 1048576 | Maximum file size to analyze (bytes) | 1KB-100MB |
| `PYEYE_MAX_WORKERS` | 4 | Maximum concurrent analysis workers | 1-32 |
| `PYEYE_ANALYSIS_TIMEOUT` | 30.0 | Analysis timeout in seconds | 1.0-300.0 |
| `PYEYE_ENABLE_MEMORY_PROFILING` | false | Enable memory profiling | true/false |
| `PYEYE_ENABLE_PERFORMANCE_METRICS` | false | Enable performance metrics | true/false |
| **Connection Pooling** | | **Optimize multi-project workflows** | |
| `PYEYE_ENABLE_CONNECTION_POOLING` | true | Enable connection pooling for multiple projects | true/false |
| `PYEYE_POOL_MAX_CONNECTIONS` | 10 | Maximum pooled project connections | 1-100 |
| `PYEYE_POOL_TTL` | 3600 | Connection time-to-live in seconds | 60-86400 |

#### Performance Tuning Examples

**Large codebase with stable files:**

```bash
export PYEYE_MAX_PROJECTS=50        # Handle more projects
export PYEYE_CACHE_TTL=1800         # 30 minute cache
export PYEYE_WATCHER_DEBOUNCE=2.0   # Less frequent updates
```

**Active development with frequent changes:**

```bash
export PYEYE_MAX_PROJECTS=5         # Fewer projects, faster switching
export PYEYE_CACHE_TTL=60           # 1 minute cache
export PYEYE_WATCHER_DEBOUNCE=0.1   # Near real-time updates
```

**Memory-constrained environment:**

```bash
export PYEYE_MAX_PROJECTS=3         # Minimal project cache
export PYEYE_MAX_FILE_SIZE=524288   # 512KB file limit
export PYEYE_MAX_WORKERS=2          # Fewer workers
```

This file is automatically ignored by git and takes precedence over all other configuration sources.

### Auto-Detection of Source Layouts

PyEye automatically detects source layouts from `pyproject.toml` build backend metadata, supporting projects that use the `src/` directory pattern. This works with multiple build backends:

**Setuptools:**

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

**Poetry:**

```toml
[[tool.poetry.packages]]
include = "mypackage"
from = "src"
```

**Hatch:**

```toml
[tool.hatch.build.targets.wheel]
sources = ["src"]
```

**PDM:**

```toml
[tool.pdm.build]
package-dir = "src"
```

If no configuration is found in `pyproject.toml`, PyEye will also check for the presence of a `src/` directory containing Python packages and automatically add it to the package paths.

**Note:** Explicit `[tool.pyeye]` configuration always takes precedence over auto-detected layouts.

## Workflow Resources

pyeye provides workflow guidance as MCP Resources to help AI agents and users discover how to use tools effectively for common multi-step tasks.

### Discovering Workflows

List available workflows:

```text
"List pyeye workflow resources"
```

Or with Claude Code's MCP tools:

```python
ListMcpResourcesTool(server="pyeye")
```

### Using Workflows

**On-demand (trial):**

```text
"Use pyeye find-references workflow"
"Use pyeye refactoring workflow"
"Use pyeye code-understanding workflow"
"Use pyeye dependency-analysis workflow"
"Use pyeye code-review-standards workflow"
"Use pyeye code-review-security workflow"
"Use pyeye code-review-pr workflow"
```

**Permanent (adoption):**

```text
"Add pyeye find-references workflow to my CLAUDE.md"
```

The AI will fetch the workflow, add it to your context file, and automatically follow it in future sessions.

### Available Workflows

1. **find-references** - Find ALL class/function references including packages AND notebooks/scripts
   - Addresses limitation that `find_references` only works with packages (issue #236)
   - Combines `get_type_info`, `find_references`, and `Grep` for complete coverage

2. **refactoring** - Safe refactoring with impact analysis
   - Analyze subclasses, references, and dependencies before changing code
   - Includes change planning and validation steps
   - Prevents breaking changes through comprehensive analysis

3. **code-understanding** - Understand unfamiliar code structure
   - Systematic exploration from "What is this?" to "How does it work?"
   - Covers symbol location, inspection, hierarchy, execution flow, and usage patterns
   - Progressive understanding from basic to deep integration knowledge

4. **dependency-analysis** - Analyze module dependencies and architecture
   - Map import relationships and identify circular dependencies
   - Calculate coupling metrics and assess change impact
   - Understand architectural patterns and module relationships

5. **code-review-standards** - Python code review best practices (2025)
   - Industry standards: PEP 8, PEP 257, PEP 484, modern Python features
   - MCP-enhanced analysis: Type safety, anti-patterns, architecture review
   - Automated checks combined with semantic understanding

6. **code-review-security** - OWASP security code review
   - Security checklist: Input validation, injection prevention, auth patterns
   - Data flow analysis using MCP tools (trace user input through code)
   - Framework-specific security (Flask/Django plugin integration)

7. **code-review-pr** - Complete pull request review workflow
   - Combines automated checks, semantic analysis, and manual review
   - Step-by-step process: CI validation → impact analysis → standards → security
   - Constructive feedback guidelines and time budgets

### Example Usage Flow

**Discovery (README):** User learns workflows exist

```text
User: "How do I find all references to a class?"
AI: "There's a find-references workflow for that. Let me show you..."
```

**Trial (On-Demand):** User tries workflow

```text
User: "Use pyeye find-references workflow for this class"
AI: [fetches workflow from MCP Resources]
AI: [executes: get_type_info → find_references → Grep]
AI: "Found 15 references: 12 in packages, 3 in notebooks"
```

**Adoption (Self-Service):** User adds to context

```text
User: "That's useful - add it to my CLAUDE.md"
AI: [reads workflow resource, appends to CLAUDE.md]
AI: "✅ Workflow added to your context"
```

**Automatic Usage:** Future sessions use workflow automatically

```text
User: "Find all uses of this class"
AI: [sees workflow in context, follows steps automatically]
AI: [returns complete results without prompting]
```

### Benefits

- **Discover best practices** - Learn optimal tool combinations
- **Avoid trial and error** - Workflows encode discovered patterns
- **Handle tool limitations** - Includes workarounds (e.g., issue #236)
- **Self-service adoption** - Add workflows to your context as needed
- **Always up-to-date** - Workflows maintained with MCP server

### Technical Details

Workflows are exposed via MCP Resources protocol:

- **URI scheme**: `workflows://[workflow-name]`
- **Format**: Markdown (human and AI readable)
- **Access**: Via `ListMcpResourcesTool` and `ReadMcpResourceTool`
- **Integration**: Can be programmatically added to user context files

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
- **`find_subclasses`** - Find all classes inheriting from a given base class
  - Supports direct and indirect inheritance
  - Works with built-in classes (Exception, str, etc.)
  - Can show full inheritance hierarchy chains
  - Handles multiple inheritance correctly

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
PyEye
├── Core Server (FastMCP)
│   └── 17 MCP tools registered
├── Project Manager
│   ├── Multi-project support (LRU cache, max 10)
│   ├── Connection pooling (optional optimization)
│   ├── Namespace resolver
│   └── Configuration loader (multiple sources)
├── Analysis Engine
│   └── Jedi (semantic analysis & type inference)
├── Caching & Performance
│   ├── File watchers (watchdog with debouncing)
│   ├── Granular cache (5min TTL with smart invalidation)
│   ├── Metrics collection (p50/p95/p99 latencies)
│   └── Performance monitoring & reporting
├── Validation & Security
│   ├── Input validation (MCP tool parameters)
│   ├── Path security checks
│   └── Safe file operations
├── Plugin System
│   ├── Base plugin class (AnalyzerPlugin)
│   ├── Pydantic plugin (7 specialized tools)
│   ├── Django plugin (5 specialized tools)
│   └── Flask plugin (8 specialized tools)
├── Utility Systems
│   ├── Dependency tracking & circular detection
│   ├── Import analysis & re-export resolution
│   ├── Scope management (main/all/namespace scoping)
│   ├── Async utilities (concurrent operations)
│   └── Cross-platform path handling
└── Development & Automation
    ├── Release automation agent
    ├── Dogfooding metrics tracking
    └── Worktree safety management
```

## Plugin Development

Create custom plugins for your project patterns:

```python
from pyeye.plugins.base import AnalyzerPlugin

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

## Performance Monitoring Details

The server includes comprehensive performance monitoring to help identify bottlenecks and optimize performance for large-scale deployments.

### Connection Pooling for Multi-Project Workflows

Connection pooling is enabled by default to optimize performance when working with multiple projects. You can customize the pooling behavior:

```bash
# Customize connection pooling (already enabled by default)
export PYEYE_POOL_MAX_CONNECTIONS=20  # Increase pool size for many projects
export PYEYE_POOL_TTL=7200            # Increase TTL to 2 hours

# Or disable pooling if needed
export PYEYE_ENABLE_CONNECTION_POOLING=false

# Start the server
uv run mcp dev src/pyeye/server.py
```

Connection pooling provides significant performance improvements:

- **Reduced initialization time** for frequently accessed projects
- **Shared connections** across multiple analysis operations
- **Automatic eviction** of idle connections based on TTL
- **Memory-efficient** pooling with configurable limits

### Metrics Tracked

- **Operation Latencies**: p50, p95, p99 percentiles for all MCP tools
- **Cache Performance**: Hit rate, miss rate, evictions
- **Connection Pool Stats**: Pool size, hits, misses, evictions, reuse rate
- **Memory Usage**: RSS, VMS, percentage used
- **Error Rates**: Track failures per operation
- **Throughput**: Operations per second

### Performance Baselines

The following performance baselines are enforced in CI:

| Operation | p50 (ms) | p95 (ms) | p99 (ms) |
|-----------|----------|----------|----------|
| symbol_search | 50 | 100 | 200 |
| goto_definition | 30 | 75 | 150 |
| find_references | 100 | 250 | 500 |
| cache_lookup | 0.1 | 0.5 | 1.0 |

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
uv run mcp dev src/pyeye/server.py
```

## Documentation

- [Installation Guide](#installation)
- [Configuration Guide](#configuration)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [API Reference](#core-tools)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Acknowledgments

Built on top of:

- [Jedi](https://github.com/davidhalter/jedi) - Python static analysis and type inference
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [Watchdog](https://github.com/gorakhargosh/watchdog) - File system monitoring
