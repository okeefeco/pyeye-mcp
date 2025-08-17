"""Main MCP server implementation for Python code intelligence."""

import logging
from pathlib import Path
from typing import Any

import jedi
from mcp.server.fastmcp import FastMCP

from .config import ProjectConfig
from .plugins.django import DjangoPlugin
from .plugins.flask import FlaskPlugin
from .plugins.pydantic import PydanticPlugin
from .project_manager import get_project_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp = FastMCP("Python Code Intelligence")

# Global plugin registry
_plugins: list[Any] = []


def initialize_plugins(project_path: str = ".") -> None:
    """Initialize plugins for the project."""
    global _plugins
    _plugins = []

    # Try to activate each plugin
    plugin_classes = [PydanticPlugin, DjangoPlugin, FlaskPlugin]

    for plugin_class in plugin_classes:
        try:
            plugin = plugin_class(project_path)  # type: ignore[abstract]
            if plugin.detect():
                _plugins.append(plugin)
                logger.info(f"Activated {plugin.name()} plugin")

                # Register plugin tools
                for tool_name, tool_func in plugin.register_tools().items():
                    # Wrap tool function to work with MCP
                    globals()[tool_name] = mcp.tool()(tool_func)

        except Exception as e:
            logger.warning(f"Failed to load plugin {plugin_class.__name__}: {e}")


def parse_project_paths(project_path: str | list[str] | dict[str, Any]) -> tuple[str, list[str]]:
    """Parse project path specification.

    Args:
        project_path: Can be:
            - Single path: "."
            - Multiple paths: [".", "../my-package"]
            - Main + deps: {"main": ".", "include": ["../my-package"]}

    Returns:
        Tuple of (main_path, include_paths)
    """
    if isinstance(project_path, dict):
        main = project_path.get("main", ".")
        include = project_path.get("include", [])
        return main, include
    elif isinstance(project_path, list):
        # First path is main, rest are includes
        if project_path:
            return project_path[0], project_path[1:]
        return ".", []
    else:
        # Single string
        return project_path, []


def get_jedi_project(project_path: str | list[str] | dict[str, Any] = ".") -> jedi.Project:
    """Get or create Jedi project for the given path(s).

    Args:
        project_path: Project path specification

    Returns:
        Configured Jedi project
    """
    main_path, include_paths = parse_project_paths(project_path)
    manager = get_project_manager()
    return manager.get_project(main_path, include_paths)


@mcp.tool()
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
    config = ProjectConfig(".")

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
def find_symbol(
    name: str, project_path: str = ".", fuzzy: bool = False, use_config: bool = True
) -> list[dict[str, Any]]:
    """Find symbol definitions in the project.

    Args:
        name: Symbol name to search for
        project_path: Root path of the project to search
        fuzzy: Whether to use fuzzy matching
        use_config: Whether to use configuration file for additional packages

    Returns:
        List of symbol locations with file, line, column, and type
    """
    # Load configuration if requested
    if use_config:
        config = ProjectConfig(project_path)
        all_paths = config.get_package_paths()
        if len(all_paths) > 1:
            # Use configured paths as a dict
            project_path_dict: dict[str, Any] = {"main": all_paths[0], "include": all_paths[1:]}
            project = get_jedi_project(project_path_dict)
        else:
            project = get_jedi_project(project_path)
    else:
        project = get_jedi_project(project_path)

    results = []
    try:
        # Search for the symbol
        search_results = project.search(name, all_scopes=True)

        for result in search_results:
            # Check if fuzzy matching or exact match
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
                    "full_name": result.full_name,
                }
            )

    except Exception as e:
        logger.error(f"Error searching for symbol {name}: {e}")

    return results


@mcp.tool()
def goto_definition(
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
    project = get_jedi_project(project_path)

    try:
        # Read the file content
        file_path = Path(file)
        if not file_path.exists():
            return {"error": f"File not found: {file}"}

        source = file_path.read_text()

        # Create script and get definitions
        script = jedi.Script(source, path=file_path, project=project)
        definitions = script.goto(line, column)

        if definitions:
            definition = definitions[0]
            return {
                "name": definition.name,
                "file": str(definition.module_path) if definition.module_path else None,
                "line": definition.line,
                "column": definition.column,
                "type": definition.type,
                "description": definition.description,
                "docstring": definition.docstring(),
            }

    except Exception as e:
        logger.error(f"Error going to definition: {e}")
        return {"error": str(e)}

    return None


@mcp.tool()
def find_references(
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
    project = get_jedi_project(project_path)
    results = []

    try:
        # Read the file content
        file_path = Path(file)
        if not file_path.exists():
            return [{"error": f"File not found: {file}"}]

        source = file_path.read_text()

        # Create script and get references
        script = jedi.Script(source, path=file_path, project=project)
        references = script.get_references(line, column, include_builtins=False)

        for ref in references:
            # Skip definitions if not requested
            if not include_definitions and ref.is_definition():
                continue

            results.append(
                {
                    "name": ref.name,
                    "file": str(ref.module_path) if ref.module_path else None,
                    "line": ref.line,
                    "column": ref.column,
                    "is_definition": ref.is_definition(),
                    "description": ref.description,
                }
            )

    except Exception as e:
        logger.error(f"Error finding references: {e}")
        results.append({"error": str(e)})

    return results


@mcp.tool()
def get_type_info(file: str, line: int, column: int, project_path: str = ".") -> dict[str, Any]:
    """Get type information at a specific position.

    Args:
        file: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)
        project_path: Root path of the project

    Returns:
        Type information including inferred type and docstring
    """
    project = get_jedi_project(project_path)

    try:
        # Read the file content
        file_path = Path(file)
        if not file_path.exists():
            return {"error": f"File not found: {file}"}

        source = file_path.read_text()

        # Create script and get type info
        script = jedi.Script(source, path=file_path, project=project)

        # Get inferred type
        inferred = script.infer(line, column)

        # Get help/hover info
        help_info = script.help(line, column)

        result: dict[str, Any] = {
            "position": {"file": file, "line": line, "column": column},
            "inferred_types": [],
            "docstring": help_info[0].docstring() if help_info else None,
        }

        for inf in inferred:
            result["inferred_types"].append(
                {
                    "name": inf.name,
                    "type": inf.type,
                    "description": inf.description,
                    "full_name": inf.full_name,
                    "module_name": inf.module_name,
                }
            )

        return result

    except Exception as e:
        logger.error(f"Error getting type info: {e}")
        return {"error": str(e)}


@mcp.tool()
def find_imports(module_name: str, project_path: str = ".") -> list[dict[str, Any]]:
    """Find all imports of a specific module in the project.

    Args:
        module_name: Name of the module to find imports for
        project_path: Root path of the project

    Returns:
        List of import locations
    """
    project = get_jedi_project(project_path)
    results = []

    try:
        # Search for import statements
        # This is a simplified implementation - could be enhanced with AST parsing
        project_root = Path(project_path)

        for py_file in project_root.rglob("*.py"):
            try:
                source = py_file.read_text()
                script = jedi.Script(source, path=py_file, project=project)

                # Get all names in the file
                names = script.get_names(all_scopes=True, definitions=True, references=True)

                for name in names:
                    # Check if it's an import of our module
                    if name.type in ["module", "import"] and module_name in name.full_name:
                        results.append(
                            {
                                "file": str(py_file),
                                "line": name.line,
                                "column": name.column,
                                "import_statement": name.description,
                                "type": name.type,
                            }
                        )

            except Exception as e:
                logger.warning(f"Error processing {py_file}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error finding imports: {e}")

    return results


@mcp.tool()
def get_call_hierarchy(
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
    project = get_jedi_project(project_path)

    result = {
        "function": function_name,
        "callers": [],
        "callees": [],
    }

    try:
        # First find the function definition
        search_results = project.search(function_name, all_scopes=True)

        function_def = None
        for res in search_results:
            if res.type == "function" and (file is None or str(res.module_path) == file):
                function_def = res
                break

        if not function_def or not function_def.module_path:
            return {"error": f"Function {function_name} not found"}

        # Get the function's source
        source = function_def.module_path.read_text()
        script = jedi.Script(source, path=function_def.module_path, project=project)

        # Find references (callers)
        refs = script.get_references(function_def.line, function_def.column)
        for ref in refs:
            if not ref.is_definition():
                callers_list = result.get("callers", [])
                if isinstance(callers_list, list):
                    callers_list.append(
                        {
                            "file": str(ref.module_path) if ref.module_path else None,
                            "line": ref.line,
                            "column": ref.column,
                            "context": (
                                ref.get_line_code().strip()
                                if hasattr(ref, "get_line_code")
                                else None
                            ),
                        }
                    )

        # Find callees (functions called by this function)
        # This requires more sophisticated AST analysis
        # For now, we'll use a simplified approach
        names = script.get_names(all_scopes=False)
        for name in names:
            if name.type == "function" and name.line >= function_def.line:
                # Simple heuristic: functions referenced after our function definition
                callees_list = result.get("callees", [])
                if isinstance(callees_list, list):
                    callees_list.append(
                        {
                            "name": name.name,
                            "type": name.type,
                            "line": name.line,
                        }
                    )

    except Exception as e:
        logger.error(f"Error getting call hierarchy: {e}")
        return {"error": str(e)}

    return result


@mcp.tool()
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
                logger.error(f"Error searching in {path}: {e}")

    # Add namespace structure
    results["namespace_structure"] = resolver.build_namespace_map(namespace_repos)

    return results


@mcp.tool()
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
            logger.error(f"Error searching in {path}: {e}")
            all_results[path] = [{"error": str(e)}]

    return all_results


@mcp.tool()
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
