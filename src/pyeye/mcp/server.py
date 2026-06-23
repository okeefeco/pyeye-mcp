"""Main MCP server implementation for PyEye."""

import builtins
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..analyzers.jedi_analyzer import JediAnalyzer
from ..config import ProjectConfig
from ..constants import PROJECT_NAME
from ..exceptions import (
    AnalysisError,
    FileAccessError,
    ProjectNotFoundError,
)
from ..metrics import metrics

# Import metrics_hook only if available (for optional unified metrics support)
try:
    from ..metrics_hook import auto_session_for_mcp, track_mcp_operation

    UNIFIED_METRICS_AVAILABLE = True
except ImportError:
    # Fallback if unified metrics not available
    UNIFIED_METRICS_AVAILABLE = False

    def track_mcp_operation(tool_name: str | None = None) -> Any:  # type: ignore[misc]
        """No-op decorator when unified metrics not available."""
        _ = tool_name  # Mark as intentionally unused

        def decorator(func):  # type: ignore[no-untyped-def]
            # Preserve the original function without modification
            # This is critical for maintaining async compatibility
            import functools

            return functools.wraps(func)(func)

        return decorator

    def auto_session_for_mcp() -> str:
        """No-op when unified metrics not available."""
        return "default_session"


from ..plugins.django import DjangoPlugin
from ..plugins.flask import FlaskPlugin
from ..plugins.pydantic import PydanticPlugin
from ..project_manager import get_project_manager
from ..settings import settings
from ..validation import validate_mcp_inputs
from . import meta
from .operations.expand import expand as _expand_impl
from .operations.inspect import inspect as _inspect_impl
from .operations.outline import outline as _outline_impl
from .operations.resolve import (
    resolve as _resolve_impl,
    resolve_at as _resolve_at_impl,
)
from .operations.trace import trace as _trace_impl

# Logger — configured by __main__.py or caller; fallback to basic stderr.
logger = logging.getLogger(__name__)

# Initialize the MCP server.  The instructions block carries an in-band pointer
# to where pyeye bugs are reported (#458), so it is always in the agent's context.
mcp = FastMCP("PyEye", instructions=meta.server_instructions())

# Initialize unified metrics session
_unified_session_id = None


def ensure_unified_session() -> None:
    """Ensure unified metrics session is started."""
    global _unified_session_id
    if _unified_session_id is None:
        _unified_session_id = auto_session_for_mcp()


# Global plugin registry
_plugins: list[Any] = []
PLUGINS = _plugins  # Expose for testing

# Module-level exports for testing
project_manager = None  # Will be initialized lazily
project_config = None  # Will be initialized lazily


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
    global _plugins
    _plugins = []

    # Load configuration for namespace support
    config = ProjectConfig(project_path)

    # Try to activate each plugin
    plugin_classes = [PydanticPlugin, DjangoPlugin, FlaskPlugin]

    for plugin_class in plugin_classes:
        try:
            plugin = plugin_class(project_path)  # type: ignore[abstract]
            if plugin.detect():
                # Pass namespace configuration to the plugin
                from pathlib import Path

                plugin.set_additional_paths([Path(p) for p in config.get_package_paths()])
                plugin.set_namespace_paths(config.get_namespaces())

                _plugins.append(plugin)
                logger.info(f"Activated {plugin.name()} plugin with namespace support")

                # Register plugin tools
                for tool_name, tool_func in plugin.register_tools().items():
                    # Wrap tool function to work with MCP
                    globals()[tool_name] = mcp.tool()(tool_func)

        except Exception as e:
            logger.warning(f"Failed to load plugin {plugin_class.__name__}: {e}")
            # Don't raise - plugins are optional


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


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("configure_packages")
@track_mcp_operation("configure_packages")
def configure_packages(
    packages: list[str] | None = None,
    namespaces: dict[str, list[str]] | None = None,
    standalone_dirs: list[str] | None = None,
    recursive: bool = True,
    file_pattern: str = "*.py",
    exclude_patterns: list[str] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Python: Configure additional packages, namespaces, and standalone scripts for analysis.

    Args:
        packages: List of package paths to include
        namespaces: Namespace packages with their repo paths
        standalone_dirs: Directories containing standalone Python scripts
        recursive: Scan standalone directories recursively
        file_pattern: Glob pattern for standalone files
        exclude_patterns: Patterns to exclude from standalone scanning
        save: Save configuration to .pyeye.json
    """
    # Load existing config
    global project_config
    project_config = ProjectConfig(".")
    config = project_config

    # Update configuration
    if packages:
        config.config.setdefault("packages", []).extend(packages)

    if namespaces:
        config.config.setdefault("namespaces", {}).update(namespaces)

    if standalone_dirs:
        # Update standalone configuration
        standalone_config = config.config.setdefault("standalone", {})
        standalone_config.setdefault("dirs", []).extend(standalone_dirs)
        standalone_config["recursive"] = recursive
        standalone_config["file_pattern"] = file_pattern
        if exclude_patterns is None:
            exclude_patterns = []
        standalone_config["exclude_patterns"] = exclude_patterns

    # Save if requested
    if save and (packages or namespaces or standalone_dirs):
        config.save_config()

    # Apply configuration to project manager
    manager = get_project_manager()
    all_paths = config.get_package_paths()

    if len(all_paths) > 1:
        # Configure with all paths
        manager.get_project(all_paths[0], all_paths[1:])

    # Configure namespaces
    for namespace, ns_paths in config.get_namespaces().items():
        manager.namespace_resolver.register_namespace(namespace, ns_paths)

    # Invalidate cached analyzers for all paths so the next get_analyzer call
    # rebuilds with the updated package paths, namespaces, and standalone
    # directories.  Multi-project / namespace scenarios can have stale
    # analyzers for secondary paths too.
    if all_paths:
        for path in all_paths:
            manager.invalidate_analyzer(path)
    else:
        manager.invalidate_analyzer(".")

    return {
        "packages": config.get_package_paths(),
        "namespaces": config.get_namespaces(),
        "standalone": config.get_standalone_config(),
        "config_file": (config.project_path / f".{PROJECT_NAME}.json").as_posix(),
    }


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("resolve")
@track_mcp_operation("resolve")
async def resolve(
    identifier: str,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Resolve any identifier form to a canonical Handle.

    Accepts bare names, FQN dotted paths, re-exported public paths,
    file:line coordinates, or file paths. Returns the definition-site
    canonical handle along with kind and scope ("project" or "external").

    Args:
        identifier: The identifier to resolve. Forms supported:
            - Bare name: "Config"
            - FQN: "a.b.c.Config"
            - Re-exported: "package.Config" (collapses to definition site)
            - File:line: "src/foo.py:42"
            - File only: "src/foo.py"
        project_path: Project root path (default: current directory)

    Returns:
        ResolveResult dict — one of:
        - Success: {"found": True, "handle": str, "kind": str, "scope": "project"|"external"}
        - Ambiguous: {"found": True, "ambiguous": True, "candidates": [...]}
        - Not found: {"found": False, "reason": str}
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's TypedDict union to plain dict[str, Any]
    # to match this wrapper's declared return type. TypedDict instances are
    # already dicts at runtime; this is a mypy-compliance shallow copy.
    return dict(await _resolve_impl(identifier, analyzer))


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("resolve_at")
@track_mcp_operation("resolve_at")
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
        ResolveResult dict (see resolve() for shape).
    """
    analyzer = get_analyzer(project_path)
    # See note on resolve() above re: dict() widening.
    return dict(await _resolve_at_impl(file, line, column, analyzer))


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("inspect")
@track_mcp_operation("inspect")
async def inspect(
    handle: str,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Inspect a canonical handle and return a structural Node.

    The "what is this?" operation. Returns the symbol's kind, location,
    signature, docstring, and kind-dependent fields. Cheap by default —
    no source content, no exhaustive enumerations. Edge counts and
    highlights come in later phases.

    Args:
        handle: Canonical Python dotted-name string (from resolve/resolve_at).
        project_path: Project root path (default: current directory)

    Returns:
        Node dict with universal fields (handle, kind, scope, location,
        docstring, edge_counts={}) plus kind-dependent fields:
        - class: signature (constructor), superclasses (list of Handle strings)
        - function/method: signature, parameters, return_type?, is_async, is_classmethod, is_staticmethod
        - module: is_package, package?
        - attribute/property/variable: type?, default? (simple literals only)
    """
    analyzer = get_analyzer(project_path)
    # See note on resolve() above re: dict() widening.
    return dict(await _inspect_impl(handle, analyzer))


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("expand")
@track_mcp_operation("expand")
async def expand(
    handle: str,
    edge: str,
    project_path: str = ".",
) -> dict[str, Any]:
    """Python: Expand one outbound edge from a canonical handle (single hop).

    The traversal primitive that walks ONE edge from a source handle and
    returns adjacent symbols as lightweight Stubs.  Use resolve()/inspect()
    first to obtain a canonical handle, then call expand() to traverse.

    Supported edges (the complete static/outbound set):
      - ``members``  — class/module → direct members (attributes, methods, nested
        classes).  ``stubs: []`` means the class/module was found but has no
        members; that is NOT the same as unsupported.  Static-surface ceiling:
        members are read from source; runtime-injected members (metaclass /
        ``setattr`` / ``__getattr__`` / ``type()`` / ``__init_subclass__``) are
        NOT captured — e.g. a Django ``Model`` shows none of its metaclass-injected
        ``_meta`` / ``objects`` / ``DoesNotExist``.
      - ``callees``  — function/method → forward static call targets.  Includes
        project symbols and stdlib/external symbols reachable via Jedi's goto.
        Dynamic calls (un-inferable parameters, ``getattr``, lambdas, etc.) are
        counted in ``unresolved_call_sites`` rather than invented.
      - ``imported_by``  — module → the project modules that import it (module
        Stubs), computed by static AST import-graph reversal (no reverse symbol
        search).  Covers importers anywhere in the project including tests and
        standalone scripts.  Non-module handles return the unsupported branch
        with ``reason: "not_yet_implemented"`` (symbol-level ``imported_by`` is
        not yet implemented).  Ceiling: runtime-dynamic imports
        (``importlib``/``__import__`` with computed targets) are not detected.
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
        subclasses (measured-none).  A non-class handle also returns the supported
        branch with ``stubs: []`` (and no ``transitive_hint``) — only a class CAN
        be subclassed, so ``[]`` is true by definition, not an absence-vs-zero
        lie.  Static-surface ceiling: the result is complete only over literal
        ``class B(A):`` subclassing; dynamically-created subclasses
        (``type('B', (A,), {})``, factory-built classes, ``__init_subclass__``
        registration) are NOT captured.
      - ``superclasses``  — class → its base classes (class Stubs), resolved by
        Jedi from the class definition (no reverse search).  A non-class handle
        returns ``stubs: []`` (``[]`` true by definition, as with ``subclasses``).
      - ``imports``  — module → the symbols/modules it imports (Stubs), computed
        by static AST + forward ``goto``.  ``stubs: []`` is measured-none.  A
        non-module handle returns the unsupported branch with
        ``reason: "not_yet_implemented"`` (mirrors ``imported_by``).
      - ``enclosing_scope``  — symbol → its immediate lexical enclosing scope
        (the inverse of ``members``), resolved by Jedi ``parent()``: a method →
        its class, a nested def/class → its enclosing def/class, a top-level
        def/class/variable → its module.  At most ONE Stub.  A module returns
        ``stubs: []`` (a module has no enclosing lexical scope — packages are not
        lexical scopes); ``[]`` is therefore measured-empty, never unsupported.

    Unsupported edges return the unsupported branch (never raise):
      - Inbound/reference edges (``callers``, ``references``,
        ``overrides``, …) require the Pyright reference backend (#333) and return
        ``unsupported: true, reason: "deferred_reference_backend"``.
      - Wrong-kind handles (e.g. ``imported_by`` on a non-module) return the
        unsupported branch with ``reason: "not_yet_implemented"``.
      - Unrecognised edge names return ``reason: "unknown_edge"``.

    Response shape — discriminated union:

    *Supported branch* (``"unsupported"`` key absent):
    ::

        { "source": str,                 # canonical source handle
          "edge":   str,
          "stubs":  [Stub, ...],         # [] == measured-empty (NOT unsupported)
          "unresolved_call_sites": int   # callees ONLY; absent for members }

    *Unsupported branch* (``"stubs"`` key absent):
    ::

        { "source": str,
          "edge":   str,
          "unsupported": True,
          "reason":  str,               # deferred_reference_backend |
                                        # not_yet_implemented | unknown_edge
          "detail":  str,               # human-readable explanation
          "report_issues": str }        # #458 — URL to report this limitation

    Each Stub carries: ``handle``, ``kind``, ``scope``, ``line_start``,
    ``line_end``, and ``signature`` when Jedi yields one (always for
    class/function/method; also any name whose inferred type is callable).

    Relationship to deprecated tools: ``members`` supersedes the deprecated
    ``find_subclasses``/``find_symbol`` pattern for enumerating class members.
    ``callees`` supersedes manual ``get_call_hierarchy`` usage for forward edges.
    Both deprecated tools remain registered until Phase B migration.

    Args:
        handle: Canonical Python dotted-name string (from resolve/inspect).
        edge: The outbound edge to expand (e.g. ``"members"``, ``"callees"``).
        project_path: Project root path (default: current directory).

    Returns:
        ExpandResult dict — supported branch or unsupported branch (see above).
        Never raises; unresolvable source handles yield graceful supported-empty
        results consistent with inspect()'s minimal-node contract.
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's return to plain dict[str, Any] for the wire.
    return dict(await _expand_impl(handle, edge, analyzer))


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("trace")
@track_mcp_operation("trace")
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
    (``members``, ``callees``, ``imported_by``, ``subclasses``, ``superclasses``,
    ``imports``, ``enclosing_scope``) are traversed.  Any other edge named in
    ``follow`` (deferred reference edges, unknown names) is reported in
    ``unsupported_edges`` rather than silently dropped — a silent drop would
    falsely read as "no such neighbours".

    Response shape — ``Subgraph``::

        { "nodes": { handle: Stub, ... },        # deduped by canonical handle
          "edges": [ {"from": h, "to": h, "kind": edge}, ... ],
          "truncated": bool,                     # a cap cut off reachable nodes
          "truncation_reasons": ["max_depth"?, "max_nodes"?],  # which cap(s) fired
          "unsupported_edges": [ {"edge", "reason", "detail"}, ... ],
          "report_issues": str }   # #458 — present ONLY when unsupported_edges non-empty

    Edges are NOT deduped across kinds; edges to already-visited handles are
    recorded (so cycles stay visible) but never re-expanded, guaranteeing
    termination on cyclic graphs.  ``truncated`` is true ONLY when ``max_depth``
    or ``max_nodes`` cut off reachable handles before natural termination — not
    merely because a cap was set.

    Args:
        start: One canonical handle, or a list of them, as BFS roots.
        follow: Edge names to traverse at every hop (e.g. ``["members"]``,
            ``["callees"]``, ``["imported_by"]``).
        project_path: Project root path (default: current directory).
        max_depth: Maximum hop distance from a root before a node becomes a
            non-expanded frontier leaf (default 3).
        max_nodes: Maximum number of distinct nodes in the subgraph; reaching it
            sets ``truncated`` (default 50).
        stop_when: Optional StopPredicate (``exclude_external`` /
            ``module_pattern`` / ``exclude_tests``); a matching adjacent is a
            pruned boundary.  Roots are never pruned.  ``exclude_external`` stops
            at stdlib/site-packages nodes — keeps a trace inside the project (the
            common ``callees`` case).

    Returns:
        A ``Subgraph`` dict (plain, JSON-serialisable).  Never raises; an
        unresolvable root simply contributes no node.
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's return to plain dict[str, Any] for the wire.
    return dict(
        await _trace_impl(
            start,
            follow,
            analyzer,
            max_depth=max_depth,
            max_nodes=max_nodes,
            stop_when=stop_when,
        )
    )


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("outline")
@track_mcp_operation("outline")
async def outline(
    handle: str,
    project_path: str = ".",
    max_depth: int | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Python: Structural skeleton of a module or class — names, kinds, signatures, line spans.

    Returns a nested ``OutlineTree`` — the ``members`` hierarchy of *handle* as a
    tree of lightweight structural nodes (``Stub``).  Each node carries
    ``handle``, ``kind``, ``scope``, ``line_start``, ``line_end``, and
    ``signature`` when Jedi yields one.  No source content anywhere in the tree.

    Use ``resolve()`` or ``inspect()`` first to obtain a canonical handle, then
    ``outline()`` to see the complete structural skeleton in one call — the
    single-call answer to "show me the structure of this scope."

    **Static-surface ceiling.** The tree walks the ``members`` edge, so it is
    complete over what is *statically defined in source* but not over runtime.
    Runtime-injected members (metaclass / ``setattr`` / ``__getattr__`` /
    ``type()`` / ``__init_subclass__``) are NOT captured — e.g. ``outline`` of a
    Django ``Model`` omits its metaclass-injected ``_meta`` / ``objects`` /
    ``DoesNotExist``.  An absent member is "not in source," not "not at runtime."

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
      ``children: []`` instead).
    - ``"max_nodes"`` — node-budget reserve-before-expand: a container is
      expanded only if the budget admits ALL its direct members, else it is cut
      off whole.  Such a node ALSO carries ``member_count`` — the count of
      direct members withheld (a fresh count; the children were never partially
      listed).  Recover with a larger ``max_nodes`` or by targeting the subtree.
    - ``"external"`` — external-scope container at depth ≥ 1; no deeper walk
      into third-party code.

    When both ``max_nodes`` AND a depth/external cap could apply to the same
    node, ``truncation_reason`` is ``"max_nodes"`` (the harder global bound).

    Args:
        handle: Canonical Python dotted-name string (from resolve/inspect).
        project_path: Project root path (default: current directory).
        max_depth: Maximum depth from the root (root is depth 0).  ``None``
            means unbounded within scope; the external cap and ``max_nodes``
            still apply.  At the frontier, ``resolve_members`` is peeked once
            to distinguish a genuine empty container from a cut-off one.
        max_nodes: Total-node budget for the tree (root counts as 1, default
            200).  A container the budget cannot fully admit is cut off whole
            (``truncated: "max_nodes"`` + ``member_count``), never partially
            expanded — so ``children`` is always the complete direct-member set.

    Returns:
        ``OutlineTree`` dict — ``{"node": Stub, "children": [OutlineTree, ...]}``.
        Never raises; an unresolvable handle yields a minimal single-node tree
        with ``children: []``.  Children within each parent are in source order
        (sorted by ``(line_start, handle)``); BFS inclusion order bounds the budget
        gracefully (all of depth 1 before any of depth 2, etc.).
    """
    analyzer = get_analyzer(project_path)
    # dict(...) widens the operation's return to plain dict[str, Any] for the wire.
    return dict(await _outline_impl(handle, analyzer, max_depth=max_depth, max_nodes=max_nodes))


# NOTE: superseded by future expand(handle, edge="references"); kept until Phase B migration.
@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_references")
@track_mcp_operation("find_references")
async def find_references(
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    project_path: str = ".",
    include_definitions: bool = True,
    include_subclasses: bool = False,
    fields: list[str] | None = None,
    symbol_name: str | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Python: Find ALL usages of a symbol. Understands inheritance - grep misses subclass refs.

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides fields filtering, include_subclasses, and symbol_name for full reference lists.

    Two calling conventions (coordinates take precedence if both provided):
    1. Coordinates: file + line + column (precise, unambiguous)
    2. Symbol name: symbol_name only (convenient; fails if name is ambiguous)

    If symbol_name matches multiple symbols, returns error with a "matches" list
    so you can pick the right one and retry with coordinates.

    Args:
        file: Path to the file (required with line and column)
        line: Line number (1-indexed, required with file and column)
        column: Column number (0-indexed, required with file and line)
        symbol_name: Symbol name (alternative to file+line+column)
        project_path: Root path of the project
        include_definitions: Include definitions in results
        include_subclasses: Also find references to all subclasses (polymorphic search)
        fields: Fields to include per reference. Valid: name, type, line, column,
               description, full_name, file, is_definition. Default: all fields.
    """
    # Validate input: determine which branch to use
    all_coords = file is not None and line is not None and column is not None
    any_coord = file is not None or line is not None or column is not None

    if all_coords:
        # Branch 1: All coordinates present — use them directly (ignore symbol_name)
        pass
    elif any_coord:
        # Branch 3: Some but not all coordinates provided (checked before symbol_name)
        return {
            "error": "Coordinates incomplete: provide all three (file, line, column) or use symbol_name instead"
        }
    elif symbol_name is not None:
        # Branch 2: Symbol name provided (no coordinates) — resolve to coordinates
        _sym_analyzer = get_analyzer(project_path)
        symbol_results = await _sym_analyzer.find_symbol(
            symbol_name, fuzzy=False, include_import_paths=True, scope="all"
        )
        # If symbol_name is a full dotted path (contains dots) and multiple results came
        # back, narrow to exact full_name match before disambiguation.
        if "." in symbol_name and len(symbol_results) > 1:
            fqn_matches = [r for r in symbol_results if r.get("full_name") == symbol_name]
            if fqn_matches:
                symbol_results = fqn_matches

        if len(symbol_results) == 0:
            if hasattr(builtins, symbol_name):
                return {
                    "error": f"Symbol '{symbol_name}' is a built-in with no source file; cannot find references by name"
                }
            return {"error": f"No symbol found matching '{symbol_name}'"}
        elif len(symbol_results) == 1:
            match = symbol_results[0]
            if "file" not in match:
                return {
                    "error": f"Symbol '{symbol_name}' is a built-in with no source file; cannot find references by name"
                }
            # Set coordinates and fall through to the existing resolution code
            file = match["file"]
            line = match["line"]
            column = match["column"]
        else:
            # Multiple matches — return disambiguation response
            return {
                "error": f"Multiple symbols found matching '{symbol_name}'. Specify file, line, and column to disambiguate.",
                "matches": symbol_results,
            }
    else:
        # Branch 4: Neither coordinates nor symbol_name provided
        return {"error": "Either symbol_name or file+line+column required"}

    # At this point, all three coordinates are guaranteed non-None
    # (either provided directly or resolved from symbol_name).
    assert file is not None
    assert line is not None
    assert column is not None

    analyzer = get_analyzer(project_path)
    result = await analyzer.find_references(
        file, line, column, include_definitions, include_subclasses
    )

    # Apply field filtering if requested
    if fields is not None:
        result = filter_fields(result, fields)  # type: ignore

    return result


# DEPRECATED: replaced by inspect(handle).edge_counts.callers for the count; future expand(handle, edge="callers") for the list. Will be removed in the legacy-tool cleanup phase.
@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_call_hierarchy")
@track_mcp_operation("get_call_hierarchy")
async def get_call_hierarchy(
    function_name: str, file: str | None = None, project_path: str = "."
) -> dict[str, Any]:
    """Python: Trace function callers and callees through the codebase.

    **Deprecated:** Replaced by ``inspect(handle).edge_counts.callers`` for the
    count and future ``expand(handle, edge="callers")`` for the list in the
    redesigned API. See
    docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md
    for the migration plan. This method will be removed once the legacy
    MCP tools are deprecated (Phase B of the migration).

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides full call graph traversal beyond the default limit.

    Args:
        function_name: Name of the function
        file: Optional file to search in (searches whole project if not specified)
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_call_hierarchy(function_name, file)


# DEPRECATED: replaced by future trace(handle, follow=["imports"]). Will be removed in the legacy-tool cleanup phase.
@mcp.tool()
@validate_mcp_inputs
@metrics.measure("analyze_dependencies")
@track_mcp_operation("analyze_dependencies")
async def analyze_dependencies(
    module_path: str, project_path: str = ".", scope: str = "all"
) -> dict[str, Any]:
    """Python: Map module dependencies and detect circular imports. Semantic analysis grep can't do.

    **Deprecated:** Replaced by future ``trace(handle, follow=["imports"])`` in
    the redesigned API. See
    docs/superpowers/specs/2026-05-02-progressive-disclosure-api-design.md
    for the migration plan. This method will be removed once the legacy
    MCP tools are deprecated (Phase B of the migration).

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides circular dependency detection and scope filtering for targeted queries.

    Args:
        module_path: Import path of the module (e.g., "pyeye.mcp")
        project_path: Root path of the project
        scope: Search scope - "main", "all", "namespace:name", or list
    """
    try:
        analyzer = get_analyzer(project_path)
        return await analyzer.analyze_dependencies(module_path, scope=scope)
    except ProjectNotFoundError as e:
        raise FileAccessError(
            f"Project path not found: {Path(project_path).as_posix()}", project_path
        ) from e
    except FileAccessError:
        raise  # Re-raise module not found errors
    except Exception as e:
        logger.error(f"Error analyzing dependencies: {e}")
        raise AnalysisError(
            f"Failed to analyze dependencies for {module_path}",
            file_path=project_path,
            operation="analyze_dependencies",
            error=str(e),
        ) from e


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
        Dictionary with connection diagnostics including:
        - Connection uptime and idle time
        - Recent connection events
        - Error summary and patterns
        - Signal handler status
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


if settings.enable_performance_metrics:
    mcp.tool()(get_performance_metrics)
    mcp.tool()(get_connection_diagnostics)


# Workflow Resources


def load_workflow(workflow_name: str) -> str:
    """Load workflow content from workflows directory.

    Args:
        workflow_name: Name of the workflow file (without .md extension)

    Returns:
        Workflow content as markdown string

    Raises:
        FileNotFoundError: If workflow file doesn't exist
    """
    workflow_file = Path(__file__).parent.parent / "workflows" / f"{workflow_name}.md"
    if not workflow_file.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_name}")
    return workflow_file.read_text(encoding="utf-8")


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


@mcp.resource("workflows://find-references")
def get_find_references_workflow() -> str:
    """Get the Find All References workflow.

    This workflow shows how to find ALL usages of a class/function,
    including both package code and standalone scripts/notebooks.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("find_references")


@mcp.resource("workflows://refactoring")
def get_refactoring_workflow() -> str:
    """Get the Safe Refactoring workflow.

    This workflow guides through safe refactoring by analyzing
    subclasses, references, and dependencies before making changes.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("refactoring")


@mcp.resource("workflows://code-understanding")
def get_code_understanding_workflow() -> str:
    """Get the Code Understanding workflow.

    This workflow helps understand unfamiliar code by systematically
    exploring structure, relationships, and usage patterns.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("code_understanding")


@mcp.resource("workflows://dependency-analysis")
def get_dependency_analysis_workflow() -> str:
    """Get the Dependency Analysis workflow.

    This workflow helps analyze module dependencies, import relationships,
    and architectural patterns in Python projects.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("dependency_analysis")


@mcp.resource("workflows://code-review-standards")
def get_code_review_standards_workflow() -> str:
    """Get the Python Code Review Standards workflow.

    This workflow provides industry best practices for Python code review
    including PEP standards, modern Python features, type safety, testing,
    and anti-pattern detection with MCP-enhanced semantic analysis.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("code_review_standards")


@mcp.resource("workflows://code-review-security")
def get_code_review_security_workflow() -> str:
    """Get the Python Security Code Review workflow.

    This workflow provides OWASP security guidelines for Python code review
    including input validation, injection prevention, authentication patterns,
    and data flow analysis using MCP tools.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("code_review_security")


@mcp.resource("workflows://code-review-pr")
def get_code_review_pr_workflow() -> str:
    """Get the Complete Pull Request Review workflow.

    This workflow provides a comprehensive PR review process combining
    automated checks, semantic analysis, code standards, security review,
    and manual review best practices.

    Returns:
        Markdown workflow documentation
    """
    return load_workflow("code_review_pr")


# Export for __main__.py
def get_unified_collector() -> Any:
    """Get the unified metrics collector.

    Returns:
        Unified metrics collector instance
    """
    from .unified_metrics import get_unified_collector as _get_collector

    return _get_collector()
