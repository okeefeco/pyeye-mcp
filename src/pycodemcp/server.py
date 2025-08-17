"""Main MCP server implementation for Python code intelligence."""

from mcp.server.fastmcp import FastMCP
import jedi
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
import json
import logging
from .project_manager import get_project_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp = FastMCP("Python Code Intelligence")


def parse_project_paths(project_path: Union[str, List[str]]) -> tuple[str, List[str]]:
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


def get_jedi_project(project_path: Union[str, List[str], Dict] = ".") -> jedi.Project:
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
def find_symbol(name: str, project_path: str = ".", fuzzy: bool = False) -> List[Dict[str, Any]]:
    """Find symbol definitions in the project.
    
    Args:
        name: Symbol name to search for
        project_path: Root path of the project to search
        fuzzy: Whether to use fuzzy matching
        
    Returns:
        List of symbol locations with file, line, column, and type
    """
    project = get_jedi_project(project_path)
    results = []
    
    try:
        # Search for the symbol
        search_results = project.search(name, all_scopes=True)
        
        for result in search_results:
            # Check if fuzzy matching or exact match
            if not fuzzy and result.name != name:
                continue
                
            results.append({
                "name": result.name,
                "file": str(result.module_path) if result.module_path else None,
                "line": result.line,
                "column": result.column,
                "type": result.type,
                "description": result.description,
                "full_name": result.full_name,
            })
            
    except Exception as e:
        logger.error(f"Error searching for symbol {name}: {e}")
        
    return results


@mcp.tool()
def goto_definition(
    file: str, line: int, column: int, project_path: str = "."
) -> Optional[Dict[str, Any]]:
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
) -> List[Dict[str, Any]]:
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
                
            results.append({
                "name": ref.name,
                "file": str(ref.module_path) if ref.module_path else None,
                "line": ref.line,
                "column": ref.column,
                "is_definition": ref.is_definition(),
                "description": ref.description,
            })
            
    except Exception as e:
        logger.error(f"Error finding references: {e}")
        results.append({"error": str(e)})
        
    return results


@mcp.tool()
def get_type_info(file: str, line: int, column: int, project_path: str = ".") -> Dict[str, Any]:
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
        
        result = {
            "position": {"file": file, "line": line, "column": column},
            "inferred_types": [],
            "docstring": help_info[0].docstring() if help_info else None,
        }
        
        for inf in inferred:
            result["inferred_types"].append({
                "name": inf.name,
                "type": inf.type,
                "description": inf.description,
                "full_name": inf.full_name,
                "module_name": inf.module_name,
            })
            
        return result
        
    except Exception as e:
        logger.error(f"Error getting type info: {e}")
        return {"error": str(e)}


@mcp.tool()
def find_imports(module_name: str, project_path: str = ".") -> List[Dict[str, Any]]:
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
                        results.append({
                            "file": str(py_file),
                            "line": name.line,
                            "column": name.column,
                            "import_statement": name.description,
                            "type": name.type,
                        })
                        
            except Exception as e:
                logger.warning(f"Error processing {py_file}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error finding imports: {e}")
        
    return results


@mcp.tool()
def get_call_hierarchy(
    function_name: str, file: Optional[str] = None, project_path: str = "."
) -> Dict[str, Any]:
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
                result["callers"].append({
                    "file": str(ref.module_path) if ref.module_path else None,
                    "line": ref.line,
                    "column": ref.column,
                    "context": ref.get_line_code().strip() if hasattr(ref, 'get_line_code') else None,
                })
                
        # Find callees (functions called by this function)
        # This requires more sophisticated AST analysis
        # For now, we'll use a simplified approach
        names = script.get_names(all_scopes=False)
        for name in names:
            if name.type == "function" and name.line >= function_def.line:
                # Simple heuristic: functions referenced after our function definition
                result["callees"].append({
                    "name": name.name,
                    "type": name.type,
                    "line": name.line,
                })
                
    except Exception as e:
        logger.error(f"Error getting call hierarchy: {e}")
        return {"error": str(e)}
        
    return result


@mcp.tool()
def find_symbol_multi(
    name: str, 
    project_paths: List[str], 
    fuzzy: bool = False
) -> Dict[str, List[Dict[str, Any]]]:
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
                    
                results.append({
                    "name": result.name,
                    "file": str(result.module_path) if result.module_path else None,
                    "line": result.line,
                    "column": result.column,
                    "type": result.type,
                    "description": result.description,
                })
                
            if results:
                all_results[path] = results
                
        except Exception as e:
            logger.error(f"Error searching in {path}: {e}")
            all_results[path] = {"error": str(e)}
            
    return all_results


@mcp.tool()
def list_project_structure(project_path: str = ".", max_depth: int = 3) -> Dict[str, Any]:
    """List the Python project structure.
    
    Args:
        project_path: Root path of the project
        max_depth: Maximum directory depth to traverse
        
    Returns:
        Project structure with Python files and directories
    """
    project_root = Path(project_path)
    
    def build_tree(path: Path, current_depth: int = 0) -> Dict[str, Any]:
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
                if child.name.startswith('.') or child.name in ['__pycache__', 'node_modules']:
                    continue
                    
                # Only include Python files and directories
                if child.is_file() and not child.suffix in ['.py', '.pyx', '.pyi']:
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
    import sys
    import atexit
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Cleanup on exit
    def cleanup():
        manager = get_project_manager()
        manager.cleanup_all()
        logger.info("Cleaned up all projects and watchers")
    
    atexit.register(cleanup)
    
    logger.info("Starting Python Code Intelligence MCP Server with file watching")
    
    # Run the server
    mcp.run()