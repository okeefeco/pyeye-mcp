"""Main MCP server implementation for Python code intelligence."""

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .analyzers.jedi_analyzer import JediAnalyzer
from .config import ProjectConfig
from .exceptions import (
    AnalysisError,
    FileAccessError,
    ProjectNotFoundError,
)
from .metrics import metrics
from .plugins.django import DjangoPlugin
from .plugins.flask import FlaskPlugin
from .plugins.pydantic import PydanticPlugin
from .project_manager import get_project_manager
from .validation import validate_mcp_inputs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp = FastMCP("Python Code Intelligence")

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
    """Initialize plugins for the project."""
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


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("configure_packages")
def configure_packages(
    packages: list[str] | None = None,
    namespaces: dict[str, list[str]] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Configure additional package locations for analysis.

    Args:
        packages: List of package paths to include
        namespaces: Namespace packages with their repo paths
        save: Whether to save configuration to .pycodemcp.json

    Returns:
        Current configuration

    Example:
        configure_packages(
            packages=["../my-lib", "~/repos/shared-utils"],
            namespaces={
                "company": ["~/repos/company-auth", "~/repos/company-api"]
            }
        )
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

    # Save if requested
    if save and (packages or namespaces):
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
        "config_file": str(config.project_path / ".pycodemcp.json"),
    }


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_symbol")
async def find_symbol(
    name: str, project_path: str = ".", fuzzy: bool = False, use_config: bool = True
) -> list[dict[str, Any]]:
    """Find symbol definitions in the project.

    Args:
        name: Symbol name to search for
        project_path: Root path of the project to search
        fuzzy: Whether to use fuzzy matching
        use_config: Whether to use configuration file for additional packages

    Returns:
        List of symbol locations with file, line, column, type, and import_paths
    """
    try:
        # Use JediAnalyzer which now supports re-export tracking
        analyzer = get_analyzer(project_path)

        # Configure additional paths if requested
        if use_config:
            config = ProjectConfig(project_path)
            all_paths = config.get_package_paths()
            if len(all_paths) > 1:
                # Set additional paths on the analyzer if needed
                analyzer.additional_paths = [Path(p) for p in all_paths[1:]]

        # Use the analyzer's find_symbol method which includes import_paths
        results = await analyzer.find_symbol(name, fuzzy=fuzzy, include_import_paths=True)

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
async def goto_definition(
    file: str, line: int, column: int, project_path: str = "."
) -> dict[str, Any] | None:
    """Go to symbol definition from a specific position.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project

    Returns:
        Definition location or None if not found
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.goto_definition(file, line, column)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_references")
async def find_references(
    file: str, line: int, column: int, project_path: str = ".", include_definitions: bool = True
) -> list[dict[str, Any]]:
    """Find all references to the symbol at a specific position.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project
        include_definitions: Whether to include definitions in results

    Returns:
        List of reference locations
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.find_references(file, line, column, include_definitions)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_type_info")
async def get_type_info(
    file: str, line: int, column: int, project_path: str = "."
) -> dict[str, Any]:
    """Get type information at a specific position.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project

    Returns:
        Type information including inferred type and docstring
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_type_info(file, line, column)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_imports")
async def find_imports(module_name: str, project_path: str = ".") -> list[dict[str, Any]]:
    """Find all imports of a specific module in the project.

    Args:
        module_name: Name of the module to find imports for
        project_path: Root path of the project

    Returns:
        List of import locations
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.find_imports(module_name)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_call_hierarchy")
async def get_call_hierarchy(
    function_name: str, file: str | None = None, project_path: str = "."
) -> dict[str, Any]:
    """Get the call hierarchy for a function.

    Args:
        function_name: Name of the function
        file: Optional file to search in (searches whole project if not specified)
        project_path: Root path of the project

    Returns:
        Call hierarchy with callers and callees
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_call_hierarchy(function_name, file)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("configure_namespace_package")
def configure_namespace_package(namespace: str, repo_paths: list[str]) -> dict[str, Any]:
    """Configure a namespace package spread across multiple repositories.

    Args:
        namespace: Package namespace (e.g., "mycompany.services")
        repo_paths: List of repository paths containing parts of this namespace

    Returns:
        Configuration details and discovered structure

    Example:
        configure_namespace_package(
            namespace="mycompany",
            repo_paths=[
                "~/repos/mycompany-auth",
                "~/repos/mycompany-api",
                "~/repos/mycompany-utils"
            ]
        )
    """
    manager = get_project_manager()
    resolver = manager.namespace_resolver

    # Discover namespace packages
    discovered = resolver.discover_namespaces(repo_paths)

    # Register the namespace
    if namespace in discovered:
        resolver.register_namespace(namespace, [str(p) for p in discovered[namespace]])

    # Build structure map
    structure = resolver.build_namespace_map(repo_paths)

    # Configure Jedi projects for all paths
    all_paths = []
    for ns_paths in discovered.values():
        all_paths.extend([str(p) for p in ns_paths])

    # Create a unified project with all namespace paths
    if all_paths:
        # Use first path as main, rest as includes
        manager.get_project(all_paths[0], all_paths[1:] if len(all_paths) > 1 else None)

    return {
        "namespace": namespace,
        "discovered_namespaces": {k: [str(p) for p in v] for k, v in discovered.items()},
        "structure": structure,
        "status": "configured",
    }


@mcp.tool()
@validate_mcp_inputs
def find_in_namespace(import_path: str, namespace_repos: list[str]) -> dict[str, Any]:
    """Find a module/class within a namespace package spread across repos.

    Args:
        import_path: Full import path (e.g., "mycompany.auth.models.User")
        namespace_repos: Repository paths to search

    Returns:
        Locations where the import is found

    Example:
        find_in_namespace(
            "mycompany.auth.models.User",
            ["~/repos/mycompany-auth", "~/repos/mycompany-core"]
        )
    """
    manager = get_project_manager()
    resolver = manager.namespace_resolver

    # Discover namespaces if not already done
    resolver.discover_namespaces(namespace_repos)

    # Resolve the import
    resolved_paths = resolver.resolve_import(import_path, namespace_repos)

    results = {"import_path": import_path, "found_at": [], "namespace_structure": {}}

    # For each resolved path, find the specific symbol
    parts = import_path.split(".")
    symbol_name = parts[-1] if parts else None

    for path in resolved_paths:
        # Get the project for this path
        project_root = path.parent
        while project_root.parent != project_root and any(project_root.glob("*.py")):
            project_root = project_root.parent

        project = manager.get_project(str(project_root))

        # Search for the symbol
        if symbol_name:
            try:
                search_results = project.search(symbol_name, all_scopes=True)
                for result in search_results:
                    if result.module_path == path or str(result.module_path).startswith(
                        str(path.parent)
                    ):
                        found_at_list = results.get("found_at", [])
                        if isinstance(found_at_list, list):
                            found_at_list.append(
                                {
                                    "file": str(result.module_path),
                                    "line": result.line,
                                    "type": result.type,
                                    "description": result.description,
                                }
                            )
            except Exception as e:
                logger.error(f"Error searching in {Path(path).as_posix()}: {e}")

    # Add namespace structure
    results["namespace_structure"] = resolver.build_namespace_map(namespace_repos)

    return results


@mcp.tool()
@validate_mcp_inputs
def find_symbol_multi(
    name: str, project_paths: list[str], fuzzy: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """Find symbol across multiple projects.

    Args:
        name: Symbol name to search for
        project_paths: List of project paths to search
        fuzzy: Whether to use fuzzy matching

    Returns:
        Dictionary mapping project paths to their results
    """
    manager = get_project_manager()
    all_results = {}

    for path in project_paths:
        # Ensure each project is loaded
        project = manager.get_project(path)

        # Search in this project
        results = []
        try:
            search_results = project.search(name, all_scopes=True)

            for result in search_results:
                if not fuzzy and result.name != name:
                    continue

                results.append(
                    {
                        "name": result.name,
                        "file": str(result.module_path) if result.module_path else None,
                        "line": result.line,
                        "column": result.column,
                        "type": result.type,
                        "description": result.description,
                    }
                )

            if results:
                all_results[path] = results

        except Exception as e:
            logger.error(f"Error searching in {Path(path).as_posix()}: {e}")
            all_results[path] = [{"error": str(e)}]

    return all_results


@mcp.tool()
@validate_mcp_inputs
async def list_packages(project_path: str = ".") -> list[dict[str, Any]]:
    """List all Python packages in the project.

    Args:
        project_path: Root path of the project

    Returns:
        List of packages with structure information
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
async def list_modules(project_path: str = ".") -> list[dict[str, Any]]:
    """List all Python modules with exports and metrics.

    Args:
        project_path: Root path of the project

    Returns:
        List of modules with exports, classes, functions, and metrics
    """
    try:
        analyzer = get_analyzer(project_path)
        return await analyzer.list_modules()
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
async def analyze_dependencies(
    module_path: str, project_path: str = ".", scope: str = "all"
) -> dict[str, Any]:
    """Analyze import dependencies for a module.

    Args:
        module_path: Import path of the module (e.g., "pycodemcp.server")
        project_path: Root path of the project
        scope: Search scope (default "all"):
            - "main": Only the main project
            - "all": Main project + configured namespaces
            - "namespace:name": Specific namespace
            - ["main", "namespace:x"]: Multiple scopes

    Returns:
        Dependencies analysis including imports, imported_by, and circular dependencies
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
async def get_module_info(module_path: str, project_path: str = ".") -> dict[str, Any]:
    """Get detailed information about a specific module.

    Args:
        module_path: Import path of the module (e.g., "pycodemcp.server")
        project_path: Root path of the project

    Returns:
        Detailed module information including exports, classes, functions, metrics, and dependencies
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
def list_project_structure(project_path: str = ".", max_depth: int = 3) -> dict[str, Any]:
    """List the Python project structure.

    Args:
        project_path: Root path of the project
        max_depth: Maximum directory depth to traverse

    Returns:
        Project structure with Python files and directories
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
async def find_subclasses(
    base_class: str,
    project_path: str = ".",
    include_indirect: bool = True,
    show_hierarchy: bool = False,
) -> list[dict[str, Any]]:
    """Find all classes that inherit from a given base class.

    Args:
        base_class: Name of the base class to find subclasses for
        project_path: Root path of the project
        include_indirect: Include indirect inheritance (grandchildren, etc.)
        show_hierarchy: Show the full inheritance chain

    Returns:
        List of subclasses with their locations and inheritance details

    Example:
        # Find all exception classes
        subclasses = await find_subclasses("BaseException")

        # Find direct subclasses only
        direct_only = await find_subclasses("Animal", include_indirect=False)

        # Show full inheritance hierarchy
        with_hierarchy = await find_subclasses("Model", show_hierarchy=True)
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
async def get_performance_metrics(
    metric_name: str | None = None, export_format: str = "json"
) -> dict[str, Any] | str:
    """Get performance metrics for the MCP server.

    Args:
        metric_name: Optional specific metric name to retrieve
        export_format: Output format - 'json' (default) or 'prometheus'

    Returns:
        Performance metrics in requested format

    Example:
        # Get all metrics
        metrics = await get_performance_metrics()

        # Get specific metric
        symbol_search_stats = await get_performance_metrics("find_symbol")

        # Export in Prometheus format
        prometheus_data = await get_performance_metrics(export_format="prometheus")
    """
    if export_format == "prometheus":
        return metrics.export_prometheus()

    if metric_name:
        return metrics.get_stats(metric_name)

    # Return comprehensive performance report
    return metrics.get_performance_report()


# Main entry point
if __name__ == "__main__":
    import atexit

    # Set up logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Cleanup on exit
    def cleanup() -> None:
        """Clean up all projects and watchers on exit."""
        manager = get_project_manager()
        manager.cleanup_all()
        logger.info("Cleaned up all projects and watchers")

    atexit.register(cleanup)

    # Initialize plugins for current directory
    initialize_plugins(".")

    logger.info("Starting Python Code Intelligence MCP Server with file watching")
    logger.info(f"Active plugins: {[p.name() for p in _plugins]}")

    # Run the server
    mcp.run()
