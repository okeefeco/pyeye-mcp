# PyEye - API Reference

This directory holds reference documentation for PyEye's **framework plugin
tools** and for `configure_packages`. The core navigation interface is documented
elsewhere, on purpose (see below).

## 📚 Documentation Structure

- **[Pydantic Tools](./pydantic-tools.md)** - Pydantic model, validator, and schema analysis
- **[Flask Tools](./flask-tools.md)** - Flask routes, blueprints, templates, extensions, and error handlers
- **[Django Tools](./django-tools.md)** - Django models, views, URLs, templates, and migrations
- **[configure_packages](#configure_packages)** - Register additional package locations (below)

Plugin tools are registered only when the server detects the framework in the
project, under the names each plugin declares in `register_tools()` (pinned by
`tests/test_plugin_tool_names_conformance.py`). To see the tools a running
server exposes, list them from your MCP client.

## 🧭 Core Navigation: Where It's Documented

The core interface is six progressive-disclosure primitives: `resolve`,
`resolve_at`, `inspect`, `outline`, `expand`, `trace`. They have no page here:

- The README's [Core Tools](../../README.md#core-tools) section lists them, and
  states the known limitation that "who calls / references this" is not answered
  (deferred to [#333](https://github.com/okeefeco/pyeye-mcp/issues/333)).
- The `python-explore` skill (`skills/python-explore/SKILL.md`) covers the
  mechanics, the supported-edge list, and worked examples. A test checks it
  against the live edge registry, so it can't drift silently the way a
  hand-maintained page here would.

The v1 navigation tools were removed in 2.0. The CHANGELOG's migration map lists
the replacement for each.

## configure_packages

Register additional package locations, namespace packages, and standalone script
directories for analysis, alongside the current project.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `packages` | `list[str]` | `None` | Package paths to add |
| `namespaces` | `dict[str, list[str]]` | `None` | Namespace name → repo paths that contribute to it |
| `standalone_dirs` | `list[str]` | `None` | Directories of standalone Python scripts (non-package files). Every `.py` file under them is analysed |
| `save` | `bool` | `True` | Write the updated configuration to `.pyeye.json` |

Calls are **additive**: `packages` and `standalone_dirs` are appended to what is
already configured, and `namespaces` are merged by name. With `save=True`, the
file is written only when at least one of `packages`, `namespaces`, or
`standalone_dirs` is given.

> **Removed in 2.0:** `recursive`, `file_pattern` and `exclude_patterns`. They
> were saved to `.pyeye.json` but never took effect
> ([#513](https://github.com/okeefeco/pyeye-mcp/issues/513)). Passing them is
> not an error; they are ignored. If an existing `.pyeye.json` still contains
> them under `standalone`, they are ignored with a warning, and the response
> carries a `warnings` entry naming them.

### Returns

```typescript
{
  packages: string[];                     // All package paths in use; the project itself is first
  namespaces: {[name: string]: string[]}; // Configured namespace packages
  standalone: {                           // Standalone-script configuration
    dirs: string[];
  };
  config_file: string;                    // Path of the project's .pyeye.json
  warnings?: string[];                    // Present only if the config has ignored keys
}
```

### Example

```python
configure_packages(
    packages=["../my-lib", "~/repos/shared-utils"],
    namespaces={"company": ["~/repos/company-auth", "~/repos/company-api"]},
)

# Add a package for this session only, without writing .pyeye.json
configure_packages(packages=["../temp-package"], save=False)
```

After a call, cached analyzers for every configured path are invalidated, so
the next query sees the new configuration.

## ⚙️ Configuration Sources

Configuration can also be set without calling the tool. The loader's own
docstring (`ProjectConfig.load_config` in `src/pyeye/config.py`) is the
authoritative order; later sources override earlier ones:

1. Global config `~/.config/pyeye/config.json`
2. A project config file: `.pyeye.json` or `pyproject.toml` `[tool.pyeye]`
3. Override file `.pyeye.override.json` (local development)
4. Auto-discovery, used only when nothing above configured any packages

See [DOCUMENTATION.md](../../DOCUMENTATION.md#configuration) for the file format.
