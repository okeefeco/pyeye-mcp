"""Main MCP server implementation for PyEye."""

import builtins
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
from .lookup import lookup as _lookup_impl

# Logger — configured by __main__.py or caller; fallback to basic stderr.
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp = FastMCP("PyEye")

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

    return {
        "packages": config.get_package_paths(),
        "namespaces": config.get_namespaces(),
        "standalone": config.get_standalone_config(),
        "config_file": (config.project_path / f".{PROJECT_NAME}.json").as_posix(),
    }


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_symbol")
@track_mcp_operation("find_symbol")
async def find_symbol(
    name: str,
    project_path: str = ".",
    fuzzy: bool = False,
    scope: str = "all",
) -> list[dict[str, Any]]:
    """Python: Find class/function definitions. Unlike grep, follows imports and finds re-exports.

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides fuzzy search and scope filtering for targeted queries.

    Searches across the main project plus all configured additional packages
    and namespace packages. Use the scope parameter to control search breadth.

    Args:
        name: Symbol name to search for
        project_path: Root directory of the project to search
        fuzzy: Enable fuzzy matching for partial names
        scope: Search scope - "main", "all", "namespace:name", or list of scopes
    """
    try:
        analyzer = get_analyzer(project_path)
        results = await analyzer.find_symbol(
            name, fuzzy=fuzzy, include_import_paths=True, scope=scope
        )

    except FileNotFoundError as e:
        raise FileAccessError(
            f"Project path not found: {Path(project_path).as_posix()}", project_path
        ) from e
    except Exception as e:
        logger.error(f"Error searching for symbol {name}: {e}")
        raise AnalysisError(
            f"Failed to search for symbol '{name}'",
            file_path=project_path,
            operation="symbol_search",
            error=str(e),
        ) from e

    return results


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("goto_definition")
@track_mcp_operation("goto_definition")
async def goto_definition(
    file: str, line: int, column: int, project_path: str = "."
) -> dict[str, Any] | None:
    """Python: Jump to where a symbol is defined from any usage location.

    For general use, prefer lookup() which accepts any identifier form and returns richer results.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.goto_definition(file, line, column)


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


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_type_info")
@track_mcp_operation("get_type_info")
async def get_type_info(
    file: str,
    line: int,
    column: int,
    project_path: str = ".",
    detailed: bool = False,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Python: Get type hints, docstrings, and base classes at cursor position.

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides detailed mode and fields filtering for targeted queries.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project
        detailed: Include additional information like methods and attributes
        fields: Optional list of top-level fields to include in response.
               This filters the TOP-LEVEL response keys only.

               Valid top-level fields:
               - position: File location information (dict with file, line, column)
               - inferred_types: Type information (list of type dicts with name, type,
                                base_classes, mro, methods, attributes, etc.)
               - docstring: Documentation string

               Note: Fields like base_classes, mro, methods, attributes are NESTED
               inside the inferred_types field, not top-level. Phase 2 only supports
               top-level filtering. Use fields=["inferred_types"] to get all type
               information without position or docstring overhead.

               Token optimization examples:
               - fields=["inferred_types"] reduces tokens by 69.6% (~400 vs ~700 tokens)
               - fields=["position", "docstring"] returns only position and docstring
               - fields=["inferred_types", "docstring"] returns type info and docs
               - fields=None (default) returns all top-level fields
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_type_info(file, line, column, detailed=detailed, fields=fields)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_imports")
@track_mcp_operation("find_imports")
async def find_imports(module_name: str, project_path: str = ".") -> list[dict[str, Any]]:
    """Python: Find all files that import a specific module.

    For general use, prefer lookup() which accepts any identifier form and returns richer results.

    Args:
        module_name: Name of the module to find imports for
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.find_imports(module_name)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_call_hierarchy")
@track_mcp_operation("get_call_hierarchy")
async def get_call_hierarchy(
    function_name: str, file: str | None = None, project_path: str = "."
) -> dict[str, Any]:
    """Python: Trace function callers and callees through the codebase.

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides full call graph traversal beyond the default limit.

    Args:
        function_name: Name of the function
        file: Optional file to search in (searches whole project if not specified)
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_call_hierarchy(function_name, file)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("list_packages")
@track_mcp_operation("list_packages")
async def list_packages(project_path: str = ".") -> list[dict[str, Any]]:
    """Python: List all packages with their structure and subpackages.

    Args:
        project_path: Root path of the project
    """
    try:
        analyzer = get_analyzer(project_path)
        return await analyzer.list_packages()
    except ProjectNotFoundError as e:
        raise FileAccessError(
            f"Project path not found: {Path(project_path).as_posix()}", project_path
        ) from e
    except Exception as e:
        logger.error(f"Error listing packages: {e}")
        raise AnalysisError(
            "Failed to list packages",
            file_path=project_path,
            operation="list_packages",
            error=str(e),
        ) from e


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("list_modules")
@track_mcp_operation("list_modules")
async def list_modules(
    project_path: str = ".", fields: list[str] | None = None
) -> list[dict[str, Any]]:
    """Python: List all modules with their exports, classes, functions, and metrics.

    Args:
        project_path: Root path of the project
        fields: Optional list of fields to include in each module's response.
               Valid fields: name, import_path, file, exports, classes, functions,
                           imports_from, size_lines, has_tests
               Examples:
               - fields=["name", "file"] - Only module name and file path
               - fields=["exports", "classes"] - Only exports and class info
               - fields=None (default) - All fields included
    """
    try:
        analyzer = get_analyzer(project_path)
        result = await analyzer.list_modules()

        # Apply field filtering if requested
        if fields is not None:
            result = filter_fields(result, fields)  # type: ignore

        return result
    except (ValueError, TypeError):
        # Let validation errors propagate directly
        raise
    except ProjectNotFoundError as e:
        raise FileAccessError(
            f"Project path not found: {Path(project_path).as_posix()}", project_path
        ) from e
    except Exception as e:
        logger.error(f"Error listing modules: {e}")
        raise AnalysisError(
            "Failed to list modules", file_path=project_path, operation="list_modules", error=str(e)
        ) from e


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("analyze_dependencies")
@track_mcp_operation("analyze_dependencies")
async def analyze_dependencies(
    module_path: str, project_path: str = ".", scope: str = "all"
) -> dict[str, Any]:
    """Python: Map module dependencies and detect circular imports. Semantic analysis grep can't do.

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


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_module_info")
@track_mcp_operation("get_module_info")
async def get_module_info(module_path: str, project_path: str = ".") -> dict[str, Any]:
    """Python: Get module exports, classes, functions, and complexity metrics.

    For general use, prefer lookup() which accepts any identifier form and returns richer results.

    Args:
        module_path: Import path of the module (e.g., "pyeye.mcp")
        project_path: Root path of the project
    """
    try:
        analyzer = get_analyzer(project_path)
        return await analyzer.get_module_info(module_path)
    except ProjectNotFoundError as e:
        raise FileAccessError(
            f"Project path not found: {Path(project_path).as_posix()}", project_path
        ) from e
    except FileAccessError:
        raise  # Re-raise module not found errors
    except Exception as e:
        logger.error(f"Error getting module info: {e}")
        raise AnalysisError(
            f"Failed to get module info for {module_path}",
            file_path=project_path,
            operation="get_module_info",
            error=str(e),
        ) from e


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("list_project_structure")
@track_mcp_operation("list_project_structure")
def list_project_structure(project_path: str = ".", max_depth: int = 3) -> dict[str, Any]:
    """Python: Hierarchical view of Python files and packages in the project.

    Args:
        project_path: Root path of the project
        max_depth: Maximum directory depth to traverse
    """
    project_root = Path(project_path)

    def build_tree(path: Path, current_depth: int = 0) -> dict[str, Any]:
        if current_depth >= max_depth:
            return {"type": "directory", "name": path.name, "truncated": True}

        if path.is_file():
            return {
                "type": "file",
                "name": path.name,
                "size": path.stat().st_size,
            }

        children = []
        try:
            for child in sorted(path.iterdir()):
                # Skip hidden files and common non-Python directories
                if child.name.startswith(".") or child.name in ["__pycache__", "node_modules"]:
                    continue

                # Only include Python files and directories
                if child.is_file() and child.suffix not in [".py", ".pyx", ".pyi"]:
                    continue

                children.append(build_tree(child, current_depth + 1))

        except PermissionError:
            pass

        return {
            "type": "directory",
            "name": path.name,
            "children": children,
        }

    return build_tree(project_root)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_subclasses")
@track_mcp_operation("find_subclasses")
async def find_subclasses(
    base_class: str,
    project_path: str = ".",
    include_indirect: bool = True,
    show_hierarchy: bool = False,
) -> list[dict[str, Any]]:
    """Python: Find inheritance tree including indirect subclasses. Impossible with grep.

    For general use, prefer lookup() which accepts any identifier form.
    This tool provides show_hierarchy and indirect inheritance chains for targeted queries.

    Args:
        base_class: Name of the base class to find subclasses for
        project_path: Root path of the project
        include_indirect: Include indirect inheritance (grandchildren, etc.)
        show_hierarchy: Show the full inheritance chain
    """
    try:
        analyzer = get_analyzer(project_path)

        return await analyzer.find_subclasses(
            base_class=base_class,
            include_indirect=include_indirect,
            show_hierarchy=show_hierarchy,
        )
    except ProjectNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error finding subclasses: {e}")
        raise AnalysisError(
            f"Failed to find subclasses of {base_class}",
            file_path=project_path,
            error=str(e),
        ) from e


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("lookup")
@track_mcp_operation("lookup")
async def lookup(
    identifier: str | None = None,
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    project_path: str = ".",
    limit: int = 20,
) -> dict[str, Any]:
    """Python: Look up any identifier — name, full dotted path, file path, or coordinates.

    Returns comprehensive structural information about the resolved Python object.
    """
    return await _lookup_impl(
        identifier=identifier,
        file=file,
        line=line,
        column=column,
        project_path=project_path,
        limit=limit,
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


if settings.enable_performance_metrics:
    mcp.tool()(get_performance_metrics)


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


# Main entry point
if __name__ == "__main__":
    import atexit

    # Set up logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Initialize unified metrics session
    ensure_unified_session()

    # Cleanup on exit
    def cleanup() -> None:
        """Clean up all projects and watchers on exit."""
        from .unified_metrics import get_unified_collector

        # End unified metrics session
        collector = get_unified_collector()
        collector.end_session()

        manager = get_project_manager()
        manager.cleanup_all()
        logger.info("Cleaned up all projects and watchers")

    atexit.register(cleanup)

    # Initialize plugins for current directory
    initialize_plugins(".")

    logger.info("Starting PyEye Server with file watching")
    logger.info(f"Active plugins: {[p.name() for p in _plugins]}")

    # Run the server
    mcp.run()
