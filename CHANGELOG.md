# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.2.0] - 2026-11-19

### Added

- `get_performance_metrics` reports which annotation shapes `inspect` degrades to a raw type string (`Callable`, `Literal`, `Annotated` and so on), counted by shape: a `typeref_degraded` section in its report, and a `pyeye_typeref_degraded_total` counter, labelled by `kind`, in its Prometheus format. Reading them doesn't reset the counts (#331).
- The AST/Script cache's stats split evictions by cause: `cap_evictions` (entries dropped to stay under `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` or `PYEYE_SCRIPT_CACHE_MAX_ENTRIES`, the sign that the caps are too small) and `stale_evictions` (entries dropped because their file changed or was invalidated). `get_performance_metrics` reports both, in its report's `artifact_cache` section and as the Prometheus counters `pyeye_artifact_cache_cap_evictions` and `pyeye_artifact_cache_stale_evictions`. `evictions` and `pyeye_artifact_cache_evictions` keep their meaning, the total of the two (#401).
- Config entries the path check refuses (a `.pyeye.json` package, namespace or standalone directory that resolves to a restricted location) are now reported to the caller. `rejected_paths` lists each one as `{scope, path, reason: "rejected_path", detail}`. It appears in the plugin tools' `envelope` (between `unsearched_scopes` and `results`) and in `configure_packages`' result, and is `[]` when none are refused. It is left out only when the check couldn't run (a config file that failed to load), never reported as `[]`. A scope with a rejected entry is always listed in `unsearched_scopes`, so a result can no longer silently leave out a package you configured (#898).
- `find_pydantic_models`' envelope (`envelope=true`) gains `unplaced_classes`: every class in the searched scope whose base is an expression (`make_base()`, a conditional), as `{name, file, line, base}`. Such a class can't be placed statically, so it isn't reported as a model, and it used to be dropped silently. The key is always present (`[]` when none). The list is capped by the new `max_unplaced` parameter (default 50, `None` for all). When the cap cuts, the envelope carries `truncated`, `truncation_reasons: ["max_unplaced"]` and `total`, which refer to `unplaced_classes` only. `results` is never capped. The bare-list form is unchanged.
- `PYEYE_RESOLVE_CACHE_MAX_ENTRIES` caps a new per-project cache of the `imports` edge's resolutions of targets outside the project. `trace` over `imports` into the standard library no longer re-resolves the same targets on every hop and call. Misses and project targets are never cached, and a file-watcher event clears the cache (#925).
- `find_django_views` reports Django REST framework views, and every record has a new `framework` key, `"django"` or `"rest_framework"`. A DRF class view has a base imported from `rest_framework`, such as `APIView`, a generic view or a `ViewSet` class; a DRF function view is decorated with `rest_framework.decorators.api_view`. A subclass of a DRF view is `rest_framework`. The tool now also reads `viewsets.py` and `api.py` and the modules of `viewsets` and `api` packages, and a views file that imports only `rest_framework` (#947).
- `find_flask_routes` records gain `urls`, the URLs each route is served at. `find_flask_blueprints` records gain `url_prefixes`, each blueprint's served prefixes. Both are composed as Flask does: a `register_blueprint(..., url_prefix=...)` overrides the blueprint's own prefix, a nested blueprint adds its parent's, and a route's rule is joined to its blueprint's prefix. They are sorted lists, because a blueprint registered twice is served twice, and are present only when every registration's prefix is statically known. They are absent when a prefix isn't a string literal, the blueprint isn't registered in the searched scope, a registration has a subdomain or a `**` splat, or there's a cycle. `path` and `url_prefix` are unchanged.
- `configure_packages`' result has a new `unsaved` key, `{packages, namespaces, standalone: {dirs}}`. It lists the configured entries that live only in this session, not in a config file, in the same form as the result's own `packages`, `namespaces` and `standalone`. It is always present, and empty when everything is saved (#953).
- A new config key, `environment`: the path to the project's virtualenv, or `false` for none. It overrides discovery (#993).
- `configure_packages`' result has a new, always-present `environment` key, `{path, source}`. It says where third-party packages are read from, and `source` is `config`, `project`, `VIRTUAL_ENV`, `CONDA_PREFIX` or `none`. When no environment is found, pyeye logs a warning once per project, and `resolve` and `inspect` add a note to a third-party name they can't find, so a missing venv can be told apart from a name that doesn't exist (#993).

### Changed

- The documentation is published at [okeefeco.github.io/pyeye-mcp](https://okeefeco.github.io/pyeye-mcp/), built with MkDocs from the Markdown under `docs/`, with its navigation generated from the doc registry. It replaces the Sphinx site removed in #823 (#861).

### Deprecated

- `trace_model_inheritance`'s `mro` is deprecated and will be removed in v3.0 (#749). It is filled now (#870), so it's correct until then. To walk a class's bases, use `trace(follow=["superclasses"])`.
- `pyeye.unified_metrics.get_unified_collector()` is deprecated: it emits a `DeprecationWarning` and returns a collector that accepts the old calls and records nothing. `scripts/unified_metrics.py` prints a deprecation notice and exits. The environment variables `PYEYE_ISSUE` and `PYEYE_PARENT_SESSION` are deprecated: accepted and ignored. All of these will be removed in a future major release. (#943)

### Removed

- The Sphinx docs tree (`docs/source/`), its GitHub Pages workflow, its Sphinx dependencies and Dependabot's Sphinx group are removed. The docs site is now built with MkDocs from the Markdown under `docs/` (see Changed). The architecture pages that were still correct moved to `docs/architecture/` (`resolution.md`, `plugin-system.md`, `caching.md`), checked against the code, and the `python-explore` skill links the new resolution page (#823).
- The MCP server no longer writes usage metrics to `~/.pyeye/metrics/`. The unified metrics store recorded every tool call, which cost each call a locked rewrite of a file, and nothing that shipped read it. The server now has fewer places that write files, and the files it wrote there before (`active_sessions.json`, `completed_sessions.jsonl`, `aggregated_stats.json` and their `.lock` files) can be deleted. Connection diagnostics, the error tracker and the in-process performance metrics (`get_performance_metrics`) keep working. (#943)

### Fixed

- `get_performance_metrics(export_format="prometheus")` now emits valid Prometheus text format, checked in tests by `prometheus_client`'s own parser (a new dev-only dependency, never imported at runtime):
  - operation durations are declared as a `summary`, the type their quantile series have, and gain the `pyeye_operation_duration_ms_sum` and `_count` series a summary requires. They were declared a `histogram`.
  - `pyeye_operation_count` is its own `counter` family. It was interleaved with the durations, with no `HELP` or `TYPE`.
  - the memory gauge has no space before its labels.
  - label values are escaped.
  - the output ends with a newline.
- A package added with `configure_packages` under a directory whose name isn't a Python identifier (`.hidden/`, `my-dir/`) now resolves: its classes, functions, methods and attributes are found by `resolve`, `inspect`, `outline` and `expand`. Before, they were scanned but never resolved, and under an ordinary directory (`vendor/`) only top-level names resolved, by luck of a fallback (#814).
- MCP tool descriptions now take their edge, ceiling and scope lists from the code when the server loads, so they can't drift from it, and state the ceiling of each edge they expose: what the edge's answer is complete over. A docs check fails any description that exposes an edge without its ceiling (#827). Corrected along the way:
  - `trace` now lists `submodules` and `re_exports` as edges it follows, and each edge's ceiling.
  - `expand` now documents its `submodules` edge, lists every deferred reference edge, and states which kinds every edge applies to. Each edge entry states its own ceiling.
  - `outline` gives the meaning of its two ceilings.
  - The plugin tools document every scope form (`packages`, `standalone` and `package:<path>` were missing) and their `envelope` parameter.
  - `resolve` documents `max_candidates` in its Args.
- `SECURITY.md` now describes pyeye's real behaviour:
  - the server starts no subprocess of its own; the ripgrep subprocess was removed in #628, and Jedi's one helper subprocess loads compiled modules only from the server's environment;
  - `configure_packages` writes `.pyeye.json` in its `project_path`, with `save` defaulting to true;
  - which path inputs the sanity check covers;
  - when each security check runs.

  The response-time numbers, which no policy backed, are replaced by what the maintainers aim for.
- `SECURITY.md`'s security model now takes its values from pyeye's code, so they can't drift. That covers the server's process-starting calls, the places it writes, the files it keeps, what the path check rejects and which forms of a path it checks, its networking imports, and Jedi's `load_unsafe_extensions` setting (#830).
- Four history pages no longer state figures nothing backs, and now publish on the docs site (#830):
  - `docs/migration-guide.md` says it covers 0.1.x to 0.2.0. It drops its unsourced benchmark and memory figures, the removed `invalidate_scope` and the old default-scope block, which now links the live defaults. It fixes a claim that was wrong even then, a wrong signature and an invalid `pip install` command.
  - `docs/api-redesign.md` notes that it records the redesign's design, with current shapes in `docs/reference/` and the `python-explore` skill. Its examples no longer use the deleted `GranularCache` or relative paths.
  - `docs/METRICS_BASELINE.md` and `benchmarks/BASELINE_RESULTS.md` keep what happened and drop their unbacked figures, targets and projections.
- `README.md`, the docs site's home page, no longer hand-copies code facts. The core, plugin and edge lists and the artifact-cache default are fact blocks, and the env-var table links the generated reference.
- `README.md` drops claims nothing backs:
  - the "performance baselines" table, for operations (`symbol_search`, `goto_definition`) that no longer exist;
  - the stale architecture tree;
  - the `find_patterns` plugin example (plugins are built in);
  - the unrecorded cache-sizing measurements;
  - the claim that `.pyeye.override.json` is git-ignored automatically (add it to your `.gitignore`).
- `README.md`'s GitHub Copilot setup, which used a `settings.json` key, an `@mcp list` command and plan requirements that current VS Code and GitHub docs don't support, now links those docs.
- The plugin tool pages (`docs/api/`) now show each tool's real output through examples CI runs, and link the generated parameter reference. They replace hand-written response shapes and examples that used keys no tool returns (#830). The scope forms and the `envelope` wrapper are documented once, in `docs/api/README.md`.
- `docs/api/README.md` no longer says a framework in a newly added package needs a server restart: `configure_packages` activates it and names it in `activated_plugins` (#659).
- The architecture pages (`docs/architecture/`) take the resolver's strategy order, its bare-name policy, the plugins' tool lists and the cache defaults from the code. They correct the strategy chain (it was missing the private-stdlib step), the "every tool reports the definition-site handle" claim, the cache list (the class and import graphs were missing), and which edges report `unparseable_files` (#830).
- `examples/configurations/enterprise.json` and `monorepo.json` no longer use scopes that search nothing: `namespace:company` and `namespace:company.sdk` matched no configured namespace, and `./packages/app-*` / `./tools/*` aren't scope forms. Their default, aliases and `packages` now resolve, the ignored `performance` block is gone, and a test checks every example's scopes.
- `DOCUMENTATION.md` no longer describes behaviour pyeye doesn't have: a `../` path rejection, input sanitisation, a file-size limit, an on-disk `.pyeye_cache`, a `--debug` flag, environment variables as a package-config source, user-loaded plugins, and unbacked memory figures. Its security section links `SECURITY.md`. Its tool lists and the required Python version come from the code, and the rest links the generated reference.
- `CONTRIBUTING.md` says to install pre-commit before `pre-commit install`, drops the stale module tree and the GitHub Discussions link (Discussions aren't enabled), and links the architecture pages.
- The guides under `docs/`, `docs/testing/` and `docs/development/` now match the code, and take their facts from it (#830):
  - The coverage threshold, cache and timeout defaults, scope forms and duplicate-code limits come from the code instead of hand-written copies.
  - Commands no longer hard-code the coverage threshold.
  - `docs/testing/PERFORMANCE.md` describes the suite that exists, not an invented one. `docs/testing/FIXTURES.md` points at the real fixtures instead of fixtures that don't exist.
  - The log samples in `docs/debugging-connection-drops.md` and the advice in `docs/TROUBLESHOOTING.md` match current behaviour.
  - The migration guide's rollback step works.
  - Unbacked numbers, targets and projections are removed.
- `docs/architecture/caching.md` no longer says the scoped cache holds lookup results; it holds each scope's file list.
- The `inspect` tool description no longer says edge counts "come in later phases" or shows `edge_counts={}`. It says which edges are counted and that an unmeasured one is absent, never `0`. It also documents the deprecated re-export list and when `superclasses` is omitted.
- The `resolve` description's success shape includes `location`. The `expand` shape adds `transitive_hint`, the `max_stubs` truncation fields and `bindings` on re-export stubs.
- The `get_connection_diagnostics` description lists the fields the tool actually returns.
- The plugin tool descriptions say each record carries `scope`, `location`, and `handle` or `unresolved`. `get_model_schema` and `trace_model_inheritance` say `model_name` takes a class name or a handle, and describe the not-found and ambiguous answers.
- The `outline` description and the `python-explore` skill name the `unparseable` truncation reason.
- The `architecture-review` skill describes the decision-log flow as writing a file, and points auditors at `unresolved_imports` rather than warning that `imports` silently drops imports. It no longer says a file-path handle "returns junk": it gets `found: false`.
- `python-explore` no longer says conditional imports are invisible to `imports` (guarded imports are listed). It binds the deferred edges and the `imports` ceiling to their facts, scopes "stable across edits" to edits that don't rename or move a symbol, and links the reference for the candidate and stub caps.
- `architecture-review` binds its seed-axis table to the axes fact, defers to `decision-log` for that skill's rules instead of copying them, and tells the auditor to emit one `no_signal` finding per axis when it finds nothing, instead of `[]`, which contradicted the rule before it.
- `duplication-review` says normalisation ignores every name (so code of the same shape that calls different functions can match), gives the exception to how a function-to-method copy is grouped, and says a re-surfaced family shows its new sites. It links the record for its measured precision.
- The `python-explore` skill's ceiling definitions are the generated ceilings table, not a hand copy. Its plugin-envelope shape and its `resolve` examples are executed and checked against a fixture project, and its plugin tool list links the tool reference.
- The `architecture-review` skill shows the ranker's default bucket order from a new `review.buckets` fact, rather than a hard-coded order, and says to show the re-tiered map when a project changed it.
- The `duplication-review` skill binds each flag it documents to its fact.
- The docs take repository and pyeye config values from the files that define them (#830):
  - the pre-commit hooks named in `SECURITY.md`;
  - the `uv` flags CI and the hooks use, in `CONTRIBUTING.md`;
  - the config file names and keys, in the README's Configuration Methods;
  - every config key pyeye ignores with a warning, in `DOCUMENTATION.md`, which had listed 5 of the 9.
- Pages that repeated another page's explanation now link to it (#830):
  - `CONTRIBUTING.md`'s changelog-fragment and decision steps link to `changes/README.md` and the decisions log;
  - `docs/api/README.md`'s config-source list links to the README;
  - the plugin tool pages link to the shared plugin tools overview.
- `docs/architecture/resolution.md` no longer restates #419's fallback rate; it points to #419's measurement.
- Contributor tooling, none of it part of the installed package, was corrected (#828, #830, #879, #894, #915, #965, #969, #970, #981):
  - The dogfooding scripts and aliases run through `uv run --frozen`, and their always-empty `sync` command and in-process metrics read are removed.
  - The `grep`/`rg` wrappers that `scripts/setup_dogfooding.sh` installs no longer break those commands.
  - The MCP monitoring hooks count the Claude Code plugin's tool names and Claude Code's own Grep tool.
  - `scripts/claude_hooks/setup_mcp_monitoring.sh` merges pyeye's hooks into `~/.claude/settings.json` instead of replacing your Claude Code hooks, and no longer fails on macOS. If an earlier run removed hooks of yours, they're in the `~/.claude/settings.json.backup-*` file that run made.
  - The `pip-audit` pre-commit check retries network errors.
  - Claude's project instructions and the internal skills no longer state stale or unbacked facts.

  If you set up the dogfooding or monitoring scripts before, re-run `bash scripts/setup_dogfooding.sh` and `bash scripts/claude_hooks/setup_mcp_monitoring.sh`.
- A relative path passed to a tool now resolves against `project_path`, not the server's working directory (#842, #843). This covers `resolve_at`'s `file`, `resolve`'s `path/to/file.py:42` and `path/to/file.py` forms, and a plugin tool's `package:<path>` scope. Before, a multi-project server looked in the wrong place, and `resolve_at` contradicted its own "relative to project_path" message. A relative path containing `..` (`file`, `project_path`, `configure_packages`' `packages`) is no longer made absolute against the working directory by the input validator first; the validator still checks where it really leads, and now also refuses a climb onto a system directory itself (`../../etc`), not only into one. On Windows, a drive-relative path such as `C:foo` on a drive other than the project's is now rejected with a clear error. Absolute paths are unchanged.
- A plugin tool's `envelope` now lists a `package:<path>` scope whose directory doesn't exist in `unsearched_scopes`, spelled as you gave it. Before, such a scope searched nothing and returned `[]`, with only a server log warning (#842).
- pyeye installed from a wheel, or started from any directory other than its source checkout's root, failed to start: `import pyeye.mcp.server` raised `FileNotFoundError` for `tests/conformance/response_linter.py`. Tool descriptions now take their facts from the installed code only, and CI checks that a built wheel's server imports with no repo around it (#851).
- A re-export made by a relative import in a package's `__init__.py` (`from .thing import X`) now resolves to its definition (`pkg.thing.X`), like any other re-export. Before, `resolve`/`inspect("pkg.X")` answered `pkg.X` at the import line, though `inspect("pkg.thing.X")` listed `pkg.X` among its `re_exports` (#857). A name that the package also defines locally (`from .src import A` and then `class A`) still resolves to the local definition, as at runtime, and an `if`/`else` re-export of two different definitions isn't collapsed to either branch.
- A package added with `configure_packages(save=False)`, the session-only mode, can now be analysed by Jedi too. Before, only a package saved in `.pyeye.json` reached it, so for a session-only package: imports of it were unresolved, `resolve_at` found nothing at an imported name, callees into it and types from it had no handle, and a relative import inside one under a dot-directory (`.hidden/…`) couldn't be followed (#858).
- The Pydantic tools read `model_config` written as `ConfigDict(...)` or `SettingsConfigDict(...)`, bare or module-qualified, and with a type annotation (`model_config: ConfigDict = ...`), not only as a dict literal. `find_model_config`'s `settings` and the models' `config` were empty for these forms.
- `get_model_schema`'s `computed_fields` lists the model's own `@computed_field` members (name, line and return type). It was always empty. A plain `@property` isn't listed, because pydantic doesn't treat it as a computed field.
- The Pydantic tools leave out a model's `config` (on models and schemas) and `find_model_config`'s `settings` when its `model_config` can't be fully read from source: a function call, a name, a subscript, a `**` splat, a positional argument or a non-literal key. They used to report `{}` or only some of the keys, which read as "these are all the settings". A model with no configuration still reports `{}`.
- `trace_model_inheritance` fills `mro` (the static C3 order) and `fields_inherited`, which were always empty. Each inherited field carries `defined_in`, the handle of the class that declares it. Both are computed from the model's statically resolved bases, project or installed, so the walk goes through pydantic's own `BaseModel` and `RootModel`. Each is omitted when it can't be computed: when a base doesn't resolve to a class, when there's no consistent order, or (for `fields_inherited`) when an ancestor's class body can't be read, or its fields can't be known under the model's own pydantic API (#913).
- The Pydantic tools' own field lists (`fields`, `fields_own`) no longer include `model_config`, `ClassVar` attributes or private `_x` names, which pydantic doesn't treat as fields.
- A glob in a `namespaces` config entry (e.g. `"company": ["~/repos/company-*"]`) now expands to its matching directories. Before, the namespace mapped to the literal pattern, so `namespace:company` searched nothing, while the matches were analysed only as plain packages. Namespaces and packages now share one expansion. Matches are sorted, for packages too, so precedence no longer depends on filesystem order: the first repository to define a module wins. Only `*` makes a glob, so a literal `?` or `[` in a path keeps its meaning. A glob with any refused match is skipped whole, with a warning. A glob that matches nothing leaves the namespace configured with no repositories, and its scope is reported in `unsearched_scopes` rather than counted as searched (#872).
- The Flask tools no longer miss real code where they used to return a confident `[]` or a partial list:
  - `find_flask_routes`, `find_error_handlers` and `find_cli_commands` now report `async def` handlers.
  - `find_flask_blueprints` now finds `flask.Blueprint(...)` (or any `<module>.Blueprint(...)`), and annotated assignments such as `bp: Blueprint = Blueprint(...)`.
  - `find_flask_config` now looks for `config.py` and `settings.py` in the scope you ask for, instead of always the main project: at each scope root or one directory below it. Results under `main` are unchanged. (#873)
- The `expand` and `trace` descriptions, the operation docstrings, the `python-explore` skill and the resolution architecture page now agree on which edges report `unparseable_files`. Several said only `subclasses` and `imported_by`, but `re_exports` reports it too. The set is stated once, as `UNPARSEABLE_FILE_EDGES` in the edge registry, and the docs and descriptions show it through the new `edges.unparseable` fact. A test checks the constant against what `expand` returns for every edge.
- A file path passed where a handle belongs (`outline("src/x.py")`) no longer gets the hint "Call resolve('py')". It now says the input is a file path and suggests `resolve` with that path, with forward slashes and a `.pyi` stub pointed at its `.py` source. A dotted handle keeps its usual hint. `resolve` given a `.pyi` path now points at the source too, instead of `resolve('pyi')` (#882).
- The duplication review's docstrings say what it does. A function's copy of a method joins that class's family when the method also has a copy in another class. `dismiss` exits 1 after the scan when `--family` names no family, and exits 2 for bad arguments before it (#882).
- `resolve` accepts a `.pyi` stub path. A stub beside its `.py` source resolves exactly as the source does, with the same handle and location; `pkg/mod.pyi:3` and `resolve_at` on a stub already did. A bare `mod.pyi` is now read as a file path, like `mod.py`. A stub with no `.py` beside it stays `unresolved`, and its detail now says why instead of suggesting a `.py` path that doesn't exist (#885). Support for stub-only modules is #933.
- `find_flask_routes` now reports routes declared with Flask 2.0's shortcut decorators: `@app.get(...)`, `.post`, `.put`, `.delete` and `.patch`, on an app or a blueprint. Each is a `route` record whose `methods` is the one method the shortcut names. A file that used only the shortcuts used to return a confident `[]`.
  - A shortcut counts only when its receiver is a Flask app or blueprint: a name the same file binds to `Flask(...)` or `Blueprint(...)`, including an app factory's local `app`, or one imported from another module (`from .blueprints import bp`, an alias, a re-export through a package's `__init__`, or a module attribute such as `blueprints.bp`). An import is placed through pyeye's resolver, and the definition it lands on must itself be a `Flask(...)` or `Blueprint(...)` binding. So FastAPI's `@router.get(...)` and decorators such as `@cache.get("k")` are not reported, whether local or imported.
  - A receiver passed in as a function argument can't be placed, so its shortcuts aren't reported. (#905, #910)
- A Pydantic model's fields now follow its own API, taken from the root it descends from: v1 rules for a `pydantic.v1` model or an installed pydantic 1.x, v2 rules otherwise. Under v1, a public un-annotated attribute (`x = 1`) is a field, and its record has no `type` because it has no annotation. It isn't a field when its value is a lambda, a `property`/`classmethod`/`staticmethod`/`PrivateAttr` call, a class or a function. `fields_own` was a partial list for v1 models. `fields` (and the schema's `fields`, `required` and `optional`) is omitted when the rules can't be known.
- A class whose base is subscripted, such as `class IntBox(Box[int])` or `class Ids(RootModel[list[int]])`, is now found as that class's subclass, by the `subclasses` edge, `trace` and `find_pydantic_models` alike. The class graph used to drop every base that wasn't a plain name or attribute. A class named only inside a base's type arguments (`Generic[Box[int]]`) is still not a subclass of it.
- The `superclasses` edge resolves a module-qualified subscripted base (`typing.Generic[T]`) to the class. It used to report the module (`typing`).
- The `superclasses` edge and `inspect`'s `superclasses` no longer report a function or variable as a class's base. A base that's a call (`make_base()`, `BaseManager.from_queryset(QuerySet)`), a conditional, or a name that resolves to something other than a class is listed in `unresolved_superclasses` with its source text. The edge used to report, for example, `make_base` itself, or django's `BaseManager` for `Manager`.
- `find_pydantic_models` finds models built on `pydantic.v1`, the v1 API that pydantic 2 ships (`from pydantic.v1 import BaseModel`, `BaseSettings`, `GenericModel`), and v1's `pydantic.generics.GenericModel`. It returned none of them, which read as "no models".
- A project under a directory named `dev`, `etc`, `sys`, `proc` or `root`, in any case, now works. Before, a path check refused any path containing one of those names anywhere, so a project under `~/dev` or `~/Dev`, `/srv/etc/lib`, or a project's own `etc/` package was refused ("suspicious component"). The deny-list now judges only where a path leads: its patterns are anchored at the root (`^/etc/`, `^/private/etc/`, `^/root/`, `^/proc/`, `^/sys/`, `^/dev/`) and matched ignoring case. Every route to those directories is still refused, including a `..` climb, a relative path from `project_path="/"`, a symlink, and `/ETC` on a case-insensitive volume (#939).
- The Django plugin no longer switches on for any project with a `manage.py`: a Flask-Script project has one too. Detection now relies on Django being imported or required. Django's own generated `manage.py` imports Django, so real projects are still found. A requirements file or Pipfile now has to name `django` as a requirement; a mention such as `django-environ` or a comment no longer counts (#940).
- `find_django_views` finds the views it used to miss:
  - class views with an attribute base such as `generic.ListView`, or an aliased import;
  - `async def` function views;
  - the modules of a `views` package;
  - files that import Django with `import django…` rather than `from django`.

  A class with two view bases is now one record, not two. A base counts only when the module imports it from Django (or from Django REST framework, #947), so a project class whose name merely contains `View` is no longer reported (#941).
- `find_django_views` reports project classes that subclass a Django class view, at any depth and in any module, such as `class Page(BaseListView)` where `BaseListView(ListView)`. It follows the same shared class graph as `find_pydantic_models`, so the first call on a project with class views builds that graph; a project without class views never does (#942).
- `find_flask_templates` finds every Flask `render_template` call by the module's own imports: bare, aliased (`render_template as rt`), module-qualified (`flask.render_template`) and with the keyword `template_name_or_list`. It found only the bare positional form, so templates looked unrendered when they weren't. A call no longer counts unless the module imports `render_template` from Flask (the same rule as `find_django_views`, #941), so a local function that merely shares the name isn't Flask's. Each template file is listed once. Files under `app/templates` were listed twice.
- `find_flask_views` finds MethodView subclasses by the module's Flask imports (an alias or `views.MethodView` too) and then through the class graph, so a subclass of a project view is found. A local class that merely shares the name no longer counts.
- `find_flask_config` reports `app.config` and `current_app.config` reached through an attribute (`self.app.config`, `flask.current_app.config`), not only the bare names.
- The Flask tools page says a route's `path` is its own, without a blueprint's `url_prefix`, and states where config files are looked for. The resolution page shows `resolve_handle`'s `analyzer` parameter.
- `find_flask_routes` lists a blueprint route with the empty rule `""`, which Flask serves at the blueprint's prefix itself. It was skipped as if it had no path.
- `configure_packages` calls with `save=false` now accumulate for the session, as the docs say. Before, each call rebuilt the configuration from disk and kept only its own entries, so a second unsaved call silently dropped the first call's packages, from the analysis too. Unsaved entries last until the server restarts, or until a `save=true` call writes them to `.pyeye.json` with its own entries; a `save=true` call with no entries of its own now writes pending unsaved entries too (#953).
- On Windows, `configure_packages`' `packages` and `standalone_dirs` reached the tool, the response and the saved `.pyeye.json` with native backslash separators. They now carry POSIX spellings, like every other path pyeye reports (#953).
- The order of the import roots that pyeye gives Jedi (configured packages, then additional paths, then namespace repo roots) is now fixed. Before, it could change between runs, and with it which root won when two define the same module (#962).
- `find_cli_commands` finds a command registered with a bare `@app.cli.command` (or `@bp.cli.command`), without parentheses, which it used to miss silently (#980).
- The plugin docs now say exactly what each tool covers: when an error handler's `error_code` is `null`, which files `find_django_models` and `find_django_templates` read, and that `TEMPLATES` `DIRS` isn't. The troubleshooting guide's environment-variable examples now set the variables on the MCP client's server entry, as the guide itself says to, instead of with a shell `export` the server never sees.
- Documentation fixes (#983):
  - The README's project-specific install now points `.mcp.json`'s `command` at the project venv's Python. A bare `python` runs whichever Python is first on the client's `PATH`.
  - The README's configuration loading order includes this session's unsaved `configure_packages(save=false)` additions (applied last). It also says how auto-discovery treats a `src/` layout and virtualenv site-packages, and when `pyproject.toml` build-backend detection runs.
  - `PYEYE_ENABLE_PERFORMANCE_METRICS` is described as registering both admin tools.
  - `SECURITY.md` lists a config file's `packages` entries among the path-checked inputs.
  - `DOCUMENTATION.md` no longer says every tool takes `project_path`.
  - `docs/architecture/caching.md` links the environment-variable reference.
- The `configure_packages` reference now says that only plugin activation is limited to the startup project; the new paths take effect on any project you configure (#984).
- The pydantic tools page says that a v1 model's nested `class Config:` is read, with an executed example (#984).
- The namespace packages guide no longer says namespace code is searched by default: without `scope_defaults`, a plugin tool searches only the main project. It also says that imports under `if TYPE_CHECKING:` and in `try`/`except` shims are followed by the `imports` edge, while imports inside a function are not. An executed example shows the rule (#984).
- pyeye now finds a project's own Python environment for any project layout, including `src/`, and reads its third-party packages from it, whichever way pyeye runs (the Claude Code plugin, `uvx`, `uv tool` or an install into the project). Before, a `src/`-layout project under an isolated install resolved none of its third-party packages. A project's imports could also resolve against pyeye's own dependencies, such as pydantic, even when the project didn't install them. pyeye's own packages are no longer visible to the analysed project. In a flat project the virtualenv is no longer treated as a configured package, so `configure_packages` no longer lists its site-packages, and plugin scans with `scope="all"` no longer walk it (#993).
- pyeye uses the first of: the `environment` setting, a `.venv`, `venv` or `env` in the project (or, for a project that is itself a package, in its parent directory unless that directory is shared), and the activated `VIRTUAL_ENV` or `CONDA_PREFIX` (unless that is pyeye's own environment). A project's own venv wins over an activated one, because one pyeye server answers for many projects (#993).
- The installation docs are rewritten around one place, the README's Installation section (#994):
  - **Routes:** the Claude Code plugin (with its `/plugin marketplace add okeefeco/pyeye-mcp` and `/plugin install pyeye@pyeye-marketplace` steps, and what it brings: the server, four skills and a dependency hook), `claude mcp add … -- uvx pyeye-mcp`, `uvx pyeye-mcp` for other MCP clients, `uv tool install` or pipx, and an install into the project's environment.
  - **Warnings and links:** it warns not to register pyeye both as the plugin and with `claude mcp add`, and links Claude Code's, uv's and the clients' own documentation instead of restating them.
  - **DOCUMENTATION.md** points to the README instead of its own install steps. Their Claude Code and Claude Desktop setup used `uv --directory`, which made pyeye analyse its own checkout instead of your project.
  - **TROUBLESHOOTING** and **debugging-connection-drops**: their `claude mcp add` examples use `uvx pyeye-mcp` (a bare `python -m pyeye.mcp` broke installs where that Python lacks pyeye), and the debugging page's Claude Desktop config no longer uses `uv --directory`, which made pyeye analyse its own checkout.
  - **CONTRIBUTING** shows how to run your checkout as the server alongside the plugin.

### Security

- Every caller-supplied path now goes through the input check in the form the tool finally uses: a relative path anchored on `project_path`, checked as spelled and with symlinks followed. Before, a relative path without `..`, `resolve`'s file forms (`f.py`, `f.py:42`), a plugin `scope="package:<path>"`, `configure_packages`' `namespaces` paths and `standalone_dirs`, and config-file namespace and standalone paths skipped the check. A refused tool argument is now an error, never a "not found". A refused config entry is skipped with a warning (#856) and listed in `rejected_paths` (#898).
- A directory that pyeye scans (a plugin scope, or a configured package, namespace or standalone dir) may no longer be `/`, or any other ancestor of a restricted system directory. This includes the scan that `project_path="/"` implies, so scope `main` from `/` is refused with an error. `project_path` itself and single-file inputs are unchanged. Every directory walk also skips restricted directories it reaches through a symlink (#856).
- Config entries (`.pyeye.json` packages, namespaces and standalone dirs) that resolve to a restricted path, or to an ancestor of one, are now skipped with a warning, and reported to the caller in `rejected_paths` (#898).
- The path check now also refuses `/boot`, `/run/secrets`, `/var/run/secrets` and macOS root's home (`/var/root`). `/run`, `/var`, `/var/run` and `/private/var` are now refused as directories to scan.
- It also refuses credential stores directly below any user home (`/home/<user>`, `/Users/<user>`, `/root`, and the server's own home): `.ssh`, `.aws`, `.gnupg`, `.config/gcloud`, `.azure`, `.kube`, `.docker`, `.config/gh`, `.netrc`, `.pypirc`, `.pgpass`, `.git-credentials` and `.npmrc`. Directory scans skip these stores, while scanning `~`, `/home` or `/Users` still works. A project placed inside one of them is refused. A config entry that names one is skipped with a warning and listed in `rejected_paths` (#909).
- A symlinked home (for example an NFS `/home/u` that points at `/data/u`) is protected under both names. Directory scans also skip a file or directory that is a symlink into a restricted location, such as a project file that points at `~/.netrc` (#909).
- A path that goes through a symlink and then `..` is now checked where the operating system really puts it. With `l_tmp` -> `/tmp`, the path `l_tmp/../etc` is `/etc` on disk, because the operating system follows the symlink first; such a path is now refused. v2.1.0 accepted `project_path="proj/l_tmp/../etc"` (a `file` too), but used it collapsed to `<project>/etc`, so it never read `/etc` (#939).
- pyeye's Jedi helper process now always runs the server's own Python interpreter. Before, when `VIRTUAL_ENV` or `CONDA_PREFIX` was set in the server's environment, Jedi started the interpreter of that environment instead. That could be the interpreter of a virtualenv shipped inside an analysed repository, if the server was started with it activated. The project's environment is now read from disk (its `site-packages` and the plain-path lines of its `.pth` files), and its interpreter is never run. A `.pth` line that would run code is skipped. Because the environment can come from the repository, pyeye also checks it, once symlinks are resolved:
  - An environment that is, is inside, or contains a restricted directory or a credential store (such as `/etc` or `~/.ssh`) is skipped with a warning, whether it was configured, found in the project, or named by `VIRTUAL_ENV` or `CONDA_PREFIX`. So is each `site-packages` directory and `.pth` path it adds.
  - Reading `.pth` files is bounded in bytes and paths per file, and per environment in import roots and in paths looked up. A huge `.pth` set can't stall building the analyser.
  - For a project that is itself a package, its parent directory is searched for a venv only when that directory is neither group- nor world-writable (such as `/tmp`) nor owned by another user (#993).

## [2.1.0] - 2026-11-17

### Added

- Framework plugin tools (Pydantic, Django, Flask) take an opt-in `envelope` argument that reports what was searched (#594). By default a plugin tool returns a bare list: an empty answer is zero content items, and nothing says which scope was searched, so "these are all the models" looked the same as "these are the main repo's models". With `envelope=true` every plugin tool returns `{scope, searched, unsearched_scopes, results}`:
  - `scope` is the scope as requested or defaulted.
  - `searched` lists the configured scopes (`main`, `packages`, each `namespace:<name>`) whose paths were all searched.
  - `unsearched_scopes` lists the ones the search didn't cover, so an agent can retry with `scope="all"`.
  - `results` is the tool's usual answer, present even when empty.

  The default output is unchanged. The python-explore skill now tells agents to always pass `envelope=true`, and the plugin API docs document `scope` and `envelope`. Making the envelope the default is planned for the next major release (#644).
- `SECURITY.md` (#69): report vulnerabilities privately through GitHub's private vulnerability reporting, now enabled for the repository, rather than public issues. It covers supported versions (2.x), response goals, scope, and pyeye's security model: static analysis only, and it reads whatever paths the MCP client points it at, so path validation is a sanity check rather than a sandbox. Linked from the README.
- `expand(handle, "re_exports")` lists the public modules that re-export a symbol. Each stub is the re-exporting module, with a `bindings` list of the public paths it provides (for example `["pkg.api.X", "pkg.api.Y"]`). The edge applies to every kind except `module`, and isn't counted in `edge_counts`. Like `subclasses` and `imported_by`, it reports `unparseable_files`, and still lists every re-export it found in the files that parsed. Its static-surface ceiling (#417) is `package_reexports`: import bindings in the public modules of the symbol's own package. A repeat call reads a per-project cache that the file watcher and `configure_packages` clear (#393).
- Structural results now say what scope they're complete over (#417). `expand` carries `ceiling` (e.g. `"static_definitions"`: a class body or a module's top level, with no `self.x` instance attributes and nothing injected at runtime). `outline`'s root carries `ceiling`. `trace` carries `ceilings: {edge: id}`. The tool descriptions and the `python-explore` skill define each id. A name missing from the result is unknown beyond that scope, not absent.
- `outline` results carry a top-level `truncation_reasons` list: every reason any node in the tree was cut for (absent when nothing was cut), named like `trace`'s. A real `max_nodes` cut no longer hides among many `survey_leaf` nodes (#435).
- A node `outline` cuts at `max_depth` now says how many children it withheld: `member_count`, or `submodule_count` in a package survey. A `max_nodes` cut already did this (#435).
- **Duplication review (#495).** The new `duplication-review` skill and `python -m pyeye.duplication review <scope…>` find copied code in a scope you choose. Results are ranked clone families of pointers only (file, line range, qualname, token count), each labelled as a judgment with its threshold (35 normalised AST tokens) and filters (a function-body filter and a signature/stub guard). Dismissals (`python -m pyeye.duplication dismiss`) persist in a committed state file such as `.pyeye/duplication-review.json`. A dismissed family stays suppressed through edits and drift, and re-surfaces only when a new, renamed or moved member joins it.
- The duplicate-code detector, shared by the review and this repository's ratchet, now pairs a token window seen more than 50 times with its next occurrence only. The run stays linear on repeated data tables, which previously ran out of memory, and every copy is still reported. A file that can't be parsed is skipped and named in the output (`unparseable_files`), never printed.
- The `architecture-review` cross-derivation guard has a third verdict, `cannot_confirm`, alongside corroborated and divergent. When a finding's import fact can't be decided (an import listed in `unresolved_imports`, or source that doesn't parse), the finding is left unpromoted (`grade: "ambiguous"`, `corroboration: "cannot_confirm"`) for human review. It is no longer silently confirmed, and no longer flagged as a possible extractor bug. The new `guard.corroborate_imports` helper derives the verdict for import facts; `True`/`False` verdicts still work (#499).
- Python 3.14 is supported: it is in the CI test matrix (Linux, Windows and macOS on pull requests; every OS on `main`) and in the package classifiers. Analyzed code that uses 3.14-only syntax (template strings, unparenthesised `except`) is outlined and inspected normally when pyeye runs on 3.14 (#543).
- `configure_packages` takes an optional `project_path` (default `"."`), like every other tool, to choose which project to configure (#618). It used to always configure the server's working directory.
- `trace` responses now include `unresolved_nodes` (#621), always present: the interior nodes `trace` reached but could not resolve, the same handles `expand` answers `found: false` for. They stay in `nodes` but are not walked, so a listed node is a dead end of the walk, not a node with no neighbours.
- `expand(cls, "superclasses")` now reports `unresolved_superclasses`: the source text of each declared base that couldn't be resolved, such as an attribute of a dynamically imported module (#624). It used to drop such bases without a trace. It is `[]` when every base resolved, and absent for other edges. `inspect`'s `superclasses` field is unchanged: it still shows those bases as their source text.
- `resolve` and `resolve_at` not-found responses now carry the lookup they missed and a next step (#626). `resolve` adds `identifier` (the input, verbatim) and `resolve_at` adds `file`, `line` and `column` (as passed), and both add `detail`. For example: `{found: false, identifier: "pkg.Nope", reason: "unresolved", detail: "…"}`. `reason` keeps its existing values (`unresolved`, `file_not_found`, `no_symbol_at_position`). All five primitives now share one not-found shape: `{found: false, <lookup echo>, reason, detail}`. `handle` appears only when the input is a handle (`inspect`, `outline`, `expand`), so an identifier or path is never handed back as if it were one. The tool descriptions also now say what really raises: invalid arguments or a missing `project_path`, never a lookup miss.
- `expand` (and `trace`'s `unsupported_edges`) report a new unsupported `reason`, `not_applicable`, when an edge exists but doesn't apply to the handle's kind (#626), for example `imports` on a class, `members` on a function or `subclasses` on a module. `detail` names the handle's kind and the kinds the edge does apply to. Which kinds each edge applies to is one table: `members` → class, module; `callees` → function, method; `imports`, `imported_by`, `submodules` → module; `subclasses`, `superclasses` → class; `enclosing_scope` → every kind except module.
- Every framework plugin result (Pydantic, Django, Flask) now says which symbol it is and where (#627). Each record gains:
  - `location`: the core tools' location shape (`file`, `line_start`, `line_end`, `column_start`, `column_end`), with `file` absolute. For a symbol it's exactly what `inspect` reports for its handle. Other records carry `{file, line_start, line_end}` or just `{file}`. The existing `file` field may be relative to where the server started.
  - `scope`: `"project"` or `"external"`.
  - `handle`, for results that name a symbol (a model, validator, view, route, blueprint, CLI command, extension module and so on): the canonical handle from pyeye's shared resolver, so you can pass it straight to `inspect`, `outline`, `expand` or `trace` instead of re-resolving an ambiguous name. When the resolver can't place the symbol (for example, a route defined inside an app-factory function), the record carries `unresolved: {reason, detail}` and no handle.

  `get_model_schema` and `trace_model_inheritance` also report the model's `file` and `line`. Existing fields are unchanged, and this works with or without `envelope=true`.
- `get_model_schema` and `trace_model_inheritance` accept a model's handle as `model_name` (#627), for example `accounts.models.User` or a re-export such as `accounts.User`. That's how to pick one of several models that share a name. A successful answer now also carries `found: true` and the model's `handle`.
- Framework plugins are detected in configured packages and namespaces as well as the project root. **This changes startup:** a framework that appears only in a package listed in `.pyeye.json` (e.g. Flask in a configured library) now activates when the server starts, so more plugin tools may appear than before. Previously only the project root was scanned, so such a framework never activated, even after a restart (#659).
- `configure_packages` now re-detects frameworks on the project the server started in. A framework brought in by a newly added package activates, and its tools are registered and callable by name immediately, with no restart. The result's new `activated_plugins` field names them (`[]` when none). Registration is add-only, and no `tools/list_changed` notification is sent yet (#770) (#659).
- Framework plugin tools (`find_pydantic_models`, `get_model_schema`, `find_django_models`, `find_flask_routes`, …) take an optional `project_path`, as the core tools do (#665). Omitted, they answer about the project the server started in, as before. Given, they use that project's own packages, namespaces and `scope_defaults`, and they run even if the project's framework wasn't auto-detected, so an empty result means the scan found none. A `project_path` that doesn't exist is an MCP tool error.
- `expand(module, "imported_by")` now lists importing files that have no module name in a new `unresolved_importers` field, and `trace(follow=["imported_by"])` maps them per node (#668). A file whose path isn't importable (a `my-script.py`, or anything under a `tools-dir/` directory) can't be a stub, so it used to be dropped silently and `imported_by` under-counted a module's dependents. It is now listed by path, like `unresolved_imports` on the `imports` edge (#494). The key is `[]` when every importer has a module name, and absent on every other edge. The file↔module mapper also stops inventing names: a file with a non-identifier path part gets none, and a path such as `app/../repo/x.py` is no longer treated as inside `app`.
- New kind `enum_member` for a member of an `enum.Enum` subclass (`Enum`, `IntEnum`, `StrEnum`, `Flag` and project-defined enum bases, found from the class's own bases). Non-members stay `attribute`: `_sunder_` / `__dunder__` names, names in `_ignore_`, `nonmember(...)`, descriptors, functions and annotation-only names. So does anything pyeye can't tell statically. `inspect` of an enum member shows its value, not the value's type (#695).
- New `reason: "unparseable"` for `expand`'s unsupported branch and `trace`'s `unsupported_edges`, and new `truncation_reason: "unparseable"` for `outline`. Both mean the source file can't be parsed by the server's Python, and the `detail` names the file, the line and the next step. `inspect` omits the affected `edge_counts` entry (#703).

### Changed

- `expand(handle, "subclasses")` and `trace(follow=["subclasses"])` build the project's class graph once and reuse it until a file in the project changes (#397). Previously every query, and every trace hop, rebuilt it. On the pyeye repo, ten follow-up queries take about 50 ms instead of about 10 s. Results are unchanged.
- `expand(module, "imported_by")` and `trace(follow=["imported_by"])` build the project's reverse import graph once and reuse it until a file in the project changes (#397). Previously every query re-scanned every file. On the pyeye repo, ten follow-up queries take about 12 ms instead of about 15 s, and eleven queries take 5–7 s instead of 18–21 s. Results are unchanged.
- **Slower first query:** the first `imported_by` query after startup, or after any file change, is about 50% slower (5–7 s instead of 3.5–4.4 s on the pyeye repo), because it parses every file to build the graph. The second query already makes up the difference.
- **`expand` now returns at most 200 stubs by default; pass `max_stubs=None` for all.** An ambiguous **`resolve` now returns at most 50 candidates by default; pass `max_candidates=None` for all.** When a cap cuts the list, the result also carries `truncated: true`, `truncation_reasons: ["max_stubs"]` (or `["max_candidates"]`) and `total`, the full count. The first stubs (or the first candidates in sorted order) are kept. When nothing is cut, none of these fields appears. `trace` is unaffected. A cap that isn't a positive integer or `None` is an MCP tool error naming the parameter (#435).
- Documentation: a new architecture page, *Resolution and Determinism*, states how pyeye resolves things as one contract. It covers the three tiers (AST for structural facts, bounded Jedi for inference, deferral for reverse queries), the static-edge determinism invariant, the canonical handle resolver's strategy chain, the bare-name rules, and the not-found honesty rules. It's linked from the edge design specs and the python-explore skill. No behaviour change (#449).
- `expand(cls, "superclasses")` now lists bases in declaration order, the start of the class's MRO, instead of sorted by name (#624). This is the order `inspect`'s `superclasses` field already used; both now come from the same walk.
- Decision-log entries need an `Applies-to:` line: `scripts/decisions.py check` (CI and pre-commit) fails a new entry without one. A decision with no code site writes `Applies-to: none (<why>)`, and placeholders such as `n/a` or a bare `none` are rejected. The 41 entries written before the rule are grandfathered by name in `APPLIES_TO_GRANDFATHERED`, a list that only shrinks. The `decision-log` skill documents the rule (#636).
- Framework plugins (Pydantic, Django, Flask) parse source files through the same shared AST cache as `inspect`, `outline` and the other primitives again (#699), so a file is parsed once however many tools read it. Results are unchanged.
- Jedi's in-memory parse cache is bounded again (#713), instead of growing by about 0.35–0.45 MB for every distinct file parsed since #684's fix. It keeps the most recently used parse trees, 600 by default (new setting `PYEYE_PARSO_CACHE_MAX_ENTRIES`). On #684's 3,000-file workload, memory growth drops from about 1,050 MB to about 350 MB. Dropping a tree never changes an answer: pyeye recovers where Jedi would have failed, so the #684 "unresolved" cannot come back.
- Jedi scripts kept in memory have their own cap, 200 by default (new setting `PYEYE_SCRIPT_CACHE_MAX_ENTRIES`), within the existing `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` (#713). Each cached script keeps every module it inferred alive, so this is what actually bounds parse-tree memory. On a 1,167-file project, live parse trees halve (1,179 → 555) and memory growth drops by about 310 MB, at about 4% wall time (within noise). Answers are unchanged: an evicted script is rebuilt on demand.
- The test suite now checks path handling across spellings (#717):
  - Every MCP tool's paths must be absolute, forward-slash and free of `..`.
  - The cross-tool invariants are re-run with the project root reached through a symlink, a `..` spelling, a relative path and, on Windows, the other drive-letter case. The answers must be identical.
  - Each run starts with cold caches, as a fresh server would. The per-PR run covers the corpora that catch symlinked-root bugs, and CI's push-to-main job runs every corpus.
- Under a symlinked root, an in-project `location.file` came back in the resolved spelling, not the caller's. This was recorded as a known gap for #717, and #750 fixed it in this release.
- Only `pyeye.path_utils` and `pyeye.project_layout` may normalise or compare filesystem paths (#717).
  - `scripts/check_cross_platform_paths.py` is now an AST checker with narrow rules: `.resolve()`, `os.path.realpath`/`abspath`/`normpath`/`samefile`, `relative_to`, and `str(path)` comparisons or keys.
  - It runs as a blocking ratchet in pre-commit (`path-ownership`) and in the test suite.
  - The 56 existing sites were routed through `path_utils` by follow-up PRs in this release, and the baseline is now empty.
- Path containment and normalisation in `scope` (`classify_scope`, `is_stdlib_source`, the stdlib roots) and in `JediAnalyzer._search_all_scopes` now goes through `path_utils`. The two duplicate `_is_subpath` helpers are gone, and the path-ownership baseline drops from 56 to 47 sites (#717).
- Internal: path normalisation in the file artifact cache, the file watcher, the class/name-graph cache key, the namespace registry, scope resolution and the stdlib re-export scan now goes through `path_utils` (#717). No behaviour change, except that the watcher now also treats a symlinked spelling of the project root as inside it when deciding which directories to ignore.
- Internal: the analyzer's project root (absolute, in the caller's spelling), Jedi root, sys.path and namespace-root setup, and the check for Jedi's private directory, now go through `path_utils` (#717). No behaviour change: what Jedi is given stays resolved (#714).
- Internal: the plugins' scope-envelope path comparison, the main-scope namespace-subdirectory filter, Flask template names and plugin-record locations now normalise and compare paths through `path_utils` (#717). No behaviour change, except that a namespace directory reached through a symlinked spelling of the project root is now recognised as inside it.
- Internal: the project manager's project, dependency and watched-root keys and the shared project-scan walk now normalise and compare paths through `path_utils` (#717). No behaviour change.
- `PathValidator`, project config, the TypeRef cache, bare-name shadow detection, file-only `resolve` and `configure_packages` now compare and normalise paths only through `pyeye.path_utils`. That migrates the last 15 sites, so the path-ownership baseline is empty: any `.resolve()`, `os.path` normalisation, `.relative_to()` or string path comparison outside `path_utils` / `project_layout` now fails the ratchet. The "outside base directory" validation error now names the base directory as a POSIX path (#717).
- README: guidance for sizing `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` (#768). Set it at or above your project's `.py` file count (default 2000). Just below that count is the worst setting, slower *and* using more memory. Go to about 250 only to trade rebuild time for memory. The default is unchanged, and the measurements are on #768.
- `CONTRIBUTING.md` and the pull request template now state the contribution policy: open or comment on an issue first and wait for a maintainer to assign it. Pull requests not linked to an issue assigned to their author may be closed without review.
- watchdog is now capped below 7 (`watchdog>=3.0.0,<7`). watchdog 7's Windows file watcher can hold back change notifications while files keep changing, and can stop the pyeye server from exiting. pyeye stays on watchdog 6.x until that is fixed.
- The project file scan no longer walks into a nested, independent git clone (a directory below the project whose `.git` is a directory), such as a vendored repository or one provisioned under `.scenario-repos/`. Its files were scanned as part of the project: a clone at a plain path such as `vendor/lib` had its classes resolve as project symbols, and any clone added its parse failures to `unparseable_files`. Submodules and linked worktrees keep their handling; an old-style submodule with a `.git` directory is kept when `.gitmodules` declares it. To analyse a nested clone on purpose, add it with `configure_packages`.

### Deprecated

- The `re_exports` field on `inspect` is deprecated in favour of `expand(handle, "re_exports")`, and will be removed in v3.0 (#749). It still appears, computed by the same cached scan as the edge, so a node and its edge always agree. It stays absent when a package file couldn't be parsed, because the field can't say it is incomplete; the edge can (#393).
- The top-level config keys `cache`, `analysis`, `exclude`, `exclude_patterns`, `performance`, `plugins`, `default_packages`, `logging` and `watch_exclude` are deprecated. pyeye never read them, though the docs and `create_example_config` described them as working. A config that sets one still loads, but each load logs a warning naming the key, and `configure_packages` reports it under `warnings`. The docs now list them as deprecated, and the generated and committed example configs no longer include them (#581).
- `PYEYE_ENABLE_CONNECTION_POOLING`, `PYEYE_POOL_MAX_CONNECTIONS` and `PYEYE_POOL_TTL` have no effect: the connection pool built `jedi.Project` objects that nothing used, and it was removed. Setting one logs a warning at startup. They will be removed in v3.0 (#628).
- `PYEYE_MAX_WORKERS`, `PYEYE_ANALYSIS_TIMEOUT`, `PYEYE_MAX_FILE_SIZE` and `PYEYE_ENABLE_MEMORY_PROFILING` never had an effect. Setting one now logs a warning at startup. They will be removed in v3.0 (#592).
- `pyeye.scope_utils.ScopeValidator`, `ScopeDebugger` and `LazyNamespaceLoader` are unused by pyeye. Constructing one emits a `DeprecationWarning`; they will be removed in v3.0 (#628).

### Removed

- Internal caches that were never read or written: `pyeye.cache.GranularCache`, `ProjectCache` and `CacheMetrics`, `pyeye.dependency_tracker`, and `pyeye.connection_pool` (#628).
- Internal `JediAnalyzer` code that no tool used: the regex re-export scan (`find_reexports`, `_find_init_file`, `_check_symbol_in_init`) together with the `include_import_paths` option of `find_symbol`, and the transitive `include_indirect` / `show_hierarchy` modes of `find_subclasses`. MCP output is unchanged. `inspect`'s `re_exports` comes from `canonicalization.collect_re_exports`, and the transitive subclass closure comes from `trace(follow=["subclasses"])`. The removed comments had claimed that `find_reexports` backed `re_exports` (#628).
- `InputValidator.sanitize_string`, an internal helper that only its own test called, is removed (#628).
- Dropped the unused `tree-sitter` and `tree-sitter-python` runtime dependencies. Nothing in pyeye imported them: structural analysis uses Jedi and the standard-library `ast` module.

### Fixed

- Code changes now reach pyeye's caches in a default setup (#617). Without a `.pyeye.json` that listed extra packages, no file watcher started, so `resolve` kept reporting a new or edited symbol as not found until restart. Even with a watcher, these were missed:
  - **Created, deleted and moved files:** only edits to existing files were handled.
  - **Batched changes:** only the first file of a batch was passed on.
  - **The file-list cache:** it wasn't cleared, so new files stayed invisible for up to 5 minutes.

  Every analyzer is now watched: its project root, and every package, namespace and standalone root it reads from. A root shared by several projects gets one watcher. Each change clears the name index, the file lists, the parse cache and the `inspect` type-reference cache of the projects that read from that root, and only those. Before, any change cleared every project's name index.

- The server no longer dies on Windows with CPython 3.11 when analysis walks into certain stdlib modules (#650). Following the imports of `io` (or `weakref`) makes Jedi recurse about 1,500 frames between the module and its C-accelerator stub. On Linux, macOS and Python 3.12+ that raises a `RecursionError`, which pyeye reports as an unresolved import; on Windows with Python 3.11 the main thread's 1 MB C stack overflowed first and killed the process. `trace` could already reach this by walking into `io`. Every tool that touches Jedi or the analyzers (`resolve`, `resolve_at`, `inspect`, `outline`, `expand`, `trace`, `configure_packages` and the plugin tools) now runs on one dedicated worker thread with a 64 MiB stack, so the recursion is reported as an unresolved import on every platform. Such an import shows up under `unresolved_imports` (e.g. `_io.UnsupportedOperation`). No tool, field or setting changed.
- An analyzer created without a config now detects a `src/` layout, like one created through the project manager (#625). Only the configured path ran `src/` detection, so an analyzer built directly (`JediAnalyzer(path)`) on a src-layout project named everything `src.<pkg>…`: `resolve("mypackage")` returned `src.mypackage`, `resolve("mypackage.module.my_function")` wasn't found, and `inspect` disagreed with `resolve`. Both now use one rule (a `src/` directory holding at least one package) and hand Jedi the same roots. Sibling, virtualenv and global-config discovery still need a config. On Windows, `resolve` and `resolve_at` also named src-layout symbols `src.<pkg>…` even with a config, because Jedi was given its extra search paths with forward slashes and Jedi compares them as text against backslash paths; they are now passed in the platform's native form. No tool, field or setting changed.
- `inspect`'s parameter, return and attribute types no longer depend on which symbol was inspected first (#620). The TypeRef cache was keyed on the annotation's text alone, but a name resolves differently depending on where it is written. In a file with a module-level `Foo` and a nested `Outer.Foo`, inspecting `Outer.g(self, x: Foo)` first made `f(x: Foo)` and the forward ref `h(x: "Foo")` report `Outer.Foo` too. The cache is now keyed on the annotation's position, its source text and the project, and holds at most 4096 entries (least recently used are dropped first). No tool, field or setting changed.
- `inspect` and `outline` now echo the canonical handle on success, as `expand` and `trace` already did (#623). Given a re-export alias such as `package.Thing` (or `pathlib.Path` on Python 3.13, defined in `pathlib._local`), they returned `"handle": "package.Thing"` while `expand` and `trace` returned `package._impl.Thing`; all four now return the definition-site handle. A not-found response still echoes the input.
- `inspect`, `outline`, `expand` and `trace` now find external modules such as `logging`, `os` and `typing` (#623, #602). They reported them as not found, so a module emitted by the `imports` edge was a dead end. `resolve` now finds them too: a later #623 change in this release moved it onto the same resolver.
- Module names are now consistent with the handles pyeye reports when a project's root is itself a package, or when packages are configured alongside it (#625). File↔module naming was implemented four times with different rules, and the copy used by `imported_by` and `resolve(<file>)` left out the root package's name. So in a project rooted at `rootpkg/`, `expand("rootpkg.a", "imported_by")` reported the importer as `b` instead of `rootpkg.b`, `resolve("<…>/rootpkg/b.py")` returned `b`, and `rootpkg.a` couldn't be found by file. Importers in configured additional packages were silently left out of `imported_by` (#619), and re-exports inside those packages were left out of `inspect`'s `re_exports`. All of these now use one mapper that follows Jedi's names, and project-roots lists come from one policy whose subsets are each named once. The re-export import paths pyeye computes internally also carry the root package's name now. No tool, field or setting changed.
- Framework plugin tools (Pydantic, Django, Flask) no longer report an internal failure as "nothing found" (#622, #637). Every plugin wrapped its per-file work in a broad `except Exception`, so a bug, or an `ast` API change like Python 3.14's removal of `ast.Str`, returned `[]` and could not be told apart from a project with no routes or models. Pydantic logged these failures only at debug. File discovery and framework detection had the same problem: a discovery error emptied every plugin tool, and a detection error silently left the plugin off. The Flask plugin now reads string literals through `ast.Constant`, without `ast.Str` or `ast.Num`. As before, an unreadable file or a file that isn't valid Python is skipped, now always with a warning. Any other error is raised as a tool error. A plugin that fails to load is still skipped so the server starts, but the failure is logged at ERROR with a traceback.
- Every `kind` now comes from the documented vocabulary (`class`, `function`, `method`, `module`, `variable`, `attribute`, `property`; #623). A PEP 420 namespace package returned by the `imports` edge was reported as `kind: "namespace"`; it is now `"module"`, as `resolve` and `inspect` already reported it. A Jedi type pyeye doesn't map is now reported as `"variable"` instead of passing through as an undocumented kind. Clients that matched `"namespace"` should match `"module"`.
- The worktree-hook plugin's hooks now run with `uv run --script` instead of bare `python3` (#608). On macOS, the built-in `python3` (3.9) couldn't import the scripts, so creating or removing a worktree through the plugin failed; on Windows, `python3` is often missing. Without PyYAML installed, the config fell back to a built-in parser that dropped every branch type, so `feat-123-x` was no longer nested as `feat/123-x` and aliases stopped collapsing. Each script now declares its Python version (3.10+) and dependencies (PyYAML) in a PEP 723 header, and uv provides a matching interpreter and a cached environment. The fallback parser is removed. The plugin now requires uv on `PATH`, like the pyeye plugin; the first run needs network access to fetch PyYAML.
- The worktree-hook plugin now deletes a merged worktree's branch however the PR was merged (#607). It used only the safe `git branch -d`, which compares against the main checkout's `HEAD`: it kept every squash- or rebase-merged branch, and a merge-commit merge that local `main` hadn't pulled yet. When `-d` refuses, the hook now checks the default branch (`origin/HEAD`'s target, then `origin/main` / `origin/master`, then local `main` / `master`). It deletes with `-D` only if the branch tip is an ancestor (merge commit or fast-forward), every commit has an equivalent (`git cherry`, rebase), or the branch's whole change matches one commit (`git patch-id`, squash). If another PR edited nearby lines before ours merged, no patch matches, so a trial merge (`git merge-tree`, git 2.38+) also counts the branch as merged when merging it would change nothing. Later PRs landing on the default branch don't affect any check. Commits added after the merge, a partial rebase, or a change edited while merging still keep the branch, and so does a merge you haven't fetched. The contributor workflow docs now describe squash-only merging, which this repository enforces.
- The repo's own `.mcp.json` now starts the pyeye server in a new worktree (#600). It ran `uv run --no-sync`, left over from the plugin config. A new worktree has no `.venv`, so `uv run` created an empty one, `--no-sync` installed nothing, and the server exited with `No module named 'pyeye'` (Claude Code showed `CONNECTION_CLOSED`) for the rest of the session. It now uses `--frozen`, which installs exactly `uv.lock` on first start (about 2 s with a warm uv cache) and never re-resolves it. The plugin keeps `--no-sync`: its SessionStart hook installs its dependencies first, and a test now checks that this stays true.
- `outline` on a package no longer reports modules it didn't walk as empty (#596). A package survey lists submodules, not members, but a module that had members came back `children: []`, which the outline contract defines as "measured: no members". `outline("jaraco")` claimed `jaraco.context` was empty when it defines 21 members. Such a module is now `truncated: true` with the new `truncation_reason: "survey_leaf"` (outline that module to see its members); only a genuinely empty module is `children: []`. The package's own `__init__` members were also dropped without any sign. A walked package now reports `member_count` for them (present only when non-zero; `expand(pkg, "members")` lists them). A package with no submodules is now outlined by its members instead of returning an empty survey. Clients that match every `truncation_reason` should handle `survey_leaf`.
- `outline` counts now match the edge they name (#599). A package survey cut off by `max_nodes` reported `member_count` as its number of submodules: `outline("svpkg", max_nodes=1)` gave `member_count: 6` for a package with 1 member and 6 submodules. It now reports `submodule_count`. `member_count` and `submodule_count` always equal `inspect`'s `edge_counts` for `members` and `submodules`.
- Framework plugin tools (Pydantic, Django, Flask) now honour `scope_defaults` when called without `scope` (#559). Each tool used to hard-code `scope="main"` and never read the configured defaults, so a namespace project's `find_pydantic_models` silently searched only the main repo. The default now comes from `scope_defaults.methods.<tool name>` (the MCP tool name, e.g. `find_pydantic_models`), then `scope_defaults.global`, then `"main"`. An explicit `scope` still wins, and `scope_aliases` are now expanded for plugin tools; before, an alias searched nothing. The plugin tools' `scope` parameter now defaults to `null` (use the configured default) instead of `"main"`. Keys that aren't plugin tool names, including the method names the old docs showed (`find_models`, `find_routes`, `list_modules`, `find_subclasses`), never had an effect; they are now logged as ignored. The docs and `examples/configurations/` use tool names, and a test checks that every documented key is a real plugin tool.
- The docs now list only environment variables that take effect (#556). They had named 18 that don't: package and namespace configuration via `PYEYE_PACKAGES` / `PYEYE_NAMESPACE_*` / `PYEYE_NAMESPACES` (never implemented; use `.pyeye.json`, the global config or `configure_packages`); misspellings (`PYEYE_DEBOUNCE` for `PYEYE_WATCHER_DEBOUNCE`, plus `PYEYE_WORKERS` and `PYEYE_TIMEOUT`); invented knobs such as `PYEYE_CACHE_ENABLED`; and four settings that are loaded but never used (`PYEYE_MAX_WORKERS`, `PYEYE_ANALYSIS_TIMEOUT`, `PYEYE_MAX_FILE_SIZE`, `PYEYE_ENABLE_MEMORY_PROFILING`; #592). The README's settings table adds `PYEYE_ARTIFACT_CACHE_MAX_ENTRIES` (the main memory lever) and the logging variables, and explains that variables must be set on the MCP client's server entry, because the client starts the server. Wrong 1-second debounce defaults are corrected to 0.5s. A test now fails if a doc names a variable that pyeye doesn't read and use.
- Documented commands for starting and setting up the server now work (#553). Several pointed at `src/pyeye/server.py`, which doesn't exist: `uv run mcp dev …`, and the `DOCUMENTATION.md` Claude Code and Claude Desktop setup. Running the real module as a script fails anyway, because of its relative imports. Others used `uv run pyeye` (the script is `pyeye-mcp`) or invalid `claude mcp add` forms, including the Sphinx quickstart's Claude Code setup. All now use `python -m pyeye.mcp`. The debugging guides set `PYEYE_LOG_LEVEL` / `PYEYE_LOG_FILE` on the client's server entry, replacing the non-existent `PYEYE_DEBUG` and a made-up log directory. `mcp dev` is dropped; CONTRIBUTING shows the MCP Inspector via `npx` instead. A test now checks that documented server commands and console-script names exist.
- `os.path` and its functions are now located at the `sys.platform` branch in typeshed's `os/path.pyi` that selects `posixpath` or `ntpath`, the same on every OS, instead of in `ntpath.py`. Their handles are unchanged.
- `architecture-review`'s reproduction gate now promotes a stable finding even when the auditor rewords its claim between runs. Finding identity used to rest on the free-text `claim`, so in practice nothing was promoted, and a dismissed non-issue came back whenever it was reworded. Identity is now the axis, a new `facet` field (a closed vocabulary per axis, listed in the auditor prompt) and the handle set. Merging, the gate and dismissed non-issues all key on it, and the axis is now part of the identity. A finding with no valid facet is never promoted, and is merged on its exact claim as before (#498).
- `resolve` on a bare method or class-attribute name no longer returns `unresolved`, the same answer as a name that exists nowhere. When no module or top-level definition has the name, `resolve` now falls back to methods and class-body attributes. One match is returned as found (`resolve("load_settings")` → `pkg.config.Loader.load_settings`); several are `ambiguous` with every candidate. Because it's a fallback, a top-level name still wins, and same-named methods aren't listed. Dunder names (`__eq__`) are never matched this way: they stay `unresolved`, and `detail` now points at the class's dotted handle or `expand(<class>, "members")` (#508).
- The Pydantic, Flask and Django plugins no longer scan nested git worktrees (such as `.claude/worktrees/`) or `.venv` / build directories. They used to report a second copy of every `models.py`, `views.py`, migration and template directory from a sibling worktree, and Pydantic could be detected from `.venv` alone. Git submodules are still scanned.
- `collections.abc` classes (`Mapping`, `Iterable`, …) now resolve instead of being not found. They are located in `_collections_abc.py` and named `collections.abc.*` in every tool, and `_collections_abc.*` resolves to the same handle. `imports` and parameter types for `from collections.abc import Mapping` now report `collections.abc.Mapping` instead of typeshed's `typing.Mapping`.
- `resolve`, `resolve_at` and `inspect` no longer report the target of an attribute assignment (`self.x = …`, `self.x: T = …`, `obj.x = …`) as a local variable of the enclosing method or as a module or class binding. Such a handle (`A.__init__.x`) or position is now not-found (`unresolved`), because instance attributes aren't modelled yet (#565). A position on `self.x` next to a local `x` no longer answers with the local. `expand(members)` and `inspect`'s member count no longer list a module-level `obj.attr = …` or class-body `ns.attr = …` as a fake member (#567).
- The `python-explore` skill and the `expand` / `outline` tool descriptions no longer describe an unresolved handle as one that "doesn't exist", or an absent member as "not in source". A `found: false` is now described as a resolution miss (unknown), and class `members` is scoped to class-body definitions: instance attributes assigned in methods (`self.x = ...`) are not measured. The absence-vs-zero invariant is now stated as a general rule in `docs/api-redesign.md` and the skill, and a conformance test keeps the old phrasings out (#568).
- `inspect` no longer counts a package file or directory whose name is not an identifier (e.g. `show-newlines.py`) as a submodule, so `edge_counts.submodules` now equals `expand(pkg, "submodules")`.
- Two analyzers on the same project with different layouts no longer read each other's cached results (#618). The name index bakes module names in when it's built, and module names depend on the analyzer's source roots, packages and namespaces. But the index was keyed on the project root alone, so the first analyzer to build it fixed the names for every later one: a bare analyzer and a configured one on the same project could return each other's handles, or "not found", depending on which ran first. The index is now keyed on the effective layout as well, and so are cached Jedi `Script`s. Projects with different `added_sys_path` no longer share them.
- `configure_packages` now takes effect without a restart (#618). Symbols in newly added packages were still "not found", because the name index survived the reconfiguration. The project's framework plugins also never got the new package and namespace paths. Now the project's caches are dropped and its active plugins are given the new paths. A framework used only by a newly added package still needs a restart to be detected (#659).
- `trace` now walks exactly what `expand` supports (#621). It used to expand interior nodes that `expand` refuses: before #623 it walked `logging` and `io` while `expand("logging", …)` answered not found. On Windows with CPython 3.11 that walk could reach a ~1500-frame Jedi recursion and crash the server. Now every hop is the same computation as `expand(node, edge)`, and a node `expand` can't resolve is listed in the new `unresolved_nodes` instead of being walked.
  - An edge that doesn't apply to a node's kind, such as `trace(SomeClass, ["imports"])`, is now reported in `unsupported_edges` with `expand`'s reason and detail. It used to come back as a measured-empty walk with `unresolved_imports: {}`. `unresolved_imports` and `unresolved_call_sites` are now present only when their edge was actually walked.
  - `max_nodes` no longer keeps part of a hop. A node's adjacents along an edge are added all together or not at all; a hop that doesn't fit records no edges and sets `truncation_reasons`. So `trace(module, ["members"], max_nodes=3)` returns only the module and reports `max_nodes`, instead of 2 of its 7 members.
  - No field was removed or renamed. Clients that treated an empty `unsupported_edges` as "every edge applied to every node" should read the entries' `detail`.
  - The recursion itself is guarded separately: the server now runs Jedi work on a large-stack thread (#650).
- `resolve` now finds external modules and dotted paths into them, such as `os`, `io`, `logging` and `os.path` (#623, #602). It answered "not found" for them while `inspect`, `outline`, `expand` and `trace` found them, so a module emitted by the `imports` edge resolved in one tool and not the other.
- `resolve_at` no longer reports `found: true` with a handle no other tool accepts (#623). When pyeye couldn't canonicalize the symbol at a position, `resolve_at` returned Jedi's raw full name, which `resolve` and `inspect` then rejected. It now reports not-found.
- Symbols in a configured namespace package that lives outside the project root are found again by `inspect`, `outline`, `expand` and `trace`, and resolve consistently in every tool (#623). Since the previous #623 step they weren't found at all: modules under the namespace package's other directories were never looked up.
- Everything configured in `.pyeye.json` or `configure_packages`, packages and namespaces alike, now has scope `"project"`, as do PEP 420 namespace-package stubs emitted by edges (#623). Configured namespace repos were `"external"`. Installed packages (site-packages) and the standard library stay `"external"`.
- `resolve` on a bare name that is itself a top-level module now returns that module, even when the project defines something with the same name (#623, #602). `resolve("functools")` in a project with its own `functools` module (such as `jaraco.functools`) returned the project module, with no sign that stdlib `functools` existed; it now returns stdlib `functools`. Reach the project's symbol or submodule by its dotted handle (`resolve("jaraco.functools")`). Two top-level packages with one name across project roots still come back ambiguous. Every ambiguous candidate is now the canonical handle that `inspect` accepts, and an alias no longer appears beside its definition.
- `resolve`, `inspect`, `outline`, `expand` and `trace` now find standard-library names whose value is a different object, such as `typing.TYPE_CHECKING`, `typing.Callable`, `typing.ClassVar`, `typing.Dict` and `__future__.annotations` (#623, #602). pyeye looked these up by inferring their value (`TYPE_CHECKING` is a `bool`) and correctly refused that as a wrong answer, so every one was "not found", including when the `imports` edge had just emitted it. They now resolve to their own definition, so `typing.Dict` is reported as `kind: "variable"` with handle `typing.Dict` (as written in `typing.pyi`), not the class `typing.dict`. A name re-exported from somewhere else, such as `collections.abc.Mapping`, is still not found rather than reported under another module's name.
- The `imports` edge now reports external targets under the same handle `resolve` and `inspect` use, such as `datetime.datetime` instead of the private `_datetime.datetime`, and no longer lists a module as importing itself (`io` → `io`) (#623, #602).
- A quoted type annotation (`x: "Foo"`) now resolves to the same class as the unquoted one (`x: Foo`) in `inspect`'s parameter, return and attribute types (#623). It was looked up by bare name across the whole project, so a second `Foo` elsewhere left it without a handle.
- `expand` and `trace` no longer guess when a call, import or base class has more than one possible definition (#624). Jedi can give several targets for one name: a `bytes | str` receiver's `.endswith`, or a name bound by a `try`/`except ImportError` fallback. The callees, imports and superclasses edges used to report the first target, so the same `.clear()` call resolved to `OrderedDict.clear` in one file and `MutableMapping.clear` in another. These cases are now reported as unresolved, in `unresolved_call_sites`, `unresolved_imports` or the new `unresolved_superclasses`. On pyeye's own source, that affects 10 of 3,752 call sites and 1 of 500 imports; no base class was ambiguous. All four places that pick a target (callees, imports, superclasses, and type annotations in `inspect`) now share one rule: exactly one target, or none.
- An edge that doesn't apply to a handle's kind is now always answered as unsupported, `not_applicable` (#626). `members`, `callees`, `subclasses`, `superclasses`, `enclosing_scope` and `submodules` used to answer a wrong kind with a measured `stubs: []`, which reads as "has none"; `imports` and `imported_by` used the unsupported branch but called it `not_yet_implemented` "in this slice". `inspect`'s `edge_counts` and `outline` follow the same table.
- `expand(..., "submodules")` no longer makes up handles for a symbol defined in a package `__init__` (#626). `expand("pkg.__all__", "submodules")` used to list the package's submodules as `pkg.__all__.<name>`, handles that resolve to nothing; it now answers `not_applicable`. The same applies to functions defined in an `__init__`.
- A call that can't run now reaches the client as an MCP tool error with its message, instead of a bare "Error executing tool X". This covers an invalid argument (e.g. `line=0`), a `project_path` that doesn't exist, an unusable config, and an unreadable file. The message names the parameter to fix. A lookup that runs and misses is still a `found: false` response, and a genuine pyeye bug is still a logged crash (#626).
- `find_flask_config` now reports `line` as an integer, like every other tool; it was a string (#627).
- `PLUGINS` in `pyeye.mcp.server` now always lists the active plugins (#627). `initialize_plugins` replaced the list it pointed at, so it went stale.
- `get_model_schema` and `trace_model_inheritance` now say when they can't answer (#627).
  - **No match:** `get_model_schema` returned `null`, and `trace_model_inheritance` returned an empty hierarchy that looked like a model with no parents or children. Both now return the shared not-found shape, `{found: false, model_name, reason, detail}`. Callers that checked for `null` should check `found` instead.
  - **Several models with the same name:** both tools silently used the first one. They now return `{found: true, ambiguous: true, candidates}`, the same shape `resolve` uses for an ambiguous name.
- Framework plugin tools (Pydantic, Django, Flask) now go through the same validation, metrics and dogfooding stack as the core tools (#627), so their calls appear in pyeye's performance metrics and dogfooding tracking under their MCP tool names. No current plugin parameter is one the validator checks, so no plugin answer changes.
- `PYEYE_CACHE_TTL` now sets how long each analyzer's cached scope file lists and lookup results live. It used to size only a cache that nothing wrote to, while the live cache was fixed at 300 seconds (#628).
- `find_pydantic_models`, `get_model_schema`, `find_validators`, `find_field_validators`, `find_model_config` and `trace_model_inheritance` now find indirect Pydantic models, such as `class User(Timestamped)` where `Timestamped(BaseModel)`. Models are identified by where they are defined, so a local class that only shares a name with `BaseModel` is no longer reported. `trace_model_inheritance` lists each model's own children: two models with the same name no longer share each other's children. When a Pydantic base can't be imported where pyeye runs (for example, `pydantic-settings` not installed), its direct subclasses are still found by base name.
- Namespace paths in `.pyeye.json` are now resolved against the project, the same way package paths are (#668). A relative entry such as `../corp-tools` came back raw: the analyzer stored it as `app/../corp-tools`, so files in that repo got names like `app....corp-tools.corp.tools.widgets` and were silently dropped. Plugins and `configure_packages` resolved it against the server's working directory instead. `get_package_paths()` dropped relative namespace paths entirely. Both namespace and package paths now go through one rule: `~` expanded, relative paths anchored to the project, `..` collapsed. A package path starting with `~` now expands too; before, it was joined onto the project path literally.
- `expand(cls, "subclasses")` (and `trace(follow=["subclasses"])`) now finds subclasses in configured packages and namespace repos, not just the main project (#669). A subclass defined in a repo configured through `packages` or `namespaces` was missed, so the edge answered a confident `[]` while `expand(subclass, "superclasses")` named the base. The edge now searches the same project scope that `project` stubs come from: the main project plus configured packages and namespaces, but not standalone script directories.
- `find_computed_fields` now reports each computed field once (#672). The standard Pydantic v2 spelling stacks `@computed_field` over `@property`, and both decorators matched, so such a field came back as two identical records. The tool also now recognises the called form `@computed_field(...)` (for example `@computed_field(repr=False)`), which it used to miss when the method had no `@property`.
- Standard-library names such as `asyncio.Queue` and `json.JSONDecoder` no longer come back unresolved from `resolve`, `inspect` and `outline` once Jedi has parsed about 600 files. parso's parse-cache garbage collection dropped stdlib modules that Jedi was still using; pyeye now turns that collection off.
- Every tool now resolves a search `scope` the same way, and plugin tools change accordingly:
  - **`scope="packages"` searches the configured packages only.** Plugin tools used to search the main project and every namespace too, so results from those places are no longer returned for `packages`. Use `"all"`, or list the scopes you want, to keep them.
  - Plugin tools now accept `scope="standalone"`, and `scope="all"` now includes the standalone script directories.
  - Sub-namespaces (`scope="namespace:acme.tools"`) now work for plugin tools.
  - The `searched` / `unsearched_scopes` envelope reports `standalone` and decides coverage by directory, so `scope="all"` always reports every namespace as searched.
- Symbols in a configured standalone script directory are now labelled `scope: "project"` instead of `"external"`, because `scope="all"` searches them. Before, this happened only when the directory was also picked up by package auto-discovery.
- `line_end` for a name that sits inside a function or class without defining it (a local, a loop target, a class-body attribute) now equals its own `line_start`, as the `Location` contract documents. **Before:** it was the enclosing block's end, so `data = {}` on line 6 of a method spanning lines 5–7 reported `line_start: 6, line_end: 8`, and a class attribute `port: int = 8080` on line 3 reported the class's end line. **After:** `line_start: 6, line_end: 6` and `3, 3`. This applies to `resolve`, `resolve_at` and `inspect` `location`, and to the `line_end` of `expand` / `outline` / `trace` stubs. Functions, methods, classes and module-level variables are unchanged. (A def/class `line_end` is one past its last line, which #709 fixes separately.) (#693)
- A name bound in a class body (assigned, annotated or `ClassVar[...]`) now reports `kind: "attribute"`, the documented kind for it, instead of `variable`. Module- and function-level names stay `variable`. This applies to `resolve`, `resolve_at`, `inspect` and every stub (#695).
- `outline` of a class or function defined in a package `__init__.py` no longer returns the package's submodules as its children (with made-up handles such as `pkg.Widget.sub` marked `truncated: "survey_leaf"`). Package survey mode now applies only to modules, using the same `submodules` applicability rule as `expand`, so the class's own members come back. This affected every Python version; on 3.14 it hit `outline("pathlib.Path")` (#697).
- A module that the server's Python can't parse (for example, code using newer syntax than the interpreter pyeye runs on) is no longer reported as having no members, no imports or no bases. Previously `outline` returned `children: []`, `expand` returned `stubs: []`, and `inspect` counted `members: 0`. A class in such a file also had `superclasses: []`, which is now omitted. The edges are now reported as not measured (#703).
- An internal pyeye or Jedi failure is no longer reported as a fact about your code. `resolve`, `resolve_at`, `inspect`, `expand`, `outline` and `trace` used to answer `found: false` / `unresolved`, or an empty member list, when something broke inside pyeye (as in #684). Now the call fails as a tool error, with the traceback logged. Within a multi-item answer (a trace node, an import, a type, a plugin record), one failing item is reported as unresolved with a detail saying it was an internal error, and the rest of the answer still comes back. `inspect` leaves `re_exports` out instead of reporting it as empty.
- `line_end` for a function, method or class is now its block's last line. **Before:** it was one line past the block (parso ends a block at column 0 of the next line), so a method whose body ends on line 7 reported `line_end: 8`, and only a definition at end of file with no trailing newline was right. **After:** `line_end: 7` in every case, which matches Python's `ast` `end_lineno` and the AST-built class stubs. This applies to `resolve`, `resolve_at` and `inspect` `location`, and to the `line_end` of `expand` / `outline` / `trace` stubs. Non-definition spans are unchanged (#709).
- `inspect`'s `re_exports` now lists only public re-exports (#712). A binding counts when it is in a package `__init__.py`, when the name is in the module's `__all__`, or when a public module imports it from a `_`-prefixed module. A plain internal import (`from pkg.handle import Handle` in another public module) is no longer reported; `imported_by` covers those.
- Re-exports written as relative imports in a package `__init__.py` (`from .core import X`) are now found. They were missed before, because the scan followed only absolute imports (#712).
- `re_exports` is now **absent** (unknown, never a false `[]`) when any file in the symbol's package can't be read or parsed, for example code using syntax newer than the server's Python. The scan reads each file's import table, and per #704 the field has no way to report one bad file. The planned `re_exports` expand edge (#393) will instead list such files in `unparseable_files` and still return what the other files show.
- When the project root is reached through a symlink (for example any macOS temp directory), `resolve` no longer answers `found: true` with an invented `__main__.<name>` handle, and src-layout modules are no longer named `src.<package>…`. A file reached through a normalised or symlinked spelling now maps to its module: file-to-module matching compares resolved paths, while `location.file` keeps the caller's spelling (#603). A handle's module part always comes from pyeye's own module mapper, and a definition the mapper can't place is reported as not found (#714).
- Under a symlinked or otherwise differently-spelled project path, every path in a core or plugin tool's response now comes back under the `project_path` the agent gave. Before, the real (resolved) path came back, which an agent can't match to its own paths or its sandbox's allowed directories. The input validator still checks the resolved form for restricted locations, but no longer rewrites the agent's spelling (#717).
- Jedi's own private subprocess directory (`jedi/inference/compiled/subprocess`) is no longer on the `sys.path` pyeye analyses with. **Before:** `resolve("__init__")` and `resolve("functions")` returned found top-level modules anchored on Jedi's internal files, and an `import functions` of a configured package's module (reachable only through added paths) landed in Jedi instead. **After:** both names are not-found unless the project or an environment really defines them, and imports reach the real module. The rest of the path and its order, the project root, `src/` discovery and configured packages and namespaces are unchanged (#722).
- The reverse scans no longer silently skip project files the server's Python can't parse (e.g. newer syntax than its interpreter). **Before:** a subclass or importer defined in such a file was simply missing from `expand(..., "subclasses")` / `expand(..., "imported_by")`, which still answered a confident list, and a bare-name `resolve` miss read as "no such name". **After:** both edges carry `unparseable_files`, the POSIX paths of the files they couldn't read (`[]` when every file parsed, absent on other edges; per node on `trace`, present when one of those edges was walked). A bare-name `resolve` miss's `detail` names how many project files couldn't be parsed and by which Python (#729).
- A file rewritten within the filesystem's timestamp resolution (2 s on FAT/exFAT, coarse on some network and VM shares) is no longer served from its old parse: pyeye's parse cache now notices the size change as well as the modification time. A rewrite that keeps the same size inside that window can still be missed.
- On macOS and Windows, a file changed in the moment a project's file watcher was starting could be missed, leaving pyeye answering from the old version until something else changed. A one-off check of file modification times shortly after the watcher starts now catches such changes.
- When one pyeye server handles several projects, a project no longer picks up namespaces configured by another project. Previously, every project analysed after another got that project's namespaces too, so `resolve`, `expand`, `scope="all"` searches and plugin tools could return the other project's code.
- pyeye no longer calls the deprecated `asyncio.iscoroutinefunction`. On Python 3.14 it raised a `DeprecationWarning` on every plugin tool call, thousands per session; the replacement is `inspect.iscoroutinefunction` (#763).
- `resolve_at` and `resolve("<path>:<line>")` no longer crash with `IsADirectoryError` when given a namespace package's directory, which is the `location.file` pyeye reports for a PEP 420 namespace package. A directory is the `file_not_found` miss, with a `detail` explaining that a namespace package has no source file of its own. `resolve_at` now also passes such a `detail` through, as `resolve` does (#775).
- A cached `jedi.Script` no longer loses its own module's names when parso's bounded parse cache evicts that file and another Script re-parses it. Jedi looked parso's cache entry up by path, so the old Script read the other parse's names, and `goto` answered nothing: a base class such as `Premium(Widget)`'s came back unresolved, depending on what had been parsed before (#774's CI on 3.13). A filter now uses the cached entry only when it is its own tree, and otherwise computes without the memo, with an identical answer (#783).
- A project configured with extra packages no longer loses them when many projects are open. Invalidating a still-registered project's analyzer (which `configure_packages` does) made it impossible to evict, so the least-recently-used eviction then dropped the project being opened instead. That project's analyzer came back with no package paths, and models and names from its configured packages were silently missing (#784).
- The MCP server's shutdown cleanup tears down the Jedi worker and the file watchers again. It imported a nonexistent `pyeye.mcp.unified_metrics`, which aborted the cleanup on every shutdown. Each cleanup step now runs independently, so one failing step is logged and cannot skip the others.
- The re-export scan behind `inspect`'s `re_exports` field and the `re_exports` edge parses each package file once per scan. It used to re-parse the whole package on every hop of its walk, so a symbol bound in many modules (`django.apps.apps`) took minutes for one `inspect`. The results are unchanged.
- `inspect` no longer re-indexes a symbol's whole package for each new handle. The re-export scan behind the deprecated `re_exports` field (and the `re_exports` edge) cached its result per handle, so every new handle rebuilt the package's import index. On django that was all 907 package files per `inspect`, 13–15 s for each cold project handle. The index is now cached once per package, about 1.3 MB on django, and cleared by the file watcher and `configure_packages`, so a cold `inspect` there takes 0.02–1.3 s. Answers are unchanged (#803).
- A class added while a lookup was running could stay invisible to `resolve` (and any name-index lookup) until another file changed. When the watcher delivered the change, a lookup landing mid-invalidation rebuilt the index from a stale cached file list and kept it. File listings are now dropped before the index is marked stale, and a listing that raced an invalidation is no longer cached (#817).

## [2.0.0] - 2026-11-07

### BREAKING CHANGES

#### MCP tool surface redesigned around progressive-disclosure primitives

The Jedi-shaped navigation tools have been replaced by six primitives that
operate on **canonical handles** (re-exported paths collapse to the definition
site), return small structural responses by default (no source content), and
honour an absence-vs-zero invariant. See `docs/api-redesign.md` for the full
rationale.

**New interface:** `resolve` / `resolve_at` / `inspect` / `outline` / `expand`
/ `trace`.

##### Removed tools

The clearly-replaced legacy navigation tools were **removed** from the MCP
surface (#376). Migrate existing agent/integration code as follows:

| Removed tool | Replacement | Notes |
|--------------|-------------|-------|
| `find_symbol(name)` | `resolve(name)` | Canonical handle; ambiguity surfaced explicitly |
| `goto_definition(file, line, col)` | `resolve_at(file, line, col)` | Returns a canonical handle directly |
| `get_type_info(file, line, col)` | `inspect(handle)` | Richer Node; no source content |
| `get_module_info(module)` | `inspect(module_handle)` | Same Node contract; member count via `edge_counts.members` |
| `find_imports(module)` | `expand(handle, edge="imported_by")` | Stub-based, canonical handles |
| `find_subclasses(class)` | `expand(handle, edge="subclasses")` (direct) / `trace(follow=["subclasses"], max_depth=k)` (closure) | Direct subclasses are one hop (#422); full transitive closure via `trace`. Not in `edge_counts` (cheap count gated on #333/#397). |
| `list_packages` / `list_modules` | `outline` | One structural lister |
| `list_project_structure` | `outline` | One structural lister |

Note: several same-named `JediAnalyzer` methods are internal implementation and
remain because they back the new operations — `analyzer.find_symbol` (behind
`resolve`), `analyzer.find_subclasses` (behind the `subclasses` edge),
`analyzer.find_importers` (behind `imported_by`), and `analyzer.find_reexports`
(behind `inspect(...).re_exports`). For the tools in this table only the MCP
**tool wrappers** were removed. Others (`analyzer.list_modules`,
`analyzer.list_packages`, `analyzer.find_imports`) survive without a production
caller and are not load-bearing for anything. The three tools
removed under #505 below are the exception: their backing methods
(`find_references`, `get_call_hierarchy`, `analyze_dependencies`, and the
transitively-orphaned `get_module_info`) were deleted outright, so they cannot be
re-exposed by a future wrapper.

##### Also removed: the last three legacy tools (#505)

`find_references`, `get_call_hierarchy`, and `analyze_dependencies` were
previously slated to survive this release as deprecated. They are **removed**
instead. An audit for the 2.0 tag found they do not merely under-report — they
answer *confidently and wrongly*, which is the failure mode this release exists
to eliminate:

- **`get_call_hierarchy`** — `callees` could never be populated at all. It read
  module-level names with Jedi's defaults (`definitions=True, references=False`)
  and then skipped every result via `if name.is_definition(): continue`, so the
  list was structurally always empty. Its callers half resolved bare names by
  taking the *first* `_search_all_scopes` match with no ambiguity signal, so it
  could report a different symbol's callers as your symbol's.
- **`analyze_dependencies`** — derived `project_modules` from `rel_path.parts[0]`,
  which on a `src/` layout is `"src"`, so every first-party module was classified
  as third-party. That emptied the input to the cycle scan, making
  `circular_dependencies: []` wrong by construction on exactly the layout it was
  most often pointed at. Its stdlib set was also a hardcoded ~40-name literal
  rather than `sys.stdlib_module_names`.
- **`find_references`** — advertised "Find ALL usages" while returning a flat list
  with no absence-vs-zero signal, so an empty result was indistinguishable from a
  search that never reached. Its standalone-file branch matched candidates by
  string comparison where its own comment claimed a `goto` check.

| Removed tool | Replacement | Notes |
|--------------|-------------|-------|
| `find_references` | **None** — deferred to #333 | Reverse references are not answerable today. Delegate to a language server: `resolve` gives the definition-site position an LSP `findReferences` needs. `expand` reports the edge as unsupported rather than guessing. |
| `get_call_hierarchy` | `expand(handle, edge="callees")` (forward only) | Forward calls are covered, with `unresolved_call_sites` marking un-inferable sites. Callers remain deferred to #333. |
| `analyze_dependencies` | `expand(handle, "imports")`, `expand(handle, "imported_by")`, `trace(follow=["imports"])` | Fan-in/fan-out and the import closure are covered. For cycles, scan the `trace` result's `edges` for one whose `to` is the start module — documented in the `python-explore` skill. |

The superseded `lookup` entry point (`pyeye.mcp.lookup` /
`pyeye.mcp.lookup_builders`) was removed in the same change. It had not been
registered as an MCP tool since the primitives landed, and was the only remaining
non-MCP consumer of the removed analyzer methods.

`pyeye.agents` (the test-coverage agent) was removed too. It shipped in the wheel
while planning its work entirely in terms of tools deleted across both v2.0
phases — emitting instructions naming `mcp__pyeye__find_references`,
`mcp__pyeye__get_call_hierarchy`, `mcp__pyeye__analyze_dependencies`,
`mcp__pyeye__find_symbol`, `mcp__pyeye__get_module_info` and more — so any
consumer following one of its plans would hit tool-not-found. It was orphaned
(no importer outside its own test) and, like the retired
`cross-platform-validator` agent (#483), could not be restored by renaming onto
the primitives: its planning relied on fuzzy symbol search, reverse references,
and call hierarchy, which the redesign dropped or deferred to #333.

**Required action:** if you call any of these three tools, migrate per the table
above. If you were using `find_references` or `get_call_hierarchy` for caller
data, route that question to a language server instead — pyeye will not answer it
until #333 lands, and will say so rather than guess.

`configure_packages` is orthogonal to the navigation redesign and is unchanged.
The framework plugin tools keep their behaviour but several are renamed; see
the next section.

#### Framework plugin tools register under their declared names (#555)

Each plugin declares its tool names as the keys of `register_tools()`, but the
server registered tools under the Python method name and discarded the key. The
method names collide across plugins, and the SDK keeps the first tool on a
collision, so with Pydantic, Django and Flask all detected, Django's
`find_models`, `find_views` and `find_templates` were never exposed (only a log
warning). The documented `find_django_*` / `find_flask_*` /
`find_pydantic_models` names did not exist.

Tools now register under the declared keys. Methods, parameters and return
shapes are unchanged; only the client-visible names move. In Claude Code, for
example, `mcp__pyeye__find_routes` becomes `mcp__pyeye__find_flask_routes`.

| Plugin | Old tool name | New tool name |
|--------|---------------|---------------|
| Flask | `find_routes` | `find_flask_routes` |
| Flask | `find_blueprints` | `find_flask_blueprints` |
| Flask | `find_views` | `find_flask_views` |
| Flask | `find_templates` | `find_flask_templates` |
| Flask | `find_extensions` | `find_flask_extensions` |
| Flask | `find_config` | `find_flask_config` |
| Pydantic | `find_models` | `find_pydantic_models` |
| Django | `find_models` (often hidden by Pydantic's) | `find_django_models` |
| Django | `find_views` (often hidden by Flask's) | `find_django_views` |
| Django | `find_urls` | `find_django_urls` |
| Django | `find_templates` (often hidden by Flask's) | `find_django_templates` |
| Django | `find_migrations` | `find_django_migrations` |

Unchanged: `find_error_handlers`, `find_cli_commands`, `get_model_schema`,
`find_validators`, `find_field_validators`, `find_model_config`,
`trace_model_inheritance`, `find_computed_fields`.

`scope_defaults.methods` in `.pyeye.json` is keyed on method names and is not
affected by the rename. A duplicate plugin tool name now stops the server at startup instead
of silently dropping a tool, and `tests/test_plugin_tool_names_conformance.py`
pins the registered names.

**Required action:** update anything that names the old tools: client
configuration, prompts, and permission allow-lists (in Claude Code, rules such
as `mcp__pyeye__find_routes`). A pyeye server that is already running keeps the
old names until it restarts, so restart it after upgrading.

#### Unresolvable handles return an explicit not-found result (#545)

`inspect`, `outline` and `expand` no longer invent an answer when a handle does
not resolve. Previously `inspect` returned a placeholder node (`kind:
"variable"`, `scope: "external"`, empty `file`) that looked like a real
variable, `outline` returned the same placeholder as a one-node tree with
`children: []`, and `expand` returned `stubs: []` — which its own contract
defines as "measured, none found" — plus `unresolved_call_sites: 0` for
`callees`. All three now return:

```json
{"found": false, "handle": "<input>", "reason": "unresolved",
 "detail": "Handle '<input>' did not resolve to a symbol. Call resolve('<leaf>') to find its canonical handle."}
```

`expand` also echoes `edge`. A not-found result carries no `kind`, `location`,
`node`, `children` or `stubs`. `reason` uses the same value `resolve` already
returns.

Every successful response from these three tools now includes `found: true`
(on the root of an `outline` tree only), so callers check one field instead of
guessing from which keys are present. `expand` now resolves the handle before
checking the edge, so a nonexistent handle paired with an unsupported edge such
as `callers` reports not-found rather than "unsupported". `trace` is unchanged:
it already lists unresolved start handles in `unresolved_roots`.

**Required action:** check `found` before reading `inspect` / `outline` /
`expand` results. Code that treated `kind == "variable"` with an empty
`location.file`, or an empty `stubs` list, as "symbol not found" must switch to
`found is False`. An empty `stubs` list with `found: true` now always means the
symbol exists and has no neighbours on that edge.

#### `outline` defaults to direct members only (#474)

`outline(<module>)` and `outline(<class>)` called without `max_depth` used to
walk the whole member tree, limited only by `max_nodes=200`. They now default to
`max_depth=1`: the root's direct members, with any nested non-empty container (a
class inside the module, a nested class) returned as `truncated: true,
truncation_reason: "max_depth"` and no `children`. Package roots already
defaulted to depth 1 and are unchanged.

The `max_depth` default is now the integer `1` instead of `None`, and
`max_depth=None` means unbounded for every root kind. For a package root this is
new: `None` previously meant "depth 1", so a fully recursive package survey was
not reachable.

**Required action:** callers that relied on the deep default should pass
`max_depth=None` (unbounded) or an explicit depth, or call `outline` again on a
truncated node's handle to drill into it.

#### `configure_packages` drops its standalone-scan options (#513, #253)

`configure_packages` no longer takes `recursive`, `file_pattern` or
`exclude_patterns`, and no longer saves them under `standalone` in `.pyeye.json`.
They never took effect: their only reader, `JediAnalyzer._discover_standalone_files`,
lost its last caller when `find_references` was removed (#505), and even with a
caller it never read `exclude_patterns` from the config. That method is removed
too. Standalone directories are still analysed, in full: every `.py` file under
each `standalone.dirs` entry. The tool now has 4 parameters (`packages`,
`namespaces`, `standalone_dirs`, `save`), which also resolves #253.

`get_standalone_config()` now returns only `{"dirs": [...]}`. An existing
`.pyeye.json` that still carries the removed keys loads normally: the keys are
ignored with a logged warning, and the `configure_packages` response includes a
`warnings` list naming them. The field is absent when there is nothing to report.

**Required action:** none for the analysis itself, since the options never
applied. Remove `recursive` / `file_pattern` / `exclude_patterns` from
`standalone` in `.pyeye.json` to silence the warning. Clients that still pass
them to `configure_packages` are not rejected; the arguments are ignored.

#### Python 3.11 or newer required (#528)

Python 3.10 support is dropped: `requires-python` is now `>=3.11`. Python 3.10
reached end of life on 2026-10-01 (PEP 619), and some security fixes in pyeye's
dependencies (filelock ≥4.2.1) only ship for 3.11+.

**Who needs to act:**

- **Claude Code plugin users:** nothing to do. The plugin builds its own
  environment with `uv`, which picks or downloads a suitable interpreter.
- **`pip` / `pipx` installs:** install into a Python 3.11+ interpreter, for
  example `pipx install --python python3.12 pyeye-mcp`.

This only affects the interpreter pyeye *runs on*. pyeye still analyzes code
written for older Python versions.

### Added

- Releases are pull requests (#583). `python scripts/changelog.py prepare X.Y.Z` promotes `[Unreleased]` to a dated version section and refuses an under-bump (e.g. `### BREAKING CHANGES` released as a minor). Merging the `chore(release): vX.Y.Z` PR, by squash or merge commit (#585, #587), tags the merge commit and publishes it, with the version's CHANGELOG section as the GitHub Release notes. `python scripts/changelog.py check` replaces `validate_changelog.py`, which could not fail in CI, and now requires every `v*` tag to have a section. The missing 1.0.1, 1.1.1 and 1.1.2 sections are backfilled, and the 0.x sections are put back in order.
- Python 3.13 support (#529): CI tests it (Linux, Windows and macOS on PRs; all three on main) and the classifiers list it. The CI pre-commit job now audits dependencies on 3.13, the newest supported version. `.pre-commit-config.yaml` now builds hook environments with `python3` instead of a pinned `python3.12`, which the 3.13 runner didn't have (the remaining remote hooks move to `uv run` in #547). `path_utils.dedupe_paths` now rejects paths containing a NUL byte explicitly; on Windows with 3.13, `Path.resolve()` no longer raises for them, so such paths had slipped into root lists.
- Progressive-disclosure operations over canonical handles: `resolve`,
  `resolve_at`, `inspect`, `outline`, `expand`, and `trace`. Supported `expand`
  / `trace` edges: `members`, `callees`, `imports`, `imported_by`,
  `subclasses`, `superclasses`, `enclosing_scope`, and `submodules`.
- `pyeye://about` MCP resource and in-band issue-reporting pointers (server
  `instructions`, `report_issues` keys on unsupported `expand`/`trace`
  payloads).
- `trace` honesty fields so an empty/clean-looking subgraph is never misread as a
  real zero (#488): `unresolved_roots` (always present; `[]` when every start
  handle resolved, the failed handles otherwise) and `unresolved_call_sites` (a
  `{handle: count}` map, present only when `callees` is traced) surfacing per-node
  calls that didn't resolve — restoring across hops the count `expand(callees)`
  already reports. Conformance-guarded (linter rules T.6/T.7).
- `unresolved_imports` honesty field on the `imports` edge (#494): a
  statically-present `from X import Y` that forward-`goto` cannot resolve is now
  surfaced (by its intended dotted target) instead of being silently dropped —
  `expand(handle, "imports")` carries a list (`[]` when all resolved) and
  `trace(follow=["imports"])` a `{handle: [target, …]}` map (present only when
  `imports` is traced). Closes a silent false-negative in dependency-graph
  queries. Conformance-guarded (linter rules E.5/T.8).

### Removed

- `scripts/install_hooks.sh` (#578). It overwrote `.git/hooks/pre-commit`, the hook `pre-commit install` creates, with a script that skipped every pre-commit check, and wrote its own `post-checkout` and `prepare-commit-msg` hooks. `scripts/setup_dogfooding.sh` now runs `pre-commit install` instead. The commit-message metrics comment is dropped: with `git commit -m` git keeps `#` lines, so it leaked into real commit messages. If you ran the old script, restore your hooks with `uv run --frozen pre-commit install`.
- `worktree-manager` agent and the `claude/development` "learning hub" workflow. Worktrees now use native tooling (the `EnterWorktree` tool / superpowers `using-git-worktrees` skill) under `.claude/worktrees`; removal safety remains via `scripts/worktree_safety.py` and the rules in `01-core-rules.md`. Also removed the now-obsolete `docs/CLAUDE_WORKTREE_WORKFLOW.md` and `.claude/startup-context.md`.
- `cross-platform-validator` agent (`.claude/agents/cross-platform-validator.md` + `cross-platform-issues.yaml`) and its `scripts/test_cross_platform_agent.py` harness (#483). It was built on the Jedi-shaped tools removed in this release and re-implemented, semantically, a textual pattern check that `scripts/check_cross_platform_paths.py` already does statically. Cross-platform path validation now uses that script plus the rules in `.claude/instructions/10-cross-platform.md`.
- Unused `diskcache` runtime dependency (#289). It was declared in `pyproject.toml` but never imported anywhere in the codebase — caching is entirely in-memory (`cache.py` uses `watchdog` + `DependencyTracker`; `file_artifact_cache.py` is an `OrderedDict` LRU) and there is no `pickle` usage in `src/`. Removing the dependency resolves CVE-2025-69872 (diskcache pickle deserialization, **no upstream fix exists**) outright rather than waiting on upstream, and drops the corresponding `--ignore-vuln` from the `pip-audit` pre-commit hook. The `DOCUMENTATION.md` architecture diagram, which showed the result cache as "DiskCache", now reads "In-Memory".
- The v1 API reference pages `docs/api/core-navigation.md`, `docs/api/module-analysis.md` and `docs/api/quick-reference.md` (#509). Of the 15 tools they documented, only `configure_packages` still exists. The core primitives are documented in the README's Core Tools section and the `python-explore` skill instead, so there is one source rather than a hand-kept copy that drifts. `docs/api/README.md` now indexes the framework plugin docs and has a corrected `configure_packages` reference. The old page listed a nonexistent `auto_discovered` result and omitted `standalone_dirs`.
- `safety` dev dependency (#522). Every release pins `filelock<4`, which blocks the filelock security fix, and nothing ran it: CI had already dropped its safety step and pre-commit scans dependencies with `pip-audit`. Removing it also drops `nltk`, which was the source of 22 open Dependabot alerts.

### Changed

- The `pip-audit` pre-commit hook no longer ignores any vulnerabilities (#318, #326). Both ignores were obsolete: `CVE-2026-4539` was fixed in pygments 2.20.0, which `uv.lock` now pins, and `GHSA-4xh5-x5gv-qwph` was waiting for pip 25.3, while the lock has pip 26.2.2. With no ignores, `pip-audit` reports no known vulnerabilities on Python 3.12 (the CI audit environment) and 3.13, so the 37 lockfile findings tracked in #326 are gone too.
- Shipped docs no longer teach removed tools (#509). `DOCUMENTATION.md`'s Tools Reference now points to the README and the `python-explore` skill instead of documenting 13 removed tools. The migration guide, troubleshooting guide, testing conventions/performance guides, and the metrics docs' sample output use the primitives. `docs/api-redesign.md` no longer says `find_references` / `get_call_hierarchy` / `analyze_dependencies` are still present. A new conformance test (`TestNoShippedProseTeachesRemovedTools`) fails on any mention of a fully removed tool in shipped `.md`/`.json` outside a reasoned allowlist, and on any API heading for a name that survives only as an internal method.
- The server runs on the MCP Python SDK 2.x (#538): `FastMCP` → `MCPServer` (`mcp.server.mcpserver`), requirement `mcp[cli]>=2.3.0,<3`. `instructions` stays a keyword argument (mcp 2's second positional is `title`) and the server now passes `version=`, so `serverInfo.version` reports the pyeye version. Verified at the wire level over stdio JSON-RPC against the mcp 1.30 server: instructions, all 22 tool names/descriptions/input schemas (including dynamically registered plugin tools), tool results and `structuredContent`, error results (`isError` with the same messages) and the `pyeye://about` resource are identical; the only difference is that mcp 2 no longer advertises an empty `experimental` capability. Dependency changes come from mcp itself: `httpx` → `httpx2`, and `opentelemetry-api` is required again.
- Every Python pre-commit hook now runs from the uv environment with `uv run --frozen` (#547), finishing #413. detect-secrets, bandit, pydocstyle, commitizen and the `pre-commit-hooks` file checks were remote hook repos with their own pinned versions, which Dependabot never updated and which had drifted from `uv.lock`: the commit hook ran bandit 1.8.6 while CI ran 1.9.4, and commitizen 3.13.0 while the lock had 4.19.3. `pre-commit-hooks` 4.5.0 joins the dev group. Hook behavior is unchanged (verified hook-by-hook against deliberately bad files), and neither upgraded tool flags anything new. Only markdownlint (Node) stays remote; contract tests enforce this.
- Python 3.11 is now the minimum (#528). ruff, black and mypy target 3.11; the CI and release workflows test 3.11 and 3.12 (Codecov uploads moved from the 3.10 job to 3.11); the `filelock` version split and the `tomli` fallback are gone; `asyncio.TimeoutError` is written as the built-in `TimeoutError`, which it aliases from 3.11.
- Bumped the pinned dev linters: ruff 0.15.21 → 0.16.10, mypy 2.2.0 → 2.4.0 (#525). Neither surfaces new findings. Redoes Dependabot #521, which updated the pins without regenerating `uv.lock`.
- Migrated the Claude instructions off the removed worktree agent and the persistent `claude/development` branch (`04-agent-triggers.md`, `02-session-startup.md`, `06-workflow-commits.md`, `08-project-specific.md`, `11-pr-requirements.md`, `00-documentation-system.md`). Per-worktree environment setup now uses `uv sync` (`dev` is a default dependency group as of #414).
- Local environment setup now uses `uv sync --frozen` instead of bare `uv sync` (#573): `setup.sh`, the contributor/troubleshooting/Sphinx docs and the Claude instructions install exactly from `uv.lock` and never re-resolve or rewrite it. CI keeps `uv sync --locked`. A guard test (`tests/test_local_uv_sync_frozen.py`) fails if a bare `uv sync` comes back.

### Fixed

- A project that lives under a directory named like an excluded one (`build`, `dist`, `env`, `venv`, `.venv`, `node_modules`, `.tox`, `*.egg-info`, …) is now scanned normally (#515). The exclusion check ran against every component of the absolute path, so e.g. `~/dev/build/myproject` or a CI workspace at `/build` scanned to **zero files** with no warning, and every lookup then answered "not found". The same bug affected standalone-script discovery, and scope classification marked every file of a project under `.tox/`, `__pycache__/` or `*.egg-info/` as `external`. Exclusions now apply only below the scan or project root.
- Starting a dogfooding metrics session now first saves any session still open to `history.jsonl` (#578). Previously the next start (for example the post-checkout hook on the next branch) overwrote `current_session.json`, so the open session's data was lost. This replaces the removed `install_hooks.sh`'s "end the session at every commit" hook.
- The post-checkout dogfooding hook only starts a metrics session for `type/<issue>-description` branches (#576). It used to take the first number anywhere in the branch name, so remote-control session branches like `worktree-bridge-cse_01…` logged metrics against issue #1, and branch names with version numbers in them were misread the same way. The bash helpers in `scripts/install_hooks.sh` and `scripts/setup_aliases.sh` had the same bug and now parse branches the same way; a test checks all three against one set of branch names.
- The `decision-log-nudge` post-commit hook now runs through the uv env (`uv run --frozen python ...`) instead of a bare `python` (#574). On machines with only `python3` on PATH it failed with "Executable `python` not found" after every commit, so the nudge never ran. A guard test rejects any hook that invokes a bare `python`/`python3`.
- `resolve` on a class attribute now returns the attribute itself (#506). Canonicalization and `resolve` treated everything before a handle's last dot as a module, so for `module.Class.attr` they missed and fell back to Jedi inference, which reports a value's *type*. `resolve("pkg.Widget.name")` for `name: str = …` returned `found: true` with handle `builtins.str`, and an attribute bound to a function (`factory = make_widget`) returned `make_widget`, a different project symbol. Handles are now placed by walking back to the nearest module and matching the definition, so class attributes resolve to their own definition with kind, project scope and span. Members reached through a re-exported class (`package.Widget.name`) collapse to the definition site, and `inspect` on that alias path now finds the attribute too. Methods worked before only because a function infers to itself; they now take the same direct path. Instance attributes assigned in `__init__` (`self.x = …`) are still not modelled by any primitive; `resolve`, `inspect` and `expand(members)` consistently report them absent.
- `resolve` no longer reports a different object when inferring an external name (#544). Its external fallback accepted whatever Jedi inferred, so `collections.abc.Mapping` resolved to `typing._SpecialGenericAlias`. It now accepts an inferred definition only when its name matches the one requested, the same guard canonicalization has used since #529, and otherwise returns `found: false`. The same wrong answer affected every `collections.abc` ABC (`Sequence`, `Iterable`, `Callable`, …) and `typing` special forms such as `typing.Optional`, because typeshed declares the ABCs in `typing`. These now return `found: false` instead of a different object. Resolving them to their runtime definition site (`_collections_abc`) is tracked in #544.
- `inspect`, `expand`, `outline` and `trace` now describe external (stdlib / site-packages) symbols reached through a re-export, such as `asyncio.Queue`, `json.JSONDecoder`, or `pathlib.Path` on Python 3.13 (where it moved to `pathlib._local`) (#529). Previously `resolve_canonical` could not follow external modules, so the alias retry (#431) found nothing and these returned a placeholder node (`kind: "variable"`, empty location) instead of the class. `resolve` now takes kind and location from the external resolver when the canonical definition is outside the project. An external re-export under a *different* name (`from x import A as B`) still stays unresolved rather than risk describing the wrong object.
- The release workflow's `validate` job now runs `pytest`, `mypy` and `bandit` through `uv run` (#540). Since #414 the job installs dependencies with `uv sync` into `.venv`, so the bare commands were no longer on `PATH` and the next tag push would have failed. A contract test (`tests/test_ci_uv_run_tools.py`) fails if any workflow step calls a venv tool without `uv run`.
- `pip install pyeye-mcp` no longer installs a server that can't start (#537). The `mcp` requirement had no upper bound, so installs without the lockfile resolved mcp 2.x, which removed `mcp.server.fastmcp` (the server failed with `ModuleNotFoundError`). The requirement now has an upper bound on the major the server is built for (`mcp[cli]>=2.3.0,<3` after the `MCPServer` migration, #538). Plugin installs were unaffected because they use `uv.lock`. Also removed the unused standalone `fastmcp` dependency (pyeye uses the FastMCP bundled in `mcp`), which drops 35 transitive packages including authlib, opentelemetry-api and dnspython. A contract test (`tests/test_mcp_dependency_contract.py`) ties the declared `mcp` range to the API the server imports.
- Resolved open Dependabot security alerts (#522) by upgrading locked versions within current majors: pyjwt 2.15.1, anyio ≥4.14.2, urllib3 2.8.0, fastmcp/fastmcp-slim 3.4.11, mcp 1.30.0, opentelemetry-api 1.45.1, setuptools 84.2.1, pip 26.2.2, msgpack 1.2.4. `filelock` now requires ≥4.2.1, which needs Python 3.11 (see the Python 3.11 requirement under BREAKING CHANGES, #528). The CI pre-commit job now runs on Python 3.12 so `pip-audit` audits the newest supported environment. Bumped `black` to 26.10.1 (GHSA-cg8m-r9f2-5wm2).
- CI no longer posts a false "Documentation-only change detected" comment on PRs that also change code (#500). The feedback now lives in `ci.yml` and reuses the same `changes` (docs-vs-code) classifier as the test gate, so the comment can never contradict what CI actually ran; the divergent `docs.yml` workflow was removed. Also stripped fabricated time/percentage "CI savings" figures from the workflow comments, keeping the accurate platform-multiplier table.

## [1.1.2] - 2026-03-11

### Fixed

- Correct MRO computation and cross-project `find_symbol` (#307).

## [1.1.1] - 2026-03-10

### Added

- `get_call_hierarchy` accepts class names (#303).
- A performance-metrics tool, and a faster `find_subclasses` (#304).

### Fixed

- The release workflow uses the `gh` CLI instead of deprecated release actions (#305).
- Clone URLs in the docs; development artifacts removed (#300).

## [1.0.1] - 2026-02-17

### Added

- Standalone script analysis (#236).
- Source-layout auto-detection from `pyproject.toml`.
- Polymorphic reference search via `include_subclasses`.
- PyPI publishing through Trusted Publisher, with TestPyPI first.

### Fixed

- `src/`-layout projects in `find_imports`, `list_modules` and `list_packages`, and the src paths passed to Jedi (#277).
- Relative imports in `find_imports`.
- Base-class detection falls back to the AST when Jedi fails.
- `find_references` searches standalone files outside the project path.

The 1.0.1, 1.1.1 and 1.1.2 sections were backfilled during the 2.0 release from
their GitHub Releases, which list every change: <https://github.com/okeefeco/pyeye-mcp/releases>.

## [1.0.0] - 2025-10-04

### BREAKING CHANGES

#### Complete rebrand from "python-code-intelligence-mcp" to "PyEye"

This is a breaking change that requires migration steps:

#### Required Actions

1. Rename configuration files:
   - `.pycodemcp.json` → `.pyeye.json`
   - `.pycodemcp.yaml` → `.pyeye.yaml`
   - `.pycodemcp.override.json` → `.pyeye.override.json`

2. Rename configuration directories:
   - `~/.pycodemcp/` → `~/.pyeye/`
   - `~/.config/pycodemcp/` → `~/.config/pyeye/`

3. Update environment variables:
   - `PYCODEMCP_*` → `PYEYE_*`
   - Example: `PYCODEMCP_CACHE_TTL` → `PYEYE_CACHE_TTL`

4. Update pyproject.toml sections:
   - `[tool.pycodemcp]` → `[tool.pyeye]`

5. Update MCP configuration:
   - Module import: `from pyeye.mcp.server import mcp`
   - Package name: `pyeye-mcp`

#### What Changed

- Package renamed: `python-code-intelligence-mcp` → `pyeye-mcp`
- Module renamed: `pycodemcp` → `pyeye`
- Server moved: `pyeye.server` → `pyeye.mcp.server`
- All documentation updated to reflect new branding
- All configuration file formats updated

### Fixed

- Renamed `.pycodemcp.json.example` to `.pyeye.json.example` (missed in initial rebrand)
- Fixed Sphinx documentation paths for `pyeye.mcp.server` module structure
- Fixed test mocking conflicts with new module structure
- Restored `_version.pyi` type stub file for proper type checking
- Updated release workflow package names from `python_code_intelligence_mcp` to `pyeye_mcp`

## [0.3.0] - 2025-08-27

### Added

- Git-based versioning with setuptools_scm - automatic version management from git tags
- Persistent branch support in worktree-manager agent for claude/development workflow

### Changed

- Switched from manual version management to setuptools_scm
- Simplified release process - no more version files to update
- Version now automatically derived from git tags and commits

### Fixed

- CI installation of setuptools_scm before generating version file
- Proper version imports for CI and type checking environments
- Type annotations for version tuple

### Removed

- Obsolete release automation agent (replaced by simplified git tag process)
- Manual version sync scripts (no longer needed with setuptools_scm)
- Version management scripts: check_version_sync.py, prepare_release.py
- Outdated release documentation: RELEASING.md, RELEASE_CHECKLIST.md
- Release automation tests (no longer applicable)

## [0.2.0] - 2025-08-25

### Feat

- enable connection pooling by default for better performance
- add MCP monitoring hooks system for automatic usage tracking
- add persistent branch handling for claude/development workflow
- add PR merging capabilities and composite agent workflows
- add pr-workflow agent for complete PR lifecycle management
- add worktree-manager agent for safe git worktree operations
- add smart-commit agent for intelligent git commit workflow
- add first true Claude Code agent for cross-platform validation
- **agents**: enhance test coverage agent with quality guidelines
- **metrics**: unified metrics system with improved tests
- **metrics**: implement unified metrics collection system
- implement test coverage enhancement agent for systematic improvement
- Complete documentation deployment system setup
- implement release automation agent for end-to-end release management
- **ci**: add version validation to CI pipeline

### Fix

- record cache metrics in ScopedCache to fix 0% hit rate issue
- skip Codecov uploads for Dependabot PRs to prevent CI failures
- add small delay in Windows test for file system sync
- move psutil from dev to main dependencies
- replace DIY atomic operations with filelock for cross-platform compatibility
- implement atomic file operations for Windows compatibility
- resolve defaultdict serialization issue in unified metrics
- properly preserve async functions in fallback decorator
- Make unified metrics import optional to fix CI failures
- Add Windows support for file locking in unified metrics
- **tests**: use sys.executable for Windows CLI test compatibility
- **tests**: handle stderr being None on Windows in CLI test
- **release-automation**: resolve Windows Unicode encoding issues
- **release-automation**: preserve indentation in commitizen version updates
- Properly configure uv virtual environment for docs build
- Remove problematic plugin autosummary entries from docs
- Add --system flag for uv pip install in documentation workflow
- Merge main and update deprecated actions/upload-artifact
- Move docs deployment workflow to correct location
- Update deprecated actions/upload-artifact to v4
- **dogfooding**: implement MCP usage tracking integration
- replace Unicode emojis with ASCII markers for Windows compatibility
- use manual TOML parsing for Python 3.10 compatibility
- improve release process and add worktree safety (issues #162-#165)

## [0.1.0] - 2025-08-24

### Added

- Initial release of PyEye Server
- Core navigation tools (find_symbol, goto_definition, find_references)
- Multi-project support with LRU caching
- Namespace package resolution across repositories
- File watching with automatic cache updates
- Configuration system (files, env vars, auto-discovery)
- Plugin architecture for framework-specific intelligence
- Django plugin with model/view/URL analysis
- Pydantic plugin with model schema extraction
- Flask plugin with route/blueprint/template analysis
- Module and package analysis tools
- Circular dependency detection
- Connection pooling for optimized multi-project workflows
- Comprehensive test suite
- Pre-commit hooks for code quality
- Documentation and examples

### Fixed

- Author and copyright information corrected

### Generated commit log

Commit subjects generated by commitizen at the time; kept for history.

#### Feat

- Update dev workflow to use PAT for branch protection bypass
- Implement development versioning strategy
- Implement automated release workflow
- **dogfooding**: add complete automation for metrics tracking (fixes #138)
- **dogfooding**: implement metrics tracking for MCP usage (fixes #135)
- **guidelines**: add automated checks and documentation to prevent CI failures
- **scope**: implement smart defaults and performance optimizations for namespace packages
- **plugins**: Add namespace package support to all plugin classes
- implement MCP-first dogfooding workflow for development
- Add scope parameter support to 6 core analyzer methods
- Implement core infrastructure for namespace-aware file operations
- Add find_subclasses tool for general inheritance tracking
- Add comprehensive performance monitoring and metrics collection
- **security**: Enable Dependabot for automated dependency updates
- Add configurable performance settings via environment variables
- add re-export tracking to find_symbol tool
- Add module/package listing and dependency analysis tools
- Add workflow_dispatch trigger to CI workflow
- Add coverage percentage badge to README
- Add comprehensive error handling with custom exception hierarchy (#21)
- Add comprehensive input validation and sanitization
- Add CI pipeline status badges to README
- Add comprehensive pre-commit hooks and achieve 100% compliance (#8)
- Add comprehensive pre-commit hooks and achieve 100% compliance
- Add comprehensive pre-commit hooks and achieve 100% compliance

#### Fix

- correct changelog generation in release workflow
- disable coverage requirement for version consistency tests in release workflow
- critical syntax error in release workflow
- Update workflow to use DEV_TOKEN instead of ADMIN_PAT
- Simplify dev version workflow for admin bypass
- Fix dev version workflow coverage issue and cleanup test
- Add Python 3.10 compatibility for TOML parsing in tests
- Version synchronization across package files
- resolve find_imports performance and namespace handling issues
- restore default scope to 'all' for backward compatibility
- optimize find_imports performance with ripgrep pre-filtering
- Fix settings import issue causing connection pooling tests to fail
- Address pre-commit hook failures
- Handle PosixPath in get_call_hierarchy errors
- Use as_posix() instead of str() for cross-platform compatibility
- Handle PosixPath serialization in error messages
- ruff linting issues in tests
- synchronize formatter versions and resolve CI failures
- resolve CI failures - black formatting and Windows path tests
- **test**: use as_posix() for cross-platform path comparison in test_list_packages_single_package
- disable cross-platform path pre-commit hook by default
- resolve cross-platform path violations across entire codebase
- **tests**: resolve Windows compatibility issues in test_automation.py
- **scope**: resolve cross-platform path handling and CI performance issues
- **django**: Add scope parameter support and fix duplicate detection
- Update Django plugin tests to use async/await
- specify UTF-8 encoding for Windows compatibility in tests
- simplify dogfooding tests to avoid async execution issues in CI
- update dogfooding tests to handle CI environment differences
- Re-enable test_goto_definition_not_found with proper mocking
- Use POSIX path format for cross-platform template names
- Make tests Windows-compatible
- Resolve paths in tests to handle symlinks and short names on Windows/macOS
- Make decorators async-aware to fix MCP coroutine issue
- Update codecov-action parameter from 'file' to 'files' for v5 compatibility
- Remove test docs file
- **ci**: Add dummy success jobs for docs-only PRs
- replace missed hardcoded assertion with threshold function
- make performance tests more tolerant on CI environments
- add Windows CI exception for flaky performance test
- Make timing-based tests more reliable across platforms
- Move temp_project fixture to module level for all test classes
- Fix flaky cache memory efficiency test
- add pull-requests read permission for paths-filter action
- make performance benchmark test tolerant of CI timing variance
- increase wait time for macOS in flaky debounce test
- update test to use GranularCache instead of ProjectCache
- Make path validation tests cross-platform
- Correct CI workflow syntax for conditional jobs
- correct CI badge URL in README
- Update coverage target to 75% and fix flaky macOS test
- update tests for re-export feature changes
- add company affiliation to author and copyright information
- correct author name and email information
- Prevent infinite recursion in circular dependency detection
- Fix Windows path separators and remove unnecessary type ignores
- Add token to Codecov badge for private repository
- Use Codecov's native badge format
- Add CODECOV_TOKEN to CI workflow
- Also mock watcher in test_cross_repository_import_resolution
- Resolve macOS-specific test failure in multi-project workflow (#24)
- Replace environment variable configuration with override files (#19)
- Cross-platform path resolution issues
- Allow legitimate relative paths in PathValidator while maintaining security
- Remove deprecated safety check and fix mypy CI issues
- Update CI workflow to use pyproject.toml for uv cache

#### Refactor

- use as_posix() for all file paths in API responses
- Replace print statements with logging in settings.py
- Move Jedi methods from server to JediAnalyzer

#### Perf

- Implement connection pooling for multiple projects
- implement smart cache invalidation for 2-3x performance improvement
- Implement smart cache invalidation for 2-3x performance improvement
- Implement async file operations for non-blocking I/O
- Add performance benchmarking suite with baseline measurements
