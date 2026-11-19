"""Main MCP server implementation for PyEye."""

import functools
import json
import logging
import typing
from collections.abc import Callable, Collection
from glob import glob
from inspect import (
    Parameter as _Parameter,
    isawaitable as _isawaitable,
    signature as _signature,  # `inspect` is shadowed by the MCP tool below
)
from pathlib import Path
from typing import Any, NamedTuple

from mcp.server.mcpserver import MCPServer

from ..analyzers.jedi_analyzer import JediAnalyzer
from ..canonicalization import invalidate_re_exports
from ..config import ProjectConfig, add_unsaved, clear_unsaved, has_unsaved
from ..constants import CONFIG_FILE
from ..docs_facts.describe import described, fill
from ..environment import discover as discover_environment
from ..exceptions import ValidationError
from ..metrics import metrics
from ..metrics_hook import track_mcp_operation
from ..path_utils import absolute_path, normalize_path, path_to_key, paths_equal, respell_paths
from ..plugins import handles as plugin_handles
from ..plugins.base import AnalyzerPlugin, Scope
from ..plugins.django import DjangoPlugin
from ..plugins.flask import FlaskPlugin
from ..plugins.pydantic import PydanticPlugin
from ..project_manager import get_project_manager
from ..scope_utils import SmartScopeResolver
from ..settings import settings
from ..validation import PathValidator, validate_mcp_inputs
from . import meta
from .jedi_worker import on_jedi_worker
from .operations.expand import expand as _expand_impl
from .operations.inspect import inspect as _inspect_impl
from .operations.outline import outline as _outline_impl
from .operations.resolve import (
    resolve as _resolve_impl,
    resolve_at as _resolve_at_impl,
)
from .operations.trace import trace as _trace_impl
from .tool_errors import tool_errors

# Logger — configured by __main__.py or caller; fallback to basic stderr.
logger = logging.getLogger(__name__)

# Initialize the MCP server.  The instructions block carries an in-band pointer
# to where pyeye bugs are reported (#458), so it is always in the agent's context.
# Keyword arguments only after `name`: MCPServer's second positional is `title`,
# so a positional instructions string would silently become the title (#538).
# mcp 2.x reports an empty server version unless one is passed.
mcp = MCPServer("PyEye", instructions=meta.server_instructions(), version=meta.version())

# Global plugin registry
_plugins: list[Any] = []
PLUGINS = _plugins  # Expose for testing
#: The project ``initialize_plugins`` ran for.  Plugin tools are bound to it, so
#: ``configure_packages`` re-detects frameworks only there (#659).
_startup_root: Path | None = None
#: The scope resolver plugin tools were registered with, reused at runtime (#659).
_startup_resolver: SmartScopeResolver | None = None
#: Every plugin tool name registered so far; runtime registration is add-only.
_registered_plugin_tools: set[str] = set()

# Module-level exports for testing
project_manager = None  # Will be initialized lazily
project_config = None  # Will be initialized lazily


def _for_caller(result: Any, project_path: str) -> dict[str, Any]:
    """*result* with every in-project file path in the caller's spelling (#717).

    The analyzer is built from the resolved root (#603: one analyzer per
    directory, whatever spelling reached it first), and Jedi reports files
    resolved. An agent that opened a symlinked ``project_path`` must still get
    paths under the root it gave, or it can't match them to its own paths or
    its sandbox's allowed directories.
    """
    return dict(respell_paths(dict(result), [absolute_path(project_path)]))


def get_analyzer(project_path: str = ".") -> JediAnalyzer:
    """Get or create a JediAnalyzer for the given project path.

    This is a helper function that uses ProjectManager to create
    a properly configured analyzer with namespace and package support.
    """
    # Use the project manager to get a configured analyzer
    manager = get_project_manager()
    return manager.get_analyzer(project_path)


def initialize_plugins(project_path: str = ".") -> None:
    """Initialize and activate framework-specific plugins for the project.

    Scans the project for framework indicators and activates appropriate plugins
    that provide specialized analysis tools. Currently supports Pydantic, Django,
    and Flask frameworks.

    Args:
        project_path: Root directory path of the project to analyze

    Note:
        Plugin activation is automatic based on project detection. Failed plugin
        initialization does not prevent server startup - plugins are optional.

    Example:
        The plugin system will automatically detect frameworks:
        - Pydantic: Looks for BaseModel imports
        - Django: Checks for Django imports and settings.py
        - Flask: Scans for Flask app creation patterns
    """
    global _startup_root, _startup_resolver
    # Clear in place: PLUGINS aliases this list, and rebinding it left PLUGINS
    # pointing at the old one (#627).
    _plugins.clear()
    _registered_plugin_tools.clear()
    _startup_root = Path(project_path)

    # Load configuration for namespace support
    config = ProjectConfig(project_path)

    # Try to activate each plugin
    for plugin_class in _PLUGIN_CLASSES:
        plugin = _activate_if_detected(plugin_class, project_path, config)
        if plugin is not None:
            _plugins.append(plugin)

    # Plugin tools called without ``scope`` resolve it through scope_defaults
    # (#559). Report configured keys that can't apply instead of ignoring them.
    resolver = SmartScopeResolver(config)
    _startup_resolver = resolver
    ignored = resolver.ignored_method_keys(all_plugin_tool_names(project_path))
    if ignored:
        logger.warning(
            "Ignoring scope_defaults.methods keys that aren't plugin tool names: %s. "
            "Keys must be MCP tool names such as find_pydantic_models (#559).",
            ", ".join(ignored),
        )

    # Outside the per-plugin try: a duplicate name is a bug in the declared names,
    # not an optional plugin failing to load, so it must not be swallowed.
    _registered_plugin_tools.update(register_plugin_tools(mcp, _plugins, resolver))


def _activate_if_detected(
    plugin_class: type[AnalyzerPlugin], project_path: str, config: ProjectConfig
) -> AnalyzerPlugin | None:
    """The configured plugin if its framework is used, else ``None`` (#659).

    Detection covers the project root AND every configured package and namespace
    path, so a framework used only in a configured package activates, at startup
    and after ``configure_packages`` alike.  A detector failure is logged and the
    plugin skipped: plugins are optional, so it must not stop the server, but it
    is a bug, not "framework absent" (since #637 ``detect()`` raises on anything
    but an unreadable file), so it is reported with its traceback.
    """
    try:
        plugin = plugin_class(project_path)
        detected = plugin.detect() or any(
            plugin_class(root).detect()
            for root in _detection_roots(config)
            if not paths_equal(root, project_path)
        )
        if not detected:
            return None
        _apply_plugin_paths(plugin, config)
        logger.info(f"Activated {plugin.name()} plugin with namespace support")
        return plugin
    except Exception:
        logger.exception(f"Failed to load plugin {plugin_class.__name__}")
        return None


def _detection_roots(config: ProjectConfig) -> list[str]:
    """The configured package and namespace directories a framework may live in."""
    roots = list(config.get_package_paths())
    for ns_paths in config.get_namespaces().values():
        roots.extend(ns_paths)
    return [root for root in roots if Path(root).is_dir()]


def redetect_plugins(project_path: str, config: ProjectConfig) -> list[str]:
    """Activate plugins whose framework a new layout brings in; return their names (#659).

    Runs ``detect()`` (root and configured paths) for each plugin class not yet
    active, and registers ONLY the new plugins' tools, through the same
    decorator stack as at startup.  Add-only: nothing already registered is
    unregistered or renamed.  No ``tools/list_changed`` is sent (#770); a client
    can call the new tools by name, and the caller reports the names.
    """
    active = {type(plugin) for plugin in _plugins}
    new = [
        plugin
        for plugin_class in _PLUGIN_CLASSES
        if plugin_class not in active
        for plugin in [_activate_if_detected(plugin_class, project_path, config)]
        if plugin is not None
    ]
    if not new:
        return []
    names = register_plugin_tools(
        mcp, new, _startup_resolver, already_registered=_registered_plugin_tools
    )
    _registered_plugin_tools.update(names)
    _plugins.extend(new)
    return [plugin.name() for plugin in new]


def _apply_plugin_paths(plugin: AnalyzerPlugin, config: ProjectConfig) -> None:
    """Give *plugin* the package and namespace paths from *config*.

    Shared by ``initialize_plugins`` and ``configure_packages`` (#618), so a
    reconfigured project's plugins see the same paths a restart would give them.
    """
    from pathlib import Path

    plugin.set_additional_paths([Path(p) for p in config.get_package_paths()])
    plugin.set_namespace_paths(config.get_namespaces())
    plugin.set_standalone_paths(config.get_standalone_paths())
    # Cleared first, so a check that raises leaves "not measured", never the
    # previous list or a [] that nothing measured (#898).
    plugin.set_rejected_paths(None)
    plugin.set_rejected_paths(config.rejected_paths())


_PLUGIN_CLASSES: tuple[type[AnalyzerPlugin], ...] = (PydanticPlugin, DjangoPlugin, FlaskPlugin)


def all_plugin_tool_names(project_path: str) -> set[str]:
    """Every tool name any plugin declares, whether or not it is active here."""
    names: set[str] = set()
    for plugin_class in _PLUGIN_CLASSES:
        names.update(plugin_class(project_path).register_tools())
    return names


#: Appended to every plugin tool's description (#665).
PLUGIN_PROJECT_PATH_NOTE = """

Each record also carries ``scope`` (project or external) and an absolute
``location`` (#627).  A record that names a symbol carries its canonical
``handle``, ready for ``inspect`` or ``expand``, or ``unresolved``
(``{reason, detail}``) when it can't be placed.

``project_path`` selects the project to analyse; omitted, it is the project
the server started in, exactly as before.  Plugin tools run against the given project even if its
framework wasn't auto-detected there; an empty result means the scan found
none.  A ``project_path`` that doesn't exist is an MCP tool error.

``envelope`` (default false): when true, the result is wrapped as
``{scope, searched, unsearched_scopes, rejected_paths, results}``, so a caller
can see which scopes were searched (#594).  ``unsearched_scopes`` lists the
configured scopes that were not, then any ``package:<path>`` given whose
directory doesn't exist (#842); a relative ``package:`` path is relative to
``project_path``.  ``rejected_paths`` lists each config entry the path check
refused, as ``{scope, path, reason: "rejected_path", detail}`` (``[]`` when
none); its scope is always in ``unsearched_scopes`` (#898).  It is absent only
when the check couldn't complete (a config file that failed to load)."""


class _PluginContext(NamedTuple):
    """A plugin instance and the scope resolver for one project (#665)."""

    plugin: AnalyzerPlugin
    resolver: SmartScopeResolver | None


def _build_plugin_context(plugin_class: type[AnalyzerPlugin], project_path: str) -> _PluginContext:
    """A fresh plugin for *project_path*, configured from that project alone (#665).

    Not gated on ``detect()`` (the #665 decision): a plugin tool asked about a
    project runs its scan there, so ``[]`` is a measured empty, never a refusal
    based on a heuristic.  Its package, namespace and standalone paths and its
    ``scope_defaults`` all come from the project's own config, so nothing leaks
    from the startup project or from another project.
    """
    config = ProjectConfig(project_path)
    plugin = plugin_class(project_path)
    _apply_plugin_paths(plugin, config)
    return _PluginContext(plugin, SmartScopeResolver(config))


def _plugin_context_for(
    plugin: AnalyzerPlugin, resolver: SmartScopeResolver | None, project_path: str | None
) -> _PluginContext:
    """The plugin and resolver to answer a call about *project_path* (#665).

    No ``project_path``, or the registered plugin's own project, keeps the
    registered instance (and its resolver), so the default call is unchanged.
    Any other project gets its own, cached in ``ProjectManager`` beside its
    analyzer.  A registration without a resolver (tests) stays without one.
    """
    if project_path is None or paths_equal(project_path, plugin.project_path):
        return _PluginContext(plugin, resolver)
    context: _PluginContext = get_project_manager().get_plugin_context(
        project_path,
        type(plugin),
        lambda path: _build_plugin_context(type(plugin), path),
    )
    if resolver is None:
        return _PluginContext(context.plugin, None)
    return context


def reapply_plugin_paths(project_path: str | Path, config: ProjectConfig) -> None:
    """Give *project_path*'s plugins the paths from *config* (#618, #665).

    The startup project's active plugins are updated in place.  Plugins built
    for a per-call ``project_path`` are dropped with the project's analyzer by
    ``invalidate_analyzer``, so the next call rebuilds them from the new config.
    """
    for plugin in _plugins:
        if paths_equal(plugin.project_path, project_path):
            _apply_plugin_paths(plugin, config)


def _plugin_tool(
    tool_name: str,
    func: Callable[..., Any],
    plugin: AnalyzerPlugin,
    resolver: SmartScopeResolver | None,
) -> Callable[..., Any]:
    """Wrap a plugin tool with the shared ``scope`` default and the opt-in ``envelope``.

    The MCP schema is built from the returned callable's signature:

    - ``scope`` becomes ``Scope | None = None`` when ``resolver`` is given (#559). A
      call without it gets ``resolver.plugin_tool_default(tool_name)``, an explicit
      ``scope`` always wins, and ``scope_aliases`` are expanded either way.
    - ``envelope: bool = False`` is appended (#594). When true, the tool returns
      ``{scope, searched, unsearched_scopes, rejected_paths, results}``: ``scope``
      is the scope as requested or defaulted (before alias expansion), ``searched``
      and ``unsearched_scopes`` come from ``AnalyzerPlugin.describe_scope``,
      ``rejected_paths`` from ``AnalyzerPlugin.rejected_paths`` (#898), and
      ``results`` is exactly what the tool returns without the envelope. When
      false, the return value is passed through untouched, so the default wire
      format is unchanged (making the envelope the default is #644).

    Every other parameter is unchanged.
    """
    signature = _signature(func)
    if "scope" not in signature.parameters:
        raise TypeError(f"Plugin tool {tool_name!r} has no 'scope' parameter")
    if "envelope" in signature.parameters:
        raise TypeError(f"Plugin tool {tool_name!r} already declares 'envelope'")
    if "project_path" in signature.parameters:
        raise TypeError(f"Plugin tool {tool_name!r} already declares 'project_path'")
    hints = typing.get_type_hints(func)

    @functools.wraps(func)
    async def wrapper(
        *args: Any, envelope: bool = False, project_path: str | None = None, **kwargs: Any
    ) -> Any:
        # #665: answer about the project the caller named.  get_analyzer first, so
        # a project_path that doesn't exist is the core tools' tool error
        # (ProjectNotFoundError), never a scan of nothing reported as [].
        if project_path is not None:
            get_analyzer(project_path)
        target, target_resolver = _plugin_context_for(plugin, resolver, project_path)
        target_func = func if target is plugin else target.register_tools()[tool_name]
        bound = signature.bind_partial(*args, **kwargs)
        if target_resolver is not None:
            if bound.arguments.get("scope") is None:
                bound.arguments["scope"] = target_resolver.plugin_tool_default(tool_name)
        else:
            bound.apply_defaults()
        requested = bound.arguments["scope"]
        if target_resolver is not None:
            # Plugins resolve only main/all/packages/namespace:/package:, so an
            # alias (from config or the caller) would otherwise search nothing.
            bound.arguments["scope"] = target_resolver.resolve_aliases(requested)
        if tool_name in _MODEL_LOOKUP_TOOLS:
            # Select the model in one place, with the shared shapes (#627 slice B).
            result = await _lookup_model(
                tool_name, target, bound.arguments["model_name"], bound.arguments["scope"]
            )
        else:
            result = target_func(*bound.args, **bound.kwargs)
            if _isawaitable(result):
                result = await result
            # Canonical handles, scope and absolute locations on every record (#627),
            # before the envelope, so the bare list and `results` carry the same.
            result = plugin_handles.enrich(
                tool_name, result, lambda: get_analyzer(target.project_path.as_posix())
            )
        # The caller's spelling of the project root, as the core tools give it
        # (#717): enrich's locations come from the analyzer, which is resolved.
        # Before the envelope, so the bare list and `results` carry the same.
        result = respell_paths(result, [absolute_path(project_path or target.project_path)])
        if not envelope:
            return result
        searched, unsearched = target.describe_scope(bound.arguments["scope"])
        wrapped: dict[str, Any] = {
            "scope": requested,
            "searched": searched,
            "unsearched_scopes": unsearched,
        }
        # Present whenever the check completed: [] is a measured "none refused".
        # Absent when it couldn't (a config that failed to load), never a []
        # for a check that didn't finish (#898, #568).
        if target.rejected_paths is not None:
            wrapped["rejected_paths"] = target.rejected_paths
        wrapped["results"] = result
        # A plugin's own keys follow (#921: find_pydantic_models' unplaced_classes).
        extras = await target.envelope_extras(tool_name, dict(bound.arguments))
        wrapped.update(respell_paths(extras, [absolute_path(project_path or target.project_path)]))
        return wrapped

    # Keep the tool's own return type, so the SDK builds the same structured
    # output as before when ``envelope`` is false; the union admits the envelope.
    return_type = hints.get("return", Any) | dict[str, Any]
    envelope_param = _Parameter("envelope", _Parameter.KEYWORD_ONLY, default=False, annotation=bool)
    project_path_param = _Parameter(
        "project_path", _Parameter.KEYWORD_ONLY, default=None, annotation=str | None
    )
    parameters = [
        (
            p.replace(default=None, annotation=Scope | None)
            if p.name == "scope" and resolver is not None
            else p
        )
        for p in signature.parameters.values()
    ]
    wrapper.__signature__ = signature.replace(  # type: ignore[attr-defined]
        parameters=[*parameters, envelope_param, project_path_param],
        return_annotation=return_type,
    )
    annotations = {
        **hints,
        "envelope": bool,
        "project_path": str | None,
        "return": return_type,
    }
    if resolver is not None:
        annotations["scope"] = Scope | None
    wrapper.__annotations__ = annotations
    del wrapper.__wrapped__  # the schema must come from the new signature
    # Fact slots are filled here, from the same extractors as the docs (#827).
    wrapper.__doc_template__ = func.__doc__ or ""  # type: ignore[attr-defined]
    wrapper.__doc__ = fill((func.__doc__ or "").rstrip()) + PLUGIN_PROJECT_PATH_NOTE
    return wrapper


#: Plugin tools that look a model up by ``model_name`` (#627 slice B).
_MODEL_LOOKUP_TOOLS: frozenset[str] = frozenset({"get_model_schema", "trace_model_inheritance"})
_SCOPE_ORDER = {"project": 0, "external": 1}


async def _lookup_model(tool_name: str, plugin: Any, model_name: str, scope: Any) -> dict[str, Any]:
    """Answer a model lookup: not found, ambiguous, or the one model (#627 slice B).

    The shapes are the primitives' own:

    - no match: the shared not-found shape (``not_found_for``), echoing
      ``model_name``;
    - several models of that name: resolve's ambiguous shape,
      ``{found: True, ambiguous: True, candidates}``, each candidate a
      ``{handle, kind, scope, location}`` sorted like resolve's;
    - one model: the plugin's answer for it, enriched (#627), plus ``found: True``.

    A dotted ``model_name`` is a handle. It is canonicalised by
    ``resolve_handle`` (so a re-export alias works) and matched against each
    model's handle, which is how a caller picks an ambiguous candidate. Nothing
    here builds a handle.
    """
    from ..resolver import Resolved, resolve_handle
    from .operations.not_found import not_found_for

    analyzer = get_analyzer(plugin.project_path.as_posix())
    models = await plugin.find_models(scope)
    plugin_handles.enrich("find_pydantic_models", models, lambda: analyzer)

    if "." in model_name:
        resolved = resolve_handle(model_name, analyzer)
        target = resolved.handle if isinstance(resolved, Resolved) else None
        matches = [m for m in models if target is not None and m.get("handle") == target]
    else:
        matches = [m for m in models if m.get("name") == model_name]

    if not matches:
        return not_found_for(tool_name, {"model_name": model_name})

    if len(matches) > 1:
        candidates = [
            {"handle": m["handle"], "kind": "class", "scope": m["scope"], "location": m["location"]}
            for m in matches
            if "handle" in m
        ]
        candidates.sort(
            key=lambda c: (
                _SCOPE_ORDER.get(c["scope"], 99),
                c["location"]["file"],
                c["location"].get("line_start", 0),
            )
        )
        return {"found": True, "ambiguous": True, "candidates": candidates}

    model = matches[0]
    if tool_name == "get_model_schema":
        answer = await plugin.schema_for(model)
    else:
        answer = await plugin.inheritance_for(model["name"], model, models, scope)
    plugin_handles.enrich(tool_name, answer, lambda: analyzer)
    return {"found": True, **answer}


def _wrap_like_core_tool(tool_name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Give a plugin tool the decorator stack every core tool has, in the same order (#627).

    Outermost first, as on ``resolve``:

    - ``tool_errors``: any exception becomes an MCP tool error (#626 slice C);
    - ``validate_mcp_inputs``: arguments it knows by name are validated;
    - ``metrics.measure`` and ``track_mcp_operation``, under the MCP tool name;
    - ``on_jedi_worker``: plugin tools build jedi.Scripts and share the
      analyzers' caches, so they run on the Jedi worker like the core tools (#650).
    """
    return tool_errors(
        validate_mcp_inputs(
            metrics.measure(tool_name)(track_mcp_operation(tool_name)(on_jedi_worker(func)))
        )
    )


def register_plugin_tools(
    server: MCPServer,
    plugins: list[AnalyzerPlugin],
    resolver: SmartScopeResolver | None = None,
    *,
    already_registered: Collection[str] = (),
) -> list[str]:
    """Register every plugin tool on ``server`` under the name its plugin declares.

    The ``register_tools()`` keys are the tool names. Registering by the
    function's ``__name__`` instead (the pre-#555 behaviour) made Django's
    ``find_models`` / ``find_views`` / ``find_templates`` collide with the
    Pydantic and Flask methods of the same name, and the SDK resolves a
    collision by keeping the first tool and logging a warning.

    Args:
        server: The MCP server to register on
        plugins: Activated plugins, in load order
        resolver: If given, ``scope`` defaults through ``scope_defaults`` when the
            caller omits it (#559). Every tool also gets the opt-in ``envelope``
            argument (#594); see :func:`_plugin_tool`.
        already_registered: Names registered by an earlier call (runtime
            re-detection, #659).  They are skipped, never re-registered, so
            registration is add-only.

    Returns:
        The registered tool names, in registration order

    Raises:
        ValueError: If two plugins declare the same tool name
    """
    registered: list[str] = []
    for plugin in plugins:
        for tool_name, tool_func in plugin.register_tools().items():
            if tool_name in already_registered:
                continue
            if tool_name in registered:
                raise ValueError(
                    f"Plugin {plugin.name()} declares tool {tool_name!r}, "
                    "which another plugin already registered"
                )
            server.tool(name=tool_name)(
                _wrap_like_core_tool(
                    tool_name, _plugin_tool(tool_name, tool_func, plugin, resolver)
                )
            )
            registered.append(tool_name)
    return registered


def filter_fields(
    data: dict[str, Any] | list[dict[str, Any]],
    fields: list[str] | None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Filter dictionary or list of dictionaries to include only specified fields.

    Args:
        data: Single dictionary or list of dictionaries to filter
        fields: List of field names to include, or None to return shallow copy

    Returns:
        Filtered dictionary or list of dictionaries

    Raises:
        ValueError: If fields is an empty list, or if any field is not valid
        TypeError: If data is not a dict or list of dicts, or if fields is not a list when provided
    """
    # Type validation for data
    if not isinstance(data, (dict, list)):
        raise TypeError(f"data must be a dict or list of dicts, got {type(data).__name__}")

    if isinstance(data, list):
        if not all(isinstance(item, dict) for item in data):
            raise TypeError("All items in list must be dictionaries")

    # If no fields specified, return shallow copy
    if fields is None:
        if isinstance(data, dict):
            return data.copy()
        else:
            return [item.copy() for item in data]

    # Type validation for fields
    if not isinstance(fields, list):
        raise TypeError(f"fields must be a list or None, got {type(fields).__name__}")

    # Validate fields is not empty
    if len(fields) == 0:
        raise ValueError("fields list cannot be empty")

    # Determine valid fields from data
    if isinstance(data, dict):
        valid_fields = list(data.keys())
    elif isinstance(data, list):
        # Empty list: no validation needed, just return empty list
        if len(data) == 0:
            return []
        # Non-empty list: validate against first item
        valid_fields = list(data[0].keys())
    else:
        valid_fields = []

    # Validate requested fields
    invalid_fields = [f for f in fields if f not in valid_fields]
    if invalid_fields:
        # Sort invalid fields for consistent error messages
        invalid_sorted = sorted(invalid_fields)
        # Format with single quotes
        invalid_str = ", ".join(f"'{f}'" for f in invalid_sorted)
        # Sort valid fields alphabetically, no quotes
        valid_sorted = ", ".join(sorted(valid_fields))
        raise ValueError(f"Invalid field(s): {invalid_str}. Valid fields are: {valid_sorted}")

    # Filter the data
    if isinstance(data, dict):
        # Single dictionary - include only fields that exist, preserve requested order
        return {k: data[k] for k in fields if k in data}
    else:
        # List of dictionaries - filter each one, skip missing fields
        return [{k: item[k] for k in fields if k in item} for item in data]


def _check_new_config_paths(
    config: ProjectConfig,
    packages: list[str] | None,
    namespaces: dict[str, list[str]] | None,
    standalone_dirs: list[str] | None,
) -> None:
    """Refuse a new config entry whose final form fails the path check (#856).

    Checked as the config will read it (:meth:`ProjectConfig._normalise_config_path`:
    ``~`` expanded, anchored on the project), on the project path the tool uses.

    Raises:
        ValidationError: Naming the first refused entry; nothing has been changed.
    """
    entries = [("packages", p) for p in packages or []]
    entries += [
        (f"namespaces[{ns!r}]", p) for ns, ps in (namespaces or {}).items() for p in ps or []
    ]
    entries += [("standalone_dirs", p) for p in standalone_dirs or []]
    for where, entry in entries:
        final = config._normalise_config_path(entry)
        try:
            for target in _config_entry_targets(entry, final):
                PathValidator.validate_scan_root(target, config.project_path)
        except ValidationError as error:
            raise ValidationError(
                f"Invalid path {entry!r} in {where}: {error}", parameter=where.split("[")[0]
            ) from error


def _unsaved_view(config: ProjectConfig, disk: ProjectConfig) -> dict[str, Any]:
    """The part of *config* that *disk* (the same project, unsaved entries left out) lacks (#953).

    Shaped like ``configure_packages``' own keys (``packages``, ``namespaces``,
    ``standalone.dirs``), each in the form that key reports, so a caller can
    compare field for field. ``[]`` / ``{}`` when nothing is unsaved.
    """
    # Compared as path_utils keys (#717): one spelling per path, whatever the platform.
    disk_packages = {path_to_key(p) for p in disk.get_package_paths()}
    disk_namespaces = {
        ns: [path_to_key(d) for d in dirs] for ns, dirs in disk.get_namespaces().items()
    }
    disk_dirs = {Path(d).as_posix() for d in disk.get_standalone_config().get("dirs", [])}
    namespaces = {
        ns: dirs
        for ns, dirs in config.get_namespaces().items()
        if [path_to_key(d) for d in dirs] != disk_namespaces.get(ns)
    }
    return {
        "packages": [p for p in config.get_package_paths() if path_to_key(p) not in disk_packages],
        "namespaces": namespaces,
        "standalone": {
            "dirs": [
                d
                for d in config.get_standalone_config().get("dirs", [])
                if Path(d).as_posix() not in disk_dirs
            ]
        },
    }


def _config_entry_targets(entry: str, final: str) -> list[str]:
    """What a config *entry* will reach, to check: the entry, or every glob match.

    A glob is checked by what it matches, never in pattern form: ``/e*`` would
    pass as a pattern and match ``/etc`` at use. A glob with ``..`` is refused
    outright: whether it escapes depends on matches that exist only later, and on
    lexical collapsing the config does by accident (#856 review).

    Deliberately wider than the config's expansion: ``*?[`` count as glob here,
    while ``ProjectConfig._expand_glob`` expands ``*`` only (#872), so a literal
    ``?`` or ``[`` in a path keeps its meaning. Checking an entry by its matches
    as well as itself is only ever stricter.

    Raises:
        ValidationError: For a glob entry containing ``..``.
    """
    if not any(ch in entry for ch in "*?["):
        return [final]
    if ".." in entry.replace("\\", "/").split("/"):
        raise ValidationError("a glob pattern may not contain '..'")
    return [final, *sorted(glob(final))]


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("configure_packages")
@track_mcp_operation("configure_packages")
@on_jedi_worker
def configure_packages(
    packages: list[str] | None = None,
    namespaces: dict[str, list[str]] | None = None,
    standalone_dirs: list[str] | None = None,
    save: bool = True,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Configure additional packages, namespaces, and standalone scripts for analysis.

    Args:
        packages: List of package paths to include
        namespaces: Namespace packages with their repo paths
        standalone_dirs: Directories containing standalone Python scripts.
            Every ``.py`` file under them is analysed.
        save: Save configuration to .pyeye.json, together with any entries this
            session's earlier unsaved calls added. False keeps this call's
            entries for the session only: unsaved calls accumulate until the
            server restarts or a save writes them; ``unsaved`` lists them (#953).
        project_path: Project root to configure (default: current directory)

    The call errors (an MCP tool error, not a response) only when it can't run:
    an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
    or an unreadable file.

    Framework plugins (#659): on the project the server started in, this also
    re-detects frameworks against the new layout.  A framework used only in a
    newly added package (e.g. Flask) activates, and its tools are registered
    immediately; the result's ``activated_plugins`` names them (``[]`` when none
    newly activated; absent for any other project, which isn't re-detected).
    The new tools are **callable by name right away**, even if your client
    doesn't refresh its tool list: no ``tools/list_changed`` notification is
    sent (#770).  Registration is add-only; nothing is ever removed.
    """
    from ..analyzers import project_graph
    from .operations import typeref

    # Load existing config for the project being configured (#618: was always ".")
    global project_config
    root = normalize_path(project_path)
    project_config = ProjectConfig(root.as_posix())
    config = project_config

    # Each new entry is checked in the form the config will use it (~ expanded,
    # anchored on the project, as normalised), BEFORE anything is changed or
    # saved: a refused entry is an error and nothing is written (#856 review).
    _check_new_config_paths(config, packages, namespaces, standalone_dirs)

    if save:
        # The loaded config already carries the session's unsaved entries
        # (#953): add this call's, and persist both, then forget the overlay.
        if packages:
            existing = config.config.setdefault("packages", [])
            have = {Path(p).as_posix() for p in existing}
            existing.extend(Path(p).as_posix() for p in packages if Path(p).as_posix() not in have)
        if namespaces:
            config.config.setdefault("namespaces", {}).update(
                {ns: [Path(p).as_posix() for p in paths] for ns, paths in namespaces.items()}
            )
        if standalone_dirs:
            if not isinstance(config.config.get("standalone"), dict):
                config.config["standalone"] = {}
            dirs = config.config["standalone"].setdefault("dirs", [])
            have = {Path(d).as_posix() for d in dirs}
            dirs.extend(
                Path(d).as_posix() for d in standalone_dirs if Path(d).as_posix() not in have
            )
        if packages or namespaces or standalone_dirs or has_unsaved(root):
            config.save_config()
            clear_unsaved(root)
    else:
        # Unsaved: kept for the session, so successive calls accumulate (#953).
        add_unsaved(root, packages, namespaces, standalone_dirs)
        project_config = config = ProjectConfig(root.as_posix())

    # Apply configuration to project manager
    manager = get_project_manager()
    all_paths = config.get_package_paths()

    if len(all_paths) > 1:
        # Configure with all paths
        manager.register_project(all_paths[0], all_paths[1:])

    # Configure namespaces
    for namespace, ns_paths in config.get_namespaces().items():
        manager.namespace_resolver.register_namespace(namespace, ns_paths, project=root)

    # Invalidate cached analyzers for all paths so the next get_analyzer call
    # rebuilds with the updated package paths, namespaces, and standalone
    # directories.  Multi-project / namespace scenarios can have stale
    # analyzers for secondary paths too.
    manager.invalidate_analyzer(root.as_posix())
    for path in all_paths:
        manager.invalidate_analyzer(path)

    # Drop the project's process-wide caches. Layout keying (#618) already keeps
    # a new layout from reading the old entries; this frees them and covers the
    # TypeRef cache, which is keyed on the root alone (#620).
    project_graph.invalidate(root.as_posix())
    typeref.invalidate_project(root)
    invalidate_re_exports(root)

    # Give this project's plugins the new paths (#618).  Per-call plugins (#665)
    # were dropped with the analyzer above and rebuild from the new config.
    reapply_plugin_paths(root, config)
    # Then re-detect on the startup project, whose tools plugins are bound to: a
    # framework used only in a newly added package activates now (#659).
    activated: list[str] | None = None
    if _startup_root is not None and paths_equal(root, _startup_root):
        activated = redetect_plugins(_startup_root.as_posix(), config)

    result: dict[str, Any] = {
        "packages": config.get_package_paths(),
        "namespaces": config.get_namespaces(),
        "standalone": config.get_standalone_config(),
        # Where third-party imports are read from (#993): always present.
        "environment": discover_environment(root, config.get_environment_setting()).as_response(),
    }
    # Entries the path check refused, skipped above; [] when none. Absent when
    # the check couldn't complete (a config that failed to load), never a []
    # for a check that didn't finish (#898).
    # What lives only in this session's overlay, in the response's own shape so
    # each field compares with its counterpart; empty when nothing is unsaved (#953).
    result["unsaved"] = _unsaved_view(config, ProjectConfig(root.as_posix(), include_unsaved=False))
    rejected = config.rejected_paths()
    if rejected is not None:
        result["rejected_paths"] = rejected
    result["config_file"] = (config.project_path / CONFIG_FILE).as_posix()
    # #659: present whenever re-detection ran (the startup project); [] when no
    # framework newly activated.  Their tools are callable by name at once.
    if activated is not None:
        result["activated_plugins"] = activated
    # Report config keys that are present but ignored rather than letting them
    # read as live (#513, #581). Absent — not [] — when there are none.
    warnings = []
    ignored = config.get_ignored_standalone_keys()
    if ignored:
        warnings.append(ProjectConfig.ignored_standalone_keys_message(ignored))
    ignored_top = config.get_ignored_top_level_keys()
    if ignored_top:
        warnings.append(ProjectConfig.ignored_top_level_keys_message(ignored_top))
    if warnings:
        result["warnings"] = warnings
    return result


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("resolve")
@track_mcp_operation("resolve")
@on_jedi_worker
async def resolve(
    identifier: str,
    project_path: str = ".",
    max_candidates: int | None = 50,
) -> dict[str, Any]:
    """Python: Resolve any identifier form to a canonical Handle.

    Accepts bare names, FQN dotted paths, re-exported public paths,
    file:line coordinates, or file paths. Returns the definition-site
    canonical handle along with kind and scope ("project" or "external").

    Args:
        identifier: The identifier to resolve. Forms supported:
            - Bare name: "Config". Modules and top-level definitions first;
              a method or class attribute ("load_settings") only if none
              match, so a top-level name hides same-named methods. Dunders
              ("__eq__") are never matched by bare name.
            - FQN: "a.b.c.Config"
            - Re-exported: "package.Config" (collapses to definition site)
            - File:line: "src/foo.py:42"
            - File only: "src/foo.py"
        project_path: Project root path (default: current directory)
        max_candidates: Most candidates an ambiguous result returns (default 50;
            ``None`` for all; see Returns).

    Returns:
        ResolveResult dict — one of:
        - Success: {"found": True, "handle": str, "kind": str, "scope": "project"|"external",
          "location": {...}} (the definition site, a pointer: no source content)
        - Ambiguous: {"found": True, "ambiguous": True, "candidates": [...]}
          At most ``max_candidates`` (default 50; ``None`` for all) candidates
          come back, in sorted order (#435).  When more match, the result also
          has ``truncated: true``, ``truncation_reasons: ["max_candidates"]``
          and ``total`` (how many matched); the three are absent otherwise.
        - Not found: {"found": False, "identifier": str, "reason": str, "detail": str}
          with reason "unresolved", "file_not_found" or "no_symbol_at_position".
          The identifier is echoed verbatim; it is never put in "handle".

        A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's TypedDict union to plain dict[str, Any]
    # to match this wrapper's declared return type. TypedDict instances are
    # already dicts at runtime; this is a mypy-compliance shallow copy.
    return _for_caller(
        await _resolve_impl(identifier, analyzer, max_candidates=max_candidates), project_path
    )


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("resolve_at")
@track_mcp_operation("resolve_at")
@on_jedi_worker
async def resolve_at(
    file: str,
    line: int,
    column: int,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Resolve a (file, line, column) position to a canonical Handle.

    Used when you have coordinates (from a stack trace, error report, or
    pasted excerpt) rather than a name. Returns the same shape as resolve().

    Args:
        file: Absolute or project-relative path to the source file.
        line: 1-indexed line number.
        column: 0-indexed column number. Pass 0 for the start of the line —
            this is valid; do not coerce to a default.
        project_path: Project root path (default: current directory)

    Returns:
        ResolveResult dict, the same success/ambiguous shapes as resolve(). Not found:
        {"found": False, "file": str, "line": int, "column": int, "reason": str,
        "detail": str}, echoing the arguments as given, with reason
        "file_not_found", "no_symbol_at_position" or "unresolved".

        A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
    """
    analyzer = get_analyzer(project_path)
    # See note on resolve() above re: dict() widening.
    return _for_caller(await _resolve_at_impl(file, line, column, analyzer), project_path)


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("inspect")
@track_mcp_operation("inspect")
@on_jedi_worker
async def inspect(
    handle: str,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Inspect a canonical handle and return a structural Node.

    The "what is this?" operation. Returns the symbol's kind, location,
    signature, docstring, edge counts, and kind-dependent fields. Cheap by
    default — no source content, no exhaustive enumerations.

    Args:
        handle: Canonical Python dotted-name string (from resolve/resolve_at).
        project_path: Project root path (default: current directory)

    Returns:
        Node dict with ``found: True``, universal fields (handle, kind, scope,
        location, docstring, edge_counts) plus kind-dependent fields.
        ``edge_counts`` counts only the edges cheap to measure from the
        definition itself.  An edge it didn't measure, including one that ran
        past its time budget, is ABSENT, never ``0``.  Follow an edge with
        ``expand`` to measure it.
        - class: signature (constructor), superclasses (list of Handle strings;
          omitted when the class's file can't be parsed, never a measured ``[]``)
        - function/method: signature, parameters, return_type?, is_async, is_classmethod, is_staticmethod
        - module: is_package, package?
        - attribute/property/variable/enum_member: type?, default? (simple literals only).
          A class-body binding is ``attribute``; a member of an ``enum.Enum``
          subclass is ``enum_member`` (its ``default`` is the member's value).
        - non-module kinds: a re-export list, **deprecated** (removed in v3.0);
          follow the re-export edge with ``expand`` instead.  It is absent when
          it couldn't be measured, never an empty list standing in for "unknown".

        If the handle does not resolve:
        ``{"found": False, "handle": str, "reason": "unresolved", "detail": str}``
        — no node fields.  Call resolve() on the name to get a canonical handle.
        A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
    """
    analyzer = get_analyzer(project_path)
    # See note on resolve() above re: dict() widening.
    return _for_caller(await _inspect_impl(handle, analyzer), project_path)


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("expand")
@track_mcp_operation("expand")
@on_jedi_worker
@described
async def expand(
    handle: str,
    edge: str,
    project_path: str = ".",
    max_stubs: int | None = 200,
) -> dict[str, Any]:
    """Python: Expand one outbound edge from a canonical handle (single hop).

    The traversal primitive that walks ONE edge from a source handle and
    returns adjacent symbols as lightweight Stubs.  Use resolve()/inspect()
    first to obtain a canonical handle, then call expand() to traverse.

    Supported edges (the complete static/outbound set):
      - ``members``  — class/module → direct members (attributes, methods, nested
        classes).  ``stubs: []`` means the class/module was found but has no
        members; that is NOT the same as unsupported.  Measured scope: a class's
        members are its class-body definitions; instance attributes assigned in
        methods (``self.x = ...``) are NOT measured.  A module's members are its
        module-level definitions.  Static-surface ceiling:
        <<fact:edge.members:ceiling>>.  For example, a Django ``Model`` shows
        none of its metaclass-injected ``_meta`` / ``objects`` / ``DoesNotExist``.
        A name missing from ``stubs`` is unknown outside that scope, not absent.
      - ``callees``  — function/method → forward static call targets.  Includes
        project symbols and stdlib/external symbols reachable via Jedi's goto.
        Dynamic calls (un-inferable parameters, ``getattr``, lambdas, etc.) are
        counted in ``unresolved_call_sites`` rather than invented.  Ceiling:
        <<fact:edge.callees:ceiling>>.
      - ``imported_by``  — module → the project modules that import it (module
        Stubs), computed by static AST import-graph reversal (no reverse symbol
        search).  Covers importers anywhere in the project including tests and
        standalone scripts, and imports anywhere in a file: guarded, and inside
        a function or class body too (a lazy import is still a dependency).
        So it is NOT the exact inverse of ``imports``: if ``imports(M)`` shows
        module ``B``, then ``M`` is in ``imported_by(B)``, but a function-body
        importer appears only here.  A file that imports it but has no module
        name (``my-script.py``, ``tools-dir/x.py``) can't be a stub; it is listed
        in ``unresolved_importers`` (#668), never dropped; a file the server's
        Python can't parse is listed in ``unparseable_files`` (#729).  Non-module handles
        return the unsupported branch with ``reason: "not_applicable"`` (#626).
        Ceiling: <<fact:edge.imported_by:ceiling>>.
      - ``re_exports``  — symbol → the public MODULES that re-export it (#393).
        Each stub is the re-exporting module; its ``bindings`` lists the public
        dotted paths it provides (``["pkg.Foo"]``). Public means a package
        ``__init__``, a name in ``__all__``, or a public module importing from
        a ``_private`` one (#712); plain internal imports are ``imported_by``'s.
        Package files the server's Python can't parse are listed in
        ``unparseable_files``, and the rest are still reported.  Module handles
        return ``not_applicable``.  Not in ``inspect``'s ``edge_counts``;
        ``inspect``'s ``re_exports`` field is deprecated in its favour.  Ceiling:
        <<fact:edge.re_exports:ceiling>>.
      - ``subclasses``  — class → the project classes that **directly** subclass
        it (class Stubs), computed by an AST class-graph walk + forward ``goto``
        (no reverse symbol search).  Returns the DIRECT (depth-1) subclasses only
        (#422) — one hop, symmetric with ``superclasses``; the full transitive
        closure is served by ``trace(follow=["subclasses"], max_depth=k,
        max_nodes=N)``, which carries the cap + ``truncated`` contract.  A class
        result includes a static ``transitive_hint`` field pointing to that trace
        route.  ``subclasses`` is an expand-only edge: ``inspect`` does NOT
        measure it (dropped in #392); a cheap direct count is gated on the Pyright
        reference backend / class-graph cache (#333/#397), because even the direct
        count is a reverse query needing the same project-wide scan as
        ``callers``/``references``.  ``stubs: []`` means the class has no project
        subclasses (measured-none).  A non-class handle returns the unsupported
        branch with ``reason: "not_applicable"`` (#626).  Static-surface ceiling:
        <<fact:edge.subclasses:ceiling>>.
      - ``superclasses``  — class → its base classes (class Stubs), resolved by
        Jedi from the class definition (no reverse search).  A non-class handle
        returns the unsupported branch with ``reason: "not_applicable"``.
        Ceiling: <<fact:edge.superclasses:ceiling>>.
      - ``imports``  — module → the symbols/modules it imports (Stubs), computed
        by static AST + forward ``goto``.  Counts the imports that bind a
        module-scope name (guarded ones included; imports inside a function or
        class body are not), and reports each imported symbol at its canonical
        definition site.  ``stubs: []`` is measured-none.  A
        non-module handle returns the unsupported branch with
        ``reason: "not_applicable"`` (mirrors ``imported_by``).  Ceiling:
        <<fact:edge.imports:ceiling>>.
      - ``enclosing_scope``  — symbol → its immediate lexical enclosing scope
        (the inverse of ``members``), resolved by Jedi ``parent()``: a method →
        its class, a nested def/class → its enclosing def/class, a top-level
        def/class/variable → its module.  At most ONE Stub.  A module returns
        the unsupported branch with ``reason: "not_applicable"``: a module has no
        enclosing lexical scope (packages are not lexical scopes).
      - ``submodules``  — package → its DIRECT child modules and subpackages
        (module Stubs), from a directory scan with no Jedi lookup; PEP 420
        namespace subpackages included.  A plain (non-package) module has none:
        ``stubs: []``.  A non-module handle returns the unsupported branch with
        ``reason: "not_applicable"``.  Ceiling: <<fact:edge.submodules:ceiling>>.

    Unsupported edges return the unsupported branch (never raise):
      - Inbound/reference edges (<<fact:edges.deferred>>) require the Pyright
        reference backend (#333) and return
        ``unsupported: true, reason: "deferred_reference_backend"``.
      - Wrong-kind handles (an edge that doesn't apply to the handle's kind, e.g.
        ``imported_by`` on a class or ``members`` on a function) return the
        unsupported branch with ``reason: "not_applicable"`` (#626). Which kinds
        each edge applies to is one table, ``edges.EDGE_APPLIES_TO``:
        <<fact:edges.implemented:applies_to>>.
      - A source whose own file can't be parsed by the server's Python (e.g.
        code using newer syntax) returns the unsupported branch with
        ``reason: "unparseable"`` (#703), never ``stubs: []``: its edges were
        not measured.  ``detail`` names the file and line; Read the file.
      - A definition declared only in a stub (``.pyi``: a project stub-only
        module, typeshed, a stub-only package) has no body, so its body edge
        (``callees``) returns the unsupported branch with ``reason:
        "stub_declaration"`` (#933): its calls weren't measured, never
        ``stubs: []``.  Its declaration edges (members, superclasses, imports,
        ...) still apply.
      - Unrecognised edge names return ``reason: "unknown_edge"``.

    Response shape — discriminated union.  ``found`` is always present.

    *Source not found* (``found: False`` — the handle does not resolve, checked
    before the edge, so this wins over any unsupported edge):
    ::

        { "found": False, "handle": str, "edge": str,
          "reason": "unresolved",
          "detail": str }               # next step: call resolve() on the name

    *Supported branch* (``found: True``, ``"unsupported"`` key absent):
    ::

        { "found":  True,
          "source": str,                 # canonical source handle
          "edge":   str,
          "stubs":  [Stub, ...],         # [] == measured-empty (NOT unsupported)
          "unresolved_call_sites": int,  # callees ONLY; absent otherwise
          "unresolved_imports": [target, ...],  # imports ONLY (#494); [] when all resolved
          "unresolved_superclasses": [text, ...],  # superclasses ONLY (#624); [] when all resolved
          "unresolved_importers": [file, ...],  # imported_by ONLY (#668); [] when all named
          "unparseable_files": [file, ...],  # <<fact:edges.unparseable>> ONLY (#729); [] when all parsed
          "transitive_hint": str,        # subclasses ONLY: the trace call for the full tree
          "truncated": True,             # these three only when max_stubs cut the list;
          "truncation_reasons": ["max_stubs"],  # absent otherwise
          "total": int,                  # the edge's full size
          "ceiling": str }               # #417 — the scope the list is complete over

    ``ceiling`` names the edge's static-surface ceiling (#417), as each edge's
    entry above states it, and is absent only for ``enclosing_scope``, which is
    exact.  A name missing from ``stubs`` is unknown beyond that scope, not
    absent.

    *Unsupported branch* (``found: True``, ``"stubs"`` key absent):
    ::

        { "found":  True,
          "source": str,
          "edge":   str,
          "unsupported": True,
          "reason":  str,               # deferred_reference_backend |
                                        # not_yet_implemented | unknown_edge |
                                        # not_applicable | unparseable
          "detail":  str,               # human-readable explanation
          "report_issues": str }        # #458 — URL to report this limitation

    Each Stub carries: ``handle``, ``kind``, ``scope``, ``line_start``,
    ``line_end``, and ``signature`` when Jedi yields one (always for
    class/function/method; also any name whose inferred type is callable).
    A ``re_exports`` stub also carries ``bindings``, the public names it binds.

    A call, import or base whose definition Jedi can't pin to exactly one
    target is reported as unresolved (``unresolved_call_sites`` /
    ``unresolved_imports`` / ``unresolved_superclasses``), never guessed (#624).
    ``superclasses`` stubs are in declaration order.

    ``callees`` is the only supported way to ask what a function calls; the
    reverse question (what calls it) is not answerable here — see the
    ``deferred_reference_backend`` reason above.

    Args:
        handle: Canonical Python dotted-name string (from resolve/inspect).
        edge: The outbound edge to expand (e.g. ``"members"``, ``"callees"``).
        project_path: Project root path (default: current directory).
        max_stubs: Most stubs to return (#435), default 200; ``None`` for all.
            When the edge has more, the first ``max_stubs`` come back and the
            result also has ``truncated: true``, ``truncation_reasons:
            ["max_stubs"]`` and ``total`` (the edge's full size); the three are
            absent when nothing was cut.

    Returns:
        ExpandResult dict — not-found, supported, or unsupported (see above).
        A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
        ``stubs: []`` always means "measured, none found" — it is never returned
        for an unresolvable handle.
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's return to plain dict[str, Any] for the wire.
    return _for_caller(
        await _expand_impl(handle, edge, analyzer, max_stubs=max_stubs), project_path
    )


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("trace")
@track_mcp_operation("trace")
@on_jedi_worker
@described
async def trace(
    start: str | list[str],
    follow: list[str],
    project_path: str = ".",
    max_depth: int = 3,
    max_nodes: int = 50,
    stop_when: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Python: Bounded multi-hop BFS traversal — returns a typed Subgraph.

    The composition primitive: it walks the ``follow`` edges outward from
    ``start`` across multiple hops, deduping by canonical handle, and returns a
    ``Subgraph`` of the reachable structure.  Use resolve()/inspect() to obtain
    canonical handles first, then trace() to see structure across hops (call
    chains, reverse-import closures, member trees).

    Composes the same edge registry as ``expand``; the implemented edges
    (<<fact:edges.implemented>>) are traversed.  Any other edge named in
    ``follow`` (deferred reference edges, unknown names) is reported in
    ``unsupported_edges`` rather than silently dropped — a silent drop would
    falsely read as "no such neighbours".  So is an implemented edge that does
    not apply to a node's kind (e.g. ``imports`` on a class), or ``callees`` on
    a declaration in a stub (``stub_declaration``, #933), with ``expand``'s own
    reason and detail (#621).

    Every hop is exactly what ``expand(node, edge)`` would return: a node
    ``expand`` cannot resolve is not walked and is listed in
    ``unresolved_nodes``; a hop's adjacents are added all together or not at
    all, so a walked hop is never partial — a hop cut by ``max_depth`` or
    ``max_nodes`` records no edges and sets the matching truncation reason.

    Static-surface ceiling: each hop carries its edge's ceiling, so a trace
    over ``members`` or ``subclasses`` is complete only over that edge's
    measured scope; runtime-injected members and dynamically-created
    subclasses are not walked.  Each edge's ceiling:

    <<fact:edges.implemented:ceilings>>

    Response shape — ``Subgraph``::

        { "nodes": { handle: Stub, ... },        # deduped by canonical handle
          "edges": [ {"from": h, "to": h, "kind": edge}, ... ],
          "truncated": bool,                     # a cap cut off reachable nodes
          "truncation_reasons": ["max_depth"?, "max_nodes"?],  # which cap(s) fired
          "unsupported_edges": [ {"edge", "reason", "detail"}, ... ],
          "unresolved_roots": [ handle, ... ],  # #488 — always present; [] when every root resolved
          "unresolved_nodes": [ handle, ... ],  # #621 — always present; interior nodes not walked
          "unresolved_call_sites": { handle: count, ... },  # #488 — present iff callees walked
          "unresolved_imports": { handle: [target, ...], ... },  # #494 — present iff imports walked
          "unresolved_importers": { handle: [file, ...], ... },  # #668 — present iff imported_by walked
          "unparseable_files": { handle: [file, ...], ... },  # #729 — present iff one of <<fact:edges.unparseable>> walked
          "report_issues": str,   # #458 — present ONLY when unsupported_edges non-empty
          "ceilings": { edge: str, ... } }  # #417 — each walked edge's ceiling (see expand)

    Edges are NOT deduped across kinds; edges to already-visited handles are
    recorded (so cycles stay visible) but never re-expanded, guaranteeing
    termination on cyclic graphs.  ``truncated`` is true ONLY when ``max_depth``
    or ``max_nodes`` cut off reachable handles before natural termination — not
    merely because a cap was set.

    Args:
        start: One canonical handle, or a list of them, as BFS roots.
        follow: Edge names to traverse at every hop, from the implemented
            edges above (e.g. ``["members"]`` or ``["imported_by"]``).
        project_path: Project root path (default: current directory).
        max_depth: Maximum hop distance from a root before a node becomes a
            non-expanded frontier leaf (default 3).
        max_nodes: Maximum number of distinct nodes in the subgraph; reaching it
            sets ``truncated`` (default 50).
        stop_when: Optional StopPredicate (``exclude_external`` /
            ``module_pattern`` / ``exclude_tests``); a matching adjacent is a
            pruned boundary.  Roots are never pruned.  ``exclude_external`` stops
            at stdlib/site-packages nodes — keeps a trace inside the project (the
            common case for a call chain).

    Returns:
        A ``Subgraph`` dict (plain, JSON-serialisable).  A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
        An unresolvable root contributes no node but is listed in the always-present
        ``unresolved_roots`` (#488) — so an empty ``nodes`` is never silently
        ambiguous between "root has no neighbours" (``unresolved_roots: []``) and
        "root did not resolve" (handle listed).  When ``callees`` is traced,
        ``unresolved_call_sites`` ({handle: count}) reports each node's
        unresolved (dynamic / un-inferable / flaky) call sites, so a populated
        subgraph never overstates how complete the call walk was.
    """
    analyzer = get_analyzer(project_path)
    return _for_caller(
        await _trace_impl(
            start,
            follow,
            analyzer,
            max_depth=max_depth,
            max_nodes=max_nodes,
            stop_when=stop_when,
        ),
        project_path,
    )


@mcp.tool()
@tool_errors
@validate_mcp_inputs
@metrics.measure("outline")
@track_mcp_operation("outline")
@on_jedi_worker
@described
async def outline(
    handle: str,
    project_path: str = ".",
    max_depth: int | None = 1,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Python: Structural skeleton of a module or class — names, kinds, signatures, line spans.

    Returns a nested ``OutlineTree`` — the ``members`` hierarchy of *handle* as a
    tree of lightweight structural nodes (``Stub``).  Each node carries
    ``handle``, ``kind``, ``scope``, ``line_start``, ``line_end``, and
    ``signature`` when Jedi yields one.  No source content anywhere in the tree.

    Use ``resolve()`` or ``inspect()`` first to obtain a canonical handle, then
    ``outline()`` to see the structural skeleton in one call — the single-call
    answer to "show me the structure of this scope."

    **Default is direct members only (``max_depth=1``).**  Nested non-empty
    containers (a class inside the module, a subpackage) come back as
    ``truncated: "max_depth"`` — drill on demand by calling ``outline`` on that
    node's handle, or pass a larger ``max_depth`` (``None`` = unbounded).

    **Static-surface ceiling.** The tree walks the ``members`` edge, so it is
    complete only over that edge's measured scope: class-body definitions for a
    class (instance attributes assigned in methods, ``self.x = ...``, are NOT
    measured) and module-level definitions for a module.  Runtime-injected
    members (metaclass / ``setattr`` / ``__getattr__`` / ``type()`` /
    ``__init_subclass__``) are NOT captured either — e.g. ``outline`` of a
    Django ``Model`` omits its metaclass-injected ``_meta`` / ``objects`` /
    ``DoesNotExist``.  An absent member is unknown outside the measured scope,
    not absent from the code.

    **Absence contracts — an agent MUST read these before consuming the tree.**

    *Contract 1 — ``children`` absent ⇔ not expanded.*

    ``children`` present (including ``children: []``) means *measured*: the
    complete set of direct members of this node.  ``children: []`` is a genuine
    leaf — a container with no members, or a non-container (function/method/
    variable).  ``children`` **absent** means a cap fired and this node was not
    walked — treat it as "unknown," **never as empty.**

    *Contract 2 — ``truncated`` absent-not-false.*

    ``truncated: true`` is present **only** on a node that a cap cut off; it
    always co-occurs with ``truncation_reason`` and an **absent** ``children``.
    Fully-walked nodes omit ``truncated`` entirely — ``truncated: false`` never
    appears.

    **Truncation reasons (one string per node — not a list):**

    - ``"max_depth"`` — at the depth frontier; ``resolve_members`` was peeked
      once and found members (a genuine empty container at the frontier gets
      ``children: []`` instead).  Like ``max_nodes`` it is a budget cut, so it
      carries ``member_count`` (or, in survey mode, ``submodule_count``): how
      many children it withheld (#435).  Recover with a larger ``max_depth`` or
      by outlining that node.
    - ``"max_nodes"`` — node-budget reserve-before-expand: a container is
      expanded only if the budget admits ALL its direct members, else it is cut
      off whole.  Such a node ALSO carries ``member_count`` — the count of
      direct members withheld (a fresh count; the children were never partially
      listed) — or, in package survey mode, ``submodule_count`` (the submodules
      withheld).  Recover with a larger ``max_nodes`` or by targeting the subtree.
    - ``"external"`` — external-scope container at depth ≥ 1; no deeper walk
      into third-party code.
    - ``"survey_leaf"`` — package survey mode only (below): a module that HAS
      members, which a survey does not walk.  Recover with ``outline`` on that
      module's handle.  No ``member_count`` (one would cost a walk per leaf).
    - ``"unparseable"`` — the node's own file can't be parsed by the server's
      Python (e.g. newer syntax), so its members were not measured (#703).
      Never ``children: []``.  Recover by reading the file.

    When both ``max_nodes`` AND a depth/external cap could apply to the same
    node, ``truncation_reason`` is ``"max_nodes"`` (the harder global bound).

    **Ceiling (#417).** The root carries ``ceiling``, and the tree is complete
    over that scope only.  For a members walk it is
    <<fact:edge.members:ceiling>>.  For a package survey it is
    <<fact:edge.submodules:ceiling>>.  Absent for a non-container root.

    **Result-level summary (#435).** The root also carries
    ``truncation_reasons``: the sorted set of every node's
    ``truncation_reason`` (absent when nothing was cut), named like
    ``trace``'s.  Check it first: it shows a real ``max_nodes`` cut that would
    otherwise hide among many ``survey_leaf`` nodes.  Budget reasons
    (``max_depth``, ``max_nodes``) mean "raise the limit" and always carry a
    count; boundary reasons (``external``, ``survey_leaf``) mean "outline that
    node" and carry none; ``unparseable`` means "read that node's file".

    **Package survey mode.** When *handle* is a package that has submodules, the
    tree walks the ``submodules`` edge instead of ``members``: children are its
    child modules/subpackages.  Module members are never walked in a survey — a
    module with members is ``truncated: "survey_leaf"``; only a module with no
    members is ``children: []``.  A walked package whose ``__init__`` defines
    members carries ``member_count`` (present only when > 0) — those members are
    not in the tree; ``expand(pkg, "members")`` lists them.  A package root with
    no submodules is outlined by its ``members`` instead.

    **Counts are named for their edge.** ``member_count`` / ``submodule_count``
    always equal ``inspect(handle).edge_counts["members"]`` /
    ``["submodules"]``.  On a ``truncated`` node the count was withheld by the
    cap; on a walked node (``children`` present) it is not part of this view.

    Args:
        handle: Canonical Python dotted-name string (from resolve/inspect).
        project_path: Project root path (default: current directory).
        max_depth: Maximum depth from the root (root is depth 0).  Default
            ``1`` — direct members only.  ``None`` means unbounded within scope;
            the external cap and ``max_nodes`` still apply.  At the frontier, ``resolve_members`` is peeked once
            to distinguish a genuine empty container from a cut-off one.
        max_nodes: Total-node budget for the tree (root counts as 1, default
            200).  A container the budget cannot fully admit is cut off whole
            (``truncated: "max_nodes"`` + ``member_count``), never partially
            expanded — so ``children`` is always the complete direct-member set.

    Returns:
        ``OutlineTree`` dict — ``{"found": True, "node": Stub, "children":
        [OutlineTree, ...]}`` (``found`` on the root only).  A lookup miss never raises. The call errors (an MCP tool error, not a response) only when it can't run:
        an invalid argument, a ``project_path`` that doesn't exist, an unusable config,
        or an unreadable file.
        An unresolvable handle yields
        ``{"found": False, "handle": str, "reason": "unresolved", "detail": str}``
        — no placeholder tree.  Children within each parent are in source order
        (sorted by ``(line_start, handle)``); BFS inclusion order bounds the budget
        gracefully (all of depth 1 before any of depth 2, etc.).
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's return to plain dict[str, Any] for the wire.
    return _for_caller(
        await _outline_impl(handle, analyzer, max_depth=max_depth, max_nodes=max_nodes),
        project_path,
    )


# Optional admin tools (enabled via PYEYE_ENABLE_PERFORMANCE_METRICS=true)


async def get_performance_metrics(
    metric_name: str | None = None, export_format: str = "json"
) -> dict[str, Any] | str:
    """Get performance metrics for the PyEye MCP server.

    Args:
        metric_name: Optional specific metric name to retrieve
        export_format: Output format - 'json' (default) or 'prometheus'

    Returns:
        Performance metrics in requested format
    """
    if export_format == "prometheus":
        return metrics.export_prometheus()

    if metric_name:
        return metrics.get_stats(metric_name)

    return metrics.get_performance_report()


async def get_connection_diagnostics() -> dict[str, Any]:
    """Get connection lifecycle diagnostics for debugging disconnects.

    Returns:
        ``{connection, errors, pattern_warning, status}``: the connection
        summary (uptime, idle time, recent events), the error summary, any
        detected error pattern, and ``"healthy"`` or ``"warning"``.
    """
    from .connection_diagnostics import get_diagnostics
    from .error_tracker import get_error_tracker

    diagnostics = get_diagnostics()
    error_tracker = get_error_tracker()

    # Get summaries
    conn_summary = diagnostics.get_summary()
    error_summary = error_tracker.get_error_summary()

    # Check for error patterns
    pattern_warning = error_tracker.check_error_pattern()

    return {
        "connection": conn_summary,
        "errors": error_summary,
        "pattern_warning": pattern_warning,
        "status": "healthy" if not pattern_warning else "warning",
    }


#: The opt-in admin tools: the one list, read by the registration below and by
#: the docs-facts extractor, so the docs list them whether or not the flag is set.
ADMIN_TOOLS: tuple[Callable[..., Any], ...] = (get_performance_metrics, get_connection_diagnostics)

if settings.enable_performance_metrics:
    for _admin_tool in ADMIN_TOOLS:
        mcp.tool()(_admin_tool)


# MCP Resources


@mcp.resource("pyeye://about")
def get_about() -> str:
    """Get pyeye's self-description: version, repository, and issues URL.

    Lets an agent answer "what version are you, and where do I report a problem
    with you?" deterministically in one round-trip (#458), instead of guessing
    the repo slug out-of-band.

    Returns:
        A JSON object with ``name``, ``version``, ``repository`` and ``issues``.
    """
    return json.dumps(meta.about())
