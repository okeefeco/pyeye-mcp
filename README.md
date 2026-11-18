# PyEye 👁️

## PyEye Server

[![CI](https://github.com/okeefeco/pyeye-mcp/workflows/CI/badge.svg)](https://github.com/okeefeco/pyeye-mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/okeefeco/pyeye-mcp/graph/badge.svg?token=XE5T93O8EC)](https://codecov.io/gh/okeefeco/pyeye-mcp)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

An extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis, navigation, and understanding capabilities for AI assistants like Claude.

## Features

- 🔍 **Semantic Code Navigation**: Resolve any identifier to a stable canonical handle, then inspect or outline it
- 📊 **Structural Traversal**: Walk relationship edges ([listed below](#known-limitation-no-reverse-references)) one hop with `expand`, or many with `trace`
- 🤝 **Honest by Construction**: Unsupported questions (notably "who calls this") are *refused*, not guessed; absent counts mean "not measured", never "zero"
- 🏗️ **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
- 📦 **Namespace Packages**: Handle packages distributed across multiple repositories
- 📝 **Standalone Scripts**: Analyze standalone `.py` files (for example in `scripts/` or `examples/` directories) alongside formal packages
- 🔄 **Auto-Update**: Watches the project's files and drops cached results when they change
- ⚙️ **Configuration System**: Configure packages and namespaces in config files, or let pyeye auto-discover them; tune performance with environment variables
- 🔌 **Plugin System**: Built-in framework analyzers (Pydantic, Django, Flask)
- 🎯 **Type-Aware**: Uses Jedi's type inference, including type hints and annotations
- 📈 **Performance Metrics**: Optional per-tool latency metrics (`get_performance_metrics`)

## Installation

PyEye can be installed in three ways: as a Claude Code plugin (zero-config), into your project's venv, or globally.

### Option 0: Claude Code Plugin (zero-config)

When PyEye is installed as a Claude Code plugin, it installs its own
dependencies into a per-user virtual environment on the first session start, and
reinstalls them only when its lockfile changes. No manual `pip install` is needed.

- **Requirement**: `uv` must be on your `PATH`. See [uv installation](https://docs.astral.sh/uv/getting-started/installation/).

This works on Linux, macOS, and Windows without OS-specific configuration.

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
claude mcp add pyeye -s user -- pyeye-mcp

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

### Configure with GitHub Copilot and other MCP clients

pyeye is a standard stdio MCP server, so any MCP client can run it. Point the
client at one of the [entry points](docs/reference/cli.md) (for example
`python -m pyeye.mcp`, using the Python that has pyeye installed).

Where the server entry goes depends on the client and its version, and changes
often, so follow the client's own documentation rather than a copy here:

- **VS Code (GitHub Copilot):** [Add and manage MCP servers in VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers).
  Run **MCP: List Servers** from the Command Palette to check that `pyeye` started.
- **JetBrains IDEs, Visual Studio, Eclipse and Xcode (GitHub Copilot):**
  [Extending Copilot Chat with MCP](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/extend-copilot-chat-with-mcp).
  On Copilot Business and Enterprise, an administrator must first enable the
  organization's **MCP servers in Copilot** policy.

If the server starts but can't import your project's dependencies, point the
entry at your project's virtual-environment Python.

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

1. **Global Config**: the first of <!-- fact:begin config.files.global -->`~/.config/pyeye/config.json`, `~/.pyeye.json`<!-- fact:end --> that exists - User defaults
2. **Project Config**: the first of <!-- fact:begin config.files.project -->`.pyeye.json`, `.pyeye.yaml`, `.pyeye.yml`, `pyproject.toml`, `.claude/pyeye.json`<!-- fact:end --> in the project root (in `pyproject.toml`, the `[tool.pyeye]` section)
3. **Override File**: <!-- fact:begin config.files.override -->`.pyeye.override.json`<!-- fact:end --> - Local development overrides (keep it out of git)
4. **Auto-Discovery**: Automatically detects source layouts and sibling packages if no packages configured

The top-level keys pyeye reads are <!-- fact:begin config.keys -->`packages`, `namespaces`, `standalone`, `scope_defaults`, `scope_aliases`<!-- fact:end -->.

### Using Override Files

Override files are perfect for local development configurations that shouldn't be committed.
`.pyeye.override.json` takes precedence over the other sources; add it to your
project's `.gitignore`:

```json
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

Performance settings are configured through environment variables. The
[generated reference](docs/reference/env-vars.md) lists every `PYEYE_*` variable
pyeye reads, with its default, range and status (live or deprecated). Deprecated
variables have no effect.

These are read when the server starts, from the server's own environment.
The MCP client starts the server, so set them on its server entry (Claude
Code: `claude mcp add pyeye -s user -e PYEYE_MAX_PROJECTS=20 -- python -m pyeye.mcp`;
other clients take an `env` map in their config), then restart the client.
An `export` in your shell only reaches the server if the client was launched
from that shell.

Packages and namespaces are not configured through environment variables. Use
`.pyeye.json`, `pyproject.toml`, the global config file, or the
`configure_packages` tool (see [Configuration](#configuration)).

#### Sizing the parsed-file cache

pyeye walks every `.py` file in a project to build its name index and its
subclass and import graphs, and rebuilds them after every file change.
`PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` decides how many of those parsed files stay
in memory between walks. Answers are the same at any value; only speed and
memory change.

- **Set it at or above your project's `.py` file count** (the default is
  <!-- fact:begin env.PYEYE_ARTIFACT_CACHE_MAX_ENTRIES.default -->2000<!-- fact:end -->). Each rebuild after an edit then re-parses only what
  changed.
- **Don't set it just below that count.** The cache then evicts files during
  each walk and parses them again in the same walk, so it is both slower *and*
  uses more memory than the default.
- **To save memory, go well below it** and accept slower rebuilds.

This advice comes from measurements on one large project in [#768](https://github.com/okeefeco/pyeye-mcp/issues/768).

#### Performance Tuning Examples

Set the variables on the server entry, so they reach the server however the
client was started. For example, with Claude Code:

```bash
# Keep more projects in memory, cache longer and batch file changes more
claude mcp add pyeye -s user \
  -e PYEYE_MAX_PROJECTS=50 -e PYEYE_CACHE_TTL=1800 -e PYEYE_WATCHER_DEBOUNCE=2.0 \
  -- pyeye-mcp

# Use less memory: fewer projects and fewer parsed files kept
claude mcp add pyeye -s user \
  -e PYEYE_MAX_PROJECTS=3 -e PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=250 \
  -- pyeye-mcp
```

Other clients take the same names in the server entry's `env` map.

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

## Core Tools

PyEye exposes a small set of **progressive-disclosure primitives** that work on
canonical handles (a re-exported path collapses to its definition site). They are
cheap by default: they return structural facts and pointers, never source
content.

The core tools are <!-- fact:begin tools.core -->`configure_packages`, `expand`, `inspect`, `outline`, `resolve`, `resolve_at`, `trace`<!-- fact:end -->. The usual
flow is to `resolve` a name to a handle, `inspect` or `outline` it, then follow
relationship edges with `expand` (one hop) or `trace` (many hops);
`configure_packages` registers extra package locations. The
[tool reference](docs/reference/tools.md) gives every tool's parameters and
defaults, and the [edge reference](docs/reference/edges.md) lists the supported
edges. For worked examples, see the `python-explore` skill
(`skills/python-explore/SKILL.md`).

### Known limitation: no reverse references

The interface does not answer **"who calls / references this"**. Reverse-reference
support is deferred to a planned Pyright backend
([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). When you ask for a
`callers` or `references` edge, pyeye reports it as unsupported rather than
guessing, and `inspect`'s `edge_counts` omits those keys entirely instead of
reporting `0`. Delegate caller questions to a language server; pyeye's `resolve`
gives you the definition-site position an LSP reference query needs.

Forward and structural questions *are* answered, through the implemented edges:
<!-- fact:begin edges.implemented -->`members`, `callees`, `imported_by`, `subclasses`, `superclasses`, `imports`, `enclosing_scope`, `submodules`, `re_exports`<!-- fact:end -->.
**Static-surface ceiling:** each edge measures a stated scope, and its answer is
complete only over that scope. The
[edge reference](docs/reference/edges.md#ceilings) gives each edge's ceiling.

> **Removed in v2.0.** `find_references`, `get_call_hierarchy`, and
> `analyze_dependencies` were removed in
> [#505](https://github.com/okeefeco/pyeye-mcp/issues/505) — not deprecated —
> because they returned confidently wrong answers rather than merely incomplete
> ones. See the CHANGELOG's migration map for replacements.

### Framework-Specific Tools (Auto-Activated)

A plugin's tools are registered when its framework is detected in the project.
See the [tool reference](docs/reference/tools.md#plugin-tools) for each tool's
parameters.

- **Django:** <!-- fact:begin tools.plugin.django -->`find_django_migrations`, `find_django_models`, `find_django_templates`, `find_django_urls`, `find_django_views`<!-- fact:end -->
- **Pydantic:** <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->
- **Flask:** <!-- fact:begin tools.plugin.flask -->`find_cli_commands`, `find_error_handlers`, `find_flask_blueprints`, `find_flask_config`, `find_flask_extensions`, `find_flask_routes`, `find_flask_templates`, `find_flask_views`<!-- fact:end -->

## Advanced Features

### Multi-Project Support

Analyze your main project along with local dependencies. Put them in
`.pyeye.json` (see [Configuration](#configuration)), or ask your assistant to
call the [`configure_packages`](docs/reference/tools.md#configure_packages) tool
with arguments like these:

```json
{
  "packages": ["../my-lib", "~/repos/shared-utils"],
  "namespaces": {"company": ["~/repos/company-auth", "~/repos/company-api"]}
}
```

### Namespace Packages

Handle packages distributed across multiple repositories, for example
`company.auth` in one repo and `company.api` in another:

```json
{
  "namespaces": {"company": ["~/repos/company-auth", "~/repos/company-api"]}
}
```

### Auto-Update on File Changes

The server watches the project's files and drops cached results for the files
that change, so answers follow your edits without a restart. See
[Caching](docs/architecture/caching.md) for how invalidation works.

## Architecture

The architecture pages describe how pyeye works inside:

- [Resolution](docs/architecture/resolution.md): how a name becomes a canonical handle
- [Caching](docs/architecture/caching.md): what is cached and when it is invalidated
- [Plugin system](docs/architecture/plugin-system.md): how framework plugins are detected and register their tools

## Plugin Development

Plugins are built into pyeye; there is no dynamic loading. To add a framework
plugin, follow [Adding a plugin](docs/architecture/plugin-system.md#adding-a-plugin).

## Performance Monitoring

Set `PYEYE_ENABLE_PERFORMANCE_METRICS` to register the `get_performance_metrics`
tool, which reports per-tool latencies. Its parameters are in the
[tool reference](docs/reference/tools.md#admin-tools).

## Development

```bash
# Install pyeye with its development dependencies, exactly as locked
uv sync --frozen

# Run tests
uv run pytest

# Format and lint
uv run black src/
uv run ruff check src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full setup and workflow.

## Documentation

The full documentation is published at **[okeefeco.github.io/pyeye-mcp](https://okeefeco.github.io/pyeye-mcp/)**, built from the Markdown in this repository.

- [Installation Guide](#installation)
- [Configuration Guide](#configuration)
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [API Reference](docs/reference/tools.md) - every tool and its parameters

## Security

Please report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/okeefeco/pyeye-mcp/security/advisories/new),
not in public issues. [SECURITY.md](SECURITY.md) covers supported versions, what
to expect after reporting, and pyeye's security model (static analysis only; it
reads whatever paths the MCP client points it at).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

MIT License - see [LICENSE](LICENSE) for details

## Acknowledgments

Built on top of:

- [Jedi](https://github.com/davidhalter/jedi) - Python static analysis and type inference
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) - MCP server framework (`MCPServer`)
- [Watchdog](https://github.com/gorakhargosh/watchdog) - File system monitoring
