# PyEye Server - Full Documentation

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

The PyEye Server provides semantic code analysis for Python projects through the Model Context Protocol (MCP). It enables AI assistants like Claude to understand Python codebases without reading every file.

### Key Capabilities

- **Semantic Analysis**: Understands Python code structure, not just text matching
- **Multi-Project**: Analyzes multiple projects and dependencies simultaneously
- **Auto-Update**: Follows file changes without a restart
- **Framework plugins**: Built-in plugins for Django, Pydantic and Flask
- **Cached**: Keeps parse and analysis results in memory and drops them when files change

## Installation

### Prerequisites

- Python <!-- fact:begin project.requires_python -->`>=3.11`<!-- fact:end -->
- Git
- uv (recommended) or pip

### Install from Source

```bash
# Clone repository
git clone https://github.com/okeefeco/pyeye-mcp.git
cd pyeye-mcp

# Install dependencies with uv
uv sync --frozen

# Or with pip
pip install -e .
```

### Configure for Claude Code

pyeye analyzes the directory the server starts in, so start it from your
project. `uv run --project` uses pyeye's checkout for the environment without
changing the working directory (`uv --directory` would change it, and pyeye
would analyze its own checkout instead of your project):

These commands need [uv](https://docs.astral.sh/uv/). After a pip install, use
the installed `pyeye-mcp` command instead (see the README's
[Installation](README.md#installation)).

```bash
# Add globally (available in all projects)
claude mcp add pyeye -s user -- \
  uv run --project ~/GitHub/pyeye-mcp pyeye-mcp

# Or add to specific project
cd your-project
claude mcp add pyeye -- \
  uv run --project ~/GitHub/pyeye-mcp pyeye-mcp

# Verify connection
claude mcp list
```

The [entry points](docs/reference/cli.md) lists the commands that start the
server. For a PyPI install, see the README's [Installation](README.md#installation).

### Configure for Claude Desktop

On macOS, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/pyeye-mcp", "pyeye-mcp"]
    }
  }
}
```

Claude Desktop doesn't start the server in your project, so ask for the
project explicitly: every analysis tool takes a `project_path` argument (the
admin tools don't; see the [tool reference](docs/reference/tools.md)).

## Configuration

### Configuration File (.pyeye.json)

Create in your project root:

```json
{
  "packages": [
    ".",
    "../my-shared-library",
    "~/repos/company-utils",
    "/absolute/path/to/package",
    "~/repos/plugins/*"
  ],
  "namespaces": {
    "mycompany": [
      "~/repos/mycompany-*"
    ],
    "plugins": [
      "./plugins/builtin",
      "~/repos/community-plugins"
    ]
  }
}
```

`packages` lists package directories: relative to the project, under your home
directory (`~`), absolute, or a glob. Each `namespaces` entry names a namespace
package and lists the repositories that each hold part of it, one by one or as a
glob. A glob (`*` only) expands to its matching directories in sorted order, and
that order is the namespace's precedence: the first repository to define a module
wins. A glob that matches nothing leaves the namespace with no repositories, and
its scope is then reported as unsearched (#872).

Older docs also showed keys that are deprecated and have no effect: pyeye never
read them, and it logs a warning when one is set (#581). They are
<!-- fact:begin config.ignored_keys -->`analysis`, `cache`, `default_packages`, `exclude`, `exclude_patterns`, `logging`, `performance`, `plugins`, `watch_exclude`<!-- fact:end -->. Use the
[environment variables](docs/reference/env-vars.md) for cache tuning.

### Configuration in pyproject.toml

```toml
[tool.pyeye]
packages = [
    "../shared-lib",
    "~/repos/utils"
]

[tool.pyeye.namespaces]
company = [
    "~/repos/company-auth",
    "~/repos/company-api"
]
```

### Environment Variables

Packages and namespaces are **not** configured through environment variables.
Use a project config file (above), the global configuration (below), or the
`configure_packages` tool. Environment variables only tune performance and
logging; the [reference](docs/reference/env-vars.md) lists them, and the
README's [Performance Settings](README.md#performance-settings) explains how to
set them.

### Global Configuration

Create `~/.config/pyeye/config.json`:

```json
{
  "packages": [
    "~/my-common-libs",
    "~/work/shared-utils"
  ]
}
```

### Configuration Precedence

The README's [Configuration Methods](README.md#configuration-methods) gives the
order in which the sources are read and override each other.
<!-- TODO(#830): bind the config file list and precedence to a fact once the
CONFIG_FILES / config-keys extractor exists, instead of linking the README. -->

## Tools Reference

PyEye's core tools are <!-- fact:begin tools.core -->`configure_packages`, `expand`, `inspect`, `outline`, `resolve`, `resolve_at`, `trace`<!-- fact:end -->: the
progressive-disclosure primitives, plus `configure_packages` for registering
extra package locations. The [tool reference](docs/reference/tools.md) gives
every tool's parameters and defaults, and the
[edge reference](docs/reference/edges.md) lists the supported edges. Worked
examples live in the `python-explore` skill (`skills/python-explore/SKILL.md`).

The v1 navigation tools were removed in 2.0. The CHANGELOG's migration map lists
the replacement for each.

### Framework-Specific Tools

A plugin's tools are registered when its framework is detected in the project.
Their parameters are in the [tool reference](docs/reference/tools.md#plugin-tools),
and each plugin's page in [docs/api/](docs/api/README.md) explains what it finds.

- **Django:** <!-- fact:begin tools.plugin.django -->`find_django_migrations`, `find_django_models`, `find_django_templates`, `find_django_urls`, `find_django_views`<!-- fact:end -->
- **Pydantic:** <!-- fact:begin tools.plugin.pydantic -->`find_computed_fields`, `find_field_validators`, `find_model_config`, `find_pydantic_models`, `find_validators`, `get_model_schema`, `trace_model_inheritance`<!-- fact:end -->
- **Flask:** <!-- fact:begin tools.plugin.flask -->`find_cli_commands`, `find_error_handlers`, `find_flask_blueprints`, `find_flask_config`, `find_flask_extensions`, `find_flask_routes`, `find_flask_templates`, `find_flask_views`<!-- fact:end -->

## Architecture

The design contracts are in `docs/architecture/`:
[Resolution and Determinism](docs/architecture/resolution.md),
[Plugin System](docs/architecture/plugin-system.md) and
[Caching Strategy](docs/architecture/caching.md).

## Security

[SECURITY.md](SECURITY.md) covers pyeye's [security model](SECURITY.md#security-model):
what it reads and writes, what its path checks cover, and how to report a
vulnerability.

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
      "./plugins/builtin",
      "~/repos/community-plugins",
      "~/my-plugins"
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

Fuller configurations, with scope aliases and defaults, are in
[examples/configurations/](examples/configurations/).

## Plugin Development

Plugins are built into pyeye; there is no dynamic loading. To add a framework
plugin, follow [Adding a plugin](docs/architecture/plugin-system.md#adding-a-plugin).

## Troubleshooting

[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) covers more cases.

### Server Not Starting

1. Check the Python version: pyeye needs Python <!-- fact:begin project.requires_python -->`>=3.11`<!-- fact:end -->
2. Verify installation: `uv sync --frozen` or `pip install -e .`
3. Check logs: set `PYEYE_LOG_LEVEL=DEBUG` on the server entry, and `PYEYE_LOG_FILE` to write them to a file (see the [environment variables](docs/reference/env-vars.md))

### Packages Not Found

1. Verify paths in `.pyeye.json`
2. Check path resolution: Use absolute paths for testing
3. Verify packages exist and contain Python files

### Stale Results

The caches live in the server's memory. Restart the server (reconnect it in
your MCP client) to start from empty caches. To keep cached lookups for a
shorter time, lower `PYEYE_CACHE_TTL` (see the [environment variables](docs/reference/env-vars.md)).

### File Changes Not Detected

1. Check that the file system supports inotify (Linux) or FSEvents (macOS)
2. Increase the logging level (`PYEYE_LOG_LEVEL=DEBUG`) to see watcher events

### Performance Issues

1. Reduce number of included packages
2. Increase the cache TTL (`PYEYE_CACHE_TTL`; see the [environment variables](docs/reference/env-vars.md))
3. Size the parsed-file cache: see the README's [Sizing the parsed-file cache](README.md#sizing-the-parsed-file-cache)

### MCP Connection Issues

1. Check the server's status: `/mcp` inside Claude Code
2. Check MCP server health: `claude mcp list`
3. Review Claude logs for connection errors
4. Try reconnecting: `claude mcp remove pyeye && claude mcp add ...`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT License - See [LICENSE](LICENSE) for details.
