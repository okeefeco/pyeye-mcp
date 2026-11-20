# PyEye 👁️

## PyEye Server

[![CI](https://github.com/okeefeco/pyeye-mcp/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/okeefeco/pyeye-mcp/actions/workflows/ci.yml?query=branch%3Amain)
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

| You use | Recommended | Alternatives |
|---|---|---|
| Claude Code | [The plugin](#claude-code-plugin-recommended) | [`claude mcp add`](#claude-code-without-the-plugin) |
| Another MCP client (Claude Desktop, VS Code, …) | [`uvx pyeye-mcp`](#other-mcp-clients) | [An installed `pyeye-mcp`](#installing-the-command) |
| One project, pinned to a version | [Install into the project's environment](#install-into-a-projects-environment) | |
| You're working on pyeye itself | [CONTRIBUTING](CONTRIBUTING.md#setting-up-your-environment) | |

pyeye needs Python <!-- fact:begin project.requires_python -->`>=3.11`<!-- fact:end -->.
The plugin and `uvx` need [uv](https://docs.astral.sh/uv/getting-started/installation/).
pyeye analyses the directory its server starts in, and every analysis tool also
takes a `project_path`. The [entry points](docs/reference/cli.md) list the
commands that start the server.

**Your project's environment.** pyeye reads the project's installed
third-party packages (`requests`, `django`, …) from the project's own Python
environment, whichever way pyeye itself runs. It uses the first of:

1. the `environment` setting in the project's pyeye config: the path to a
   virtualenv, or `false` for none;
2. a virtualenv in the project: `.venv`, `venv` or `env` (for a project that is
   itself a package, in its parent directory too, unless that directory is
   shared: group- or world-writable, or owned by another user);
3. the activated environment (`VIRTUAL_ENV`, or `CONDA_PREFIX` for conda), as
   Poetry, Pipenv and Hatch set it for an environment outside the project,
   unless it is pyeye's own environment, which is skipped. One activated
   environment serves every project that has none of its own.

It reads the environment's packages from disk and never runs its Python. It
skips an environment, or a path one adds, that is in or contains a system
directory or a credential store, with a warning. When it finds none, a
third-party import doesn't resolve, and `resolve` and `inspect` say that no
environment was found (#993).

### Claude Code plugin (recommended)

In Claude Code:

```text
/plugin marketplace add okeefeco/pyeye-mcp
/plugin install pyeye@pyeye-marketplace
```

From a shell, the same is `claude plugin marketplace add okeefeco/pyeye-mcp`
followed by `claude plugin install pyeye@pyeye-marketplace`. Claude Code's
[plugin documentation](https://code.claude.com/docs/en/plugins/install) covers
updating and removing plugins.

The plugin brings:

- the pyeye MCP server;
- the skills `python-explore`, `architecture-review`, `duplication-review` and
  `decision-log`;
- a session-start hook that installs pyeye's dependencies with `uv` into a
  per-user environment, the first time and again whenever its lockfile changes.

Install pyeye **either** as the plugin **or** with `claude mcp add`, not both:
with both, every tool appears twice (`mcp__plugin_pyeye_pyeye__…` and
`mcp__pyeye__…`). If you added it with `claude mcp add` before, run
`claude mcp remove pyeye`.

### Claude Code without the plugin

```bash
claude mcp add pyeye -s user -- uvx pyeye-mcp
claude mcp list   # check that pyeye is connected
```

`uvx` runs the latest release from PyPI in an environment of its own. To use an
installed command instead, see [Installing the command](#installing-the-command)
and register `-- pyeye-mcp`. Claude Code's
[MCP documentation](https://code.claude.com/docs/en/mcp) covers scopes and options.

### Other MCP clients

pyeye is a standard stdio MCP server. Give your client the command `uvx` with
the argument `pyeye-mcp`, or an installed `pyeye-mcp`. Where that goes depends
on the client, so follow its own documentation:

- **Claude Desktop:** [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers).
  Claude Desktop doesn't start the server in your project, so ask for the
  project explicitly: every analysis tool takes a `project_path` argument.
- **VS Code (GitHub Copilot):** [Add and manage MCP servers in VS Code](https://code.visualstudio.com/docs/agent-customization/mcp-servers).
  Run **MCP: List Servers** from the Command Palette to check that `pyeye` started.
- **JetBrains IDEs, Visual Studio, Eclipse and Xcode (GitHub Copilot):**
  [Extending Copilot Chat with MCP](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/extend-copilot-chat-with-mcp).

For example, in a client that takes an `mcpServers` map:

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "uvx",
      "args": ["pyeye-mcp"]
    }
  }
}
```

### Installing the command

To install `pyeye-mcp` once instead of running it through `uvx`, use
[`uv tool install pyeye-mcp`](https://docs.astral.sh/uv/guides/tools/) or
[`pipx install pyeye-mcp`](https://pipx.pypa.io/). The server command is then
`pyeye-mcp`.

### Install into a project's environment

Install pyeye into the project's virtual environment (`pip install pyeye-mcp`,
or `uv pip install pyeye-mcp`, with that environment active), then point your
client at that environment's Python. For Claude Code, a `.mcp.json` in the
project root:

```json
{
  "mcpServers": {
    "pyeye": {
      "type": "stdio",
      "command": "/path/to/your/project/.venv/bin/python",
      "args": ["-m", "pyeye.mcp"]
    }
  }
}
```

On Windows the path is `.venv\Scripts\python.exe`. A bare `"command": "python"`
works only if your MCP client was started from a shell with that environment
active; otherwise it runs whichever Python is first on the client's `PATH`.

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
4. **Auto-Discovery**: a `src/` layout, only if no `packages` are configured yet, and the path dependencies the project's `pyproject.toml` declares, always (below). (The project's virtualenv isn't a package: pyeye reads it as the project's environment, above.) `configure_packages` lists what was discovered under `discovered`, and a save never writes it to `.pyeye.json`.
5. **This session's unsaved additions**: packages, namespaces and standalone directories added with `configure_packages(save=false)`. They're applied last and don't stop auto-discovery

**Packages beside your project.** pyeye doesn't guess at neighbouring directories (#1035). A package that lives beside your project is analysed when one of these says so:

- **A path dependency in `pyproject.toml`,** read statically:
  - `[tool.uv.sources]` entries with a `path`;
  - `[tool.uv.workspace]` `members` (a glob member stays inside the workspace; a literal path can point anywhere);
  - Poetry `path` dependencies, in the main table and in groups;
  - `name @ file:...` references in `[project]` dependencies, optional dependencies and `[dependency-groups]`. PDM's `${PROJECT_ROOT}` and Hatch's `{root:uri}` are expanded.
- **An editable install** in the project's environment that writes its path to a `.pth` file. That covers every common build backend with a `src/` layout, and flat layouts on hatchling, pdm-backend, flit, poetry-core and uv_build. Setuptools' flat-layout install uses an import-hook `.pth` instead, which pyeye doesn't run, so declare such a package or configure it.
- **Your pyeye config:** `packages`, `namespaces`, or `configure_packages`.

A declared directory with a `src/` layout is read from its `src/`. When a top-level import doesn't resolve, `resolve` and `inspect` suggest declaring the package or adding it with `configure_packages`.

The top-level keys pyeye reads are <!-- fact:begin config.keys -->`packages`, `namespaces`, `standalone`, `scope_defaults`, `scope_aliases`, `environment`<!-- fact:end -->.

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
The MCP client starts the server, so set them on its server entry and restart
the client. In Claude Code, remove the server and add it again with `-e` flags,
using the command you registered it with (here `uvx pyeye-mcp`):
`claude mcp remove pyeye && claude mcp add pyeye -s user -e PYEYE_MAX_PROJECTS=20 -- uvx pyeye-mcp`.
Other clients take an `env` map in their config. An `export` in your shell only
reaches the server if the client was launched from that shell.

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
client was started. For example, with Claude Code (remove the server first, and
use the command you registered it with):

```bash
claude mcp remove pyeye

# Keep more projects in memory, cache longer and batch file changes more
claude mcp add pyeye -s user \
  -e PYEYE_MAX_PROJECTS=50 -e PYEYE_CACHE_TTL=1800 -e PYEYE_WATCHER_DEBOUNCE=2.0 \
  -- uvx pyeye-mcp

# Or use less memory: fewer projects and fewer parsed files kept
claude mcp add pyeye -s user \
  -e PYEYE_MAX_PROJECTS=3 -e PYEYE_ARTIFACT_CACHE_MAX_ENTRIES=250 \
  -- uvx pyeye-mcp
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

Two conditions apply. `pyproject.toml` is read only when it is the project's config
file, the first of the project config files above that exists, so a
`.pyeye.json` or `.pyeye.yaml` in the root means it is never read. And detection
only runs when no `packages` are set yet, including by your global config.

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

Set `PYEYE_ENABLE_PERFORMANCE_METRICS` to true to register the admin tools:
<!-- fact:begin tool.get_performance_metrics -->`get_performance_metrics`<!-- fact:end -->, which reports per-tool latencies, and
<!-- fact:begin tool.get_connection_diagnostics -->`get_connection_diagnostics`<!-- fact:end -->, which reports the server's
connection state and recent errors. Their parameters are in the
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
