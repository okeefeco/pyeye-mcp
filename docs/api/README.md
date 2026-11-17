# PyEye - API Reference

This directory holds reference documentation for PyEye's **framework plugin
tools** and for `configure_packages`. The core navigation interface is documented
elsewhere, on purpose (see below).

## 📚 Documentation Structure

- **[Pydantic Tools](./pydantic-tools.md)** - Pydantic model, validator, and schema analysis
- **[Flask Tools](./flask-tools.md)** - Flask routes, blueprints, templates, extensions, and error handlers
- **[Django Tools](./django-tools.md)** - Django models, views, URLs, templates, and migrations
- **[configure_packages](#configure_packages)** - Register additional package locations (below)

Plugin tools are registered when the server detects the framework in the
project or in one of its configured packages, at startup or after
`configure_packages` (see [Plugin System](../architecture/plugin-system.md)).
Each tool's parameters are generated from the code in
[MCP tools](../reference/tools.md#plugin-tools). To see the tools a running
server exposes, list them from your MCP client.

## Every plugin tool

The plugin pages describe what each tool is for. What they share is here once.

**`scope`** picks where to search. When you omit it, the default comes from
<!-- fact:begin scope.default.plugin -->`scope_defaults.methods.<tool name>`, else `scope_defaults.global`, else `main`<!-- fact:end -->. A scope is one of
these forms, a scope alias, or a list of them:

<!-- fact:begin scopes.table -->
| Scope | Searches |
|---|---|
| `main` | the main project |
| `packages` | the configured packages only |
| `standalone` | the standalone script directories: those in the config's standalone.dirs, for scripts that aren't in any package |
| `namespace:<name>` | one namespace's package directories; namespace:a.b resolves under namespace a |
| `package:<path>` | that directory, if it exists: an absolute path, or one relative to the project (project\_path) |
| `all` | the main project, every configured package and namespace, and the standalone directories |
<!-- fact:end -->

**`envelope`** wraps the result so you can tell an empty search from a scope
that wasn't searched. This example asks for every scope and shows which were
covered; `results` is exactly what the tool returns without `envelope`:

```json pyeye-example tool=find_flask_routes
{"scope": "all", "envelope": true}
```

```json pyeye-output
{"scope": "all", "searched": ["main"], "unsearched_scopes": [],
 "results": [{"name": "dashboard", "…": "<omitted>"}, "<omitted>"]}
```

When `unsearched_scopes` isn't empty, the results may be incomplete: retry with
a wider scope or fix the path. AI agents should always pass `envelope=true`
(#594).

**`project_path`** points the tool at a project other than the server's own.
Once a plugin is active, its tools answer for any project you name, and an
empty result there means the tool looked and found nothing (#665).

**Records** that name a symbol carry its canonical `handle`, which you can pass
to `inspect`, `outline`, `expand` or `trace`. A symbol that can't be placed
carries `unresolved` instead; there is never a guessed handle (#627). The
examples on each plugin page show the records.

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

<!-- fact:begin tool.configure_packages.params -->
| Parameter | Type | Default |
|---|---|---|
| `packages` | `list[str] \| None` | `null` |
| `namespaces` | `dict[str, list[str]] \| None` | `null` |
| `standalone_dirs` | `list[str] \| None` | `null` |
| `save` | `bool` | `true` |
| `project_path` | `str` | `"."` |
<!-- fact:end -->

- `packages`: package paths to add.
- `namespaces`: a namespace name, mapped to the repositories that contribute to it.
- `standalone_dirs`: directories of standalone scripts that aren't in any package.
- `save`: whether to write the result to the project's `.pyeye.json`.
- `project_path`: the project whose `.pyeye.json` is read and written.

Calls are **additive**: `packages` and `standalone_dirs` are appended to what is
already configured, and `namespaces` are merged by name. With `save=True`, the
file is written only when at least one of `packages`, `namespaces`, or
`standalone_dirs` is given.

Changes take effect immediately, with no restart: the next `resolve`, `inspect`
or other call on the project sees the added packages, and the project's active
framework plugins get the new paths. If the added packages bring in a framework
the server didn't detect at startup (for example, Flask is used only in a newly
added package), that plugin activates now and its tools can be called by name
straight away; the response's `activated_plugins` names them. Your client's tool
list may not refresh, because no list-changed notification is sent (#659, #770).
This applies only to the project the server started in.

> **Removed in 2.0:** `recursive`, `file_pattern` and `exclude_patterns`. They
> were saved to `.pyeye.json` but never took effect
> ([#513](https://github.com/okeefeco/pyeye-mcp/issues/513)). Passing them is
> not an error; they are ignored. If an existing `.pyeye.json` still contains
> them under `standalone`, they are ignored with a warning, and the response
> carries a `warnings` entry naming them.

### Returns

The configuration now in use. This call changes nothing, so it shows the
project's starting point: the project itself is the first package.

```json pyeye-example tool=configure_packages
{"save": false}
```

```json pyeye-output
{"packages": ["<omitted>"], "namespaces": {}, "standalone": {"dirs": []},
 "config_file": "<omitted>"}
```

A call that names packages adds them, and with `save` left on, writes
`.pyeye.json`. To add a package for this session only:

```json
{"packages": ["../temp-package"], "save": false}
```

## ⚙️ Configuration Sources

Configuration can also be set without calling the tool. The loader's own
docstring (`ProjectConfig.load_config` in `src/pyeye/config.py`) is the
authoritative order; later sources override earlier ones:

1. Global config `~/.config/pyeye/config.json`
2. A project config file: `.pyeye.json` or `pyproject.toml` `[tool.pyeye]`
3. Override file `.pyeye.override.json` (local development)
4. Auto-discovery, used only when nothing above configured any packages

See [DOCUMENTATION.md](../../DOCUMENTATION.md#configuration) for the file format.
