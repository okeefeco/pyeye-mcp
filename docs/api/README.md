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
{"scope": "all", "searched": ["main"], "unsearched_scopes": [], "rejected_paths": [],
 "results": [{"name": "dashboard", "…": "<omitted>"}, "<omitted>"]}
```

When `unsearched_scopes` isn't empty, the results may be incomplete: retry with
a wider scope or fix the path. AI agents should always pass `envelope=true`
(#594).

`rejected_paths` lists each config entry (a package, namespace or standalone
directory in `.pyeye.json`) that the path check refused, as
`{scope, path, reason: "rejected_path", detail}`. It is `[]` when there are
none, and its scope is always in `unsearched_scopes`. A `package:` path that
merely doesn't exist is unsearched but not rejected. The key is missing only
when the check couldn't run, because a config file failed to load: then
nothing can be said about refused entries, so don't read its absence as "none"
(#898).

**`project_path`** points the tool at a project other than the server's own.
Once a plugin is active, its tools answer for any project you name, and an
empty result there means the tool looked and found nothing (#665).

**Records** that name a symbol carry its canonical `handle`, which you can pass
to `inspect`, `outline`, `expand` or `trace`. A symbol that can't be placed
carries `unresolved` instead; there is never a guessed handle (#627). The
examples on each plugin page show the records.

**Examples** on the plugin pages run in CI against a small project, and their
output is checked against the real response; `…` marks what an example leaves
out.

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
already configured, and `namespaces` are merged by name (a namespace you name
again replaces its repositories). With `save=True`, the file is written when at
least one of `packages`, `namespaces`, or `standalone_dirs` is given, or when
the session holds unsaved entries, which are then written too. It holds the
project's own config file content plus those entries, and nothing else: not a
package pyeye discovered, not your global config, and not
`.pyeye.override.json` (#1038).

Changes take effect immediately, with no restart: the next `resolve`, `inspect`
or other call on the project sees the added packages, and the project's active
framework plugins get the new paths. If the added packages bring in a framework
the server didn't detect at startup (for example, Flask is used only in a newly
added package), that plugin activates now and its tools can be called by name
straight away; the response's `activated_plugins` names them. Your client's tool
list may not refresh, because no list-changed notification is sent (#659, #770).
Plugin activation applies only to the project the server started in; the new
paths themselves take effect on whichever project you configure.

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
 "environment": {"path": "<project>/.venv", "source": "project"},
 "discovered": [],
 "unsaved": {"packages": [], "namespaces": {}, "standalone": {"dirs": []}},
 "rejected_paths": [], "config_file": "<omitted>"}
```

`environment` is where the project's third-party packages are read from: the
virtualenv's `path` (or `null`), and its `source`: `config` (the `environment`
setting), `project` (a `.venv`, `venv` or `env` in the project), `VIRTUAL_ENV` or
`CONDA_PREFIX` (an activated environment), or `none` (#993).

`discovered` lists the packages pyeye added on its own: each as
`{"path", "reason"}`, with `reason` one of:

- `src_layout`, when no packages are configured;
- `pyright_extra_paths` (from `[tool.pyright]`);
- `build_backend_layout` (from `pyproject.toml`'s build backend);
- for a path dependency `pyproject.toml` declares (#1035): `uv_source`, `uv_workspace`, `poetry_path` or `pep621_file_url`.

They are analysed, so they are in `packages` too, but a save never writes
them. A declared path the path check refuses is in `rejected_paths` instead.
It is `[]` when none were added (#1038).

`unsaved` lists the entries that live only in this session, not in a config
file, in the same shape as `packages`, `namespaces` and `standalone`, so each
compares with its counterpart. It is empty when everything is saved (#953).

`rejected_paths` lists the config entries the path check refused and skipped,
in the same shape as the plugin `envelope`'s, and is `[]` when there are none.
Like the envelope's, it is missing only when a config file failed to load
(#898). It covers entries already in the configuration: the config file and
this session's unsaved additions. A path you pass in the call itself is checked
before anything changes, and if it is refused, the call fails with an error
naming it, and nothing is changed or saved (#856).

A call that names packages adds them, and with `save` left on, writes
`.pyeye.json`. To add a package for this session only:

```json
{"packages": ["../temp-package"], "save": false}
```

Unsaved calls accumulate for the session, like saved ones. Two `save=false`
calls leave both packages configured, beside the project itself, and both
listed under `unsaved`:

```json pyeye-example tool=configure_packages
[{"packages": ["myapp/db"], "save": false},
 {"packages": ["myapp/templates"], "save": false}]
```

```json pyeye-output
{"packages": ["<project>", "<project>/myapp/db", "<project>/myapp/templates"],
 "unsaved": {"packages": ["<project>/myapp/db", "<project>/myapp/templates"],
             "namespaces": {}, "standalone": {"dirs": []}},
 "…": "<omitted>"}
```

This matters when you add several packages one at a time while exploring: each
call keeps the earlier ones, so none silently drops out of the analysis.
Unsaved entries last until the server restarts, or until a call with
`save=true` writes them to `.pyeye.json` along with that call's own entries.

## ⚙️ Configuration Sources

Configuration can also be set without calling the tool, in a config file. The
README's [Configuration Methods](../../README.md#configuration-methods) lists the
files and the order they're loaded in, and
[DOCUMENTATION.md](../../DOCUMENTATION.md#configuration) gives the file format.
