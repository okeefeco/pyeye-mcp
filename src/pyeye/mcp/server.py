"""Main MCP server implementation for PyEye."""

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
from ..validation import validate_mcp_inputs

# Configure logging
logging.basicConfig(level=logging.INFO)
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


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("configure_packages")
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
        "config_file": str(config.project_path / f".{PROJECT_NAME}.json"),
    }


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_symbol")
@track_mcp_operation("find_symbol")
async def find_symbol(
    name: str, project_path: str = ".", fuzzy: bool = False, use_config: bool = True
) -> list[dict[str, Any]]:
    """Python: Find class/function definitions. Unlike grep, follows imports and finds re-exports.

    Args:
        name: Symbol name to search for
        project_path: Root directory of the project to search
        fuzzy: Enable fuzzy matching for partial names
        use_config: Load additional packages from configuration
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
@track_mcp_operation("goto_definition")
async def goto_definition(
    file: str, line: int, column: int, project_path: str = "."
) -> dict[str, Any] | None:
    """Python: Jump to where a symbol is defined from any usage location.

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
    file: str,
    line: int,
    column: int,
    project_path: str = ".",
    include_definitions: bool = True,
    include_subclasses: bool = False,
) -> list[dict[str, Any]]:
    """Python: Find ALL usages of a symbol. Understands inheritance - grep misses subclass refs.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project
        include_definitions: Include definitions in results
        include_subclasses: Also find references to all subclasses (polymorphic search)
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.find_references(
        file, line, column, include_definitions, include_subclasses
    )


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_type_info")
async def get_type_info(
    file: str, line: int, column: int, project_path: str = ".", detailed: bool = False
) -> dict[str, Any]:
    """Python: Get type hints, docstrings, and base classes at cursor position.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project
        detailed: Include additional information like methods and attributes
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_type_info(file, line, column, detailed=detailed)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("find_imports")
async def find_imports(module_name: str, project_path: str = ".") -> list[dict[str, Any]]:
    """Python: Find all files that import a specific module.

    Args:
        module_name: Name of the module to find imports for
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.find_imports(module_name)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("get_call_hierarchy")
async def get_call_hierarchy(
    function_name: str, file: str | None = None, project_path: str = "."
) -> dict[str, Any]:
    """Python: Trace function callers and callees through the codebase.

    Args:
        function_name: Name of the function
        file: Optional file to search in (searches whole project if not specified)
        project_path: Root path of the project
    """
    analyzer = get_analyzer(project_path)
    return await analyzer.get_call_hierarchy(function_name, file)


@mcp.tool()
@validate_mcp_inputs
@metrics.measure("configure_namespace_package")
def configure_namespace_package(namespace: str, repo_paths: list[str]) -> dict[str, Any]:
    """Python: Set up namespace packages spread across multiple repositories.

    Args:
        namespace: Package namespace (e.g., "mycompany.services")
        repo_paths: List of repository paths containing parts of this namespace
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
    """Python: Find symbols within namespace packages spread across multiple repos.

    Args:
        import_path: Full import path (e.g., "mycompany.auth.models.User")
        namespace_repos: Repository paths to search
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
                                    "file": (
                                        Path(result.module_path).as_posix()
                                        if result.module_path
                                        else None
                                    ),
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
    """Python: Search for symbols across multiple projects simultaneously.

    Args:
        name: Symbol name to search for
        project_paths: List of project paths to search
        fuzzy: Whether to use fuzzy matching
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
                        "file": Path(result.module_path).as_posix() if result.module_path else None,
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
async def list_modules(project_path: str = ".") -> list[dict[str, Any]]:
    """Python: List all modules with their exports, classes, functions, and metrics.

    Args:
        project_path: Root path of the project
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
    """Python: Map module dependencies and detect circular imports. Semantic analysis grep can't do.

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
async def get_module_info(module_path: str, project_path: str = ".") -> dict[str, Any]:
    """Python: Get module exports, classes, functions, and complexity metrics.

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
async def find_subclasses(
    base_class: str,
    project_path: str = ".",
    include_indirect: bool = True,
    show_hierarchy: bool = False,
) -> list[dict[str, Any]]:
    """Python: Find inheritance tree including indirect subclasses. Impossible with grep.

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
