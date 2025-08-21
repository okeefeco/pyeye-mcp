"""Import analysis for dependency tracking."""

import ast
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ImportAnalyzer:
    """Analyzes Python files to extract import relationships."""

    def __init__(self, project_path: Path):
        """Initialize the import analyzer.

        Args:
            project_path: Root path of the project
        """
        self.project_path = project_path.resolve()

    def get_module_name(self, file_path: Path) -> str | None:
        """Convert a file path to a module name.

        Args:
            file_path: Path to Python file

        Returns:
            Dotted module name or None if not in project
        """
        try:
            file_path = file_path.resolve()

            # Check if file is within project
            relative_path = file_path.relative_to(self.project_path)

            # Convert path to module name
            # Remove .py extension and convert / to .
            if relative_path.suffix == ".py":
                parts = relative_path.with_suffix("").parts

                # Handle __init__.py files
                if parts[-1] == "__init__":
                    parts = parts[:-1]

                # Skip if no parts left
                if not parts:
                    return None

                module_name = ".".join(parts)
                return module_name

        except (ValueError, AttributeError):
            # File not in project path
            return None

        return None

    def analyze_imports(self, file_path: Path) -> dict[str, Any]:
        """Analyze imports in a Python file.

        Args:
            file_path: Path to Python file

        Returns:
            Dict with import information:
                - module_name: Name of this module
                - imports: List of imported module names
                - from_imports: Dict of module -> imported names
                - symbols: List of defined symbols (classes, functions)
        """
        result = {
            "module_name": None,
            "imports": [],
            "from_imports": {},
            "symbols": [],
        }

        try:
            module_name = self.get_module_name(file_path)
            if not module_name:
                return result

            result["module_name"] = module_name

            # Read and parse the file
            with open(file_path, encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source, filename=str(file_path))

            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_name = alias.name
                        result["imports"].append(imported_name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module = node.module

                        # Handle relative imports
                        if node.level > 0:
                            # Convert relative to absolute
                            module = self._resolve_relative_import(module_name, module, node.level)

                        if module:
                            if module not in result["from_imports"]:
                                result["from_imports"][module] = []

                            for alias in node.names:
                                if alias.name != "*":
                                    result["from_imports"][module].append(alias.name)

            # Extract defined symbols (top-level only for now)
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    result["symbols"].append(node.name)
                elif isinstance(node, ast.Assign):
                    # Track module-level variables
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            result["symbols"].append(target.id)

            logger.debug(
                f"Analyzed imports for {module_name}: {len(result['imports'])} imports, {len(result['symbols'])} symbols"
            )

        except Exception as e:
            logger.warning(f"Failed to analyze imports for {file_path}: {e}")

        return result

    def _resolve_relative_import(
        self, current_module: str, imported_module: str | None, level: int
    ) -> str | None:
        """Resolve a relative import to absolute.

        Args:
            current_module: Current module name
            imported_module: Relative module being imported
            level: Number of parent levels (dots)

        Returns:
            Absolute module name or None
        """
        try:
            # Split current module into parts
            parts = current_module.split(".")

            # Go up 'level' directories
            if level > len(parts):
                return None

            base_parts = parts[:-level] if level > 0 else parts

            # Add the imported module
            if imported_module:
                return ".".join(base_parts + imported_module.split("."))
            else:
                # Import from parent package
                return ".".join(base_parts)

        except Exception:
            return None

    def build_dependency_graph(self, python_files: list[Path]) -> dict[str, Any]:
        """Build a complete dependency graph for the project.

        Args:
            python_files: List of Python files to analyze

        Returns:
            Dict with:
                - modules: Dict of module_name -> file_path
                - imports: Dict of module -> list of imported modules
                - symbols: Dict of module -> list of defined symbols
                - errors: List of files that couldn't be analyzed
        """
        graph = {
            "modules": {},
            "imports": {},
            "symbols": {},
            "errors": [],
        }

        for file_path in python_files:
            try:
                analysis = self.analyze_imports(file_path)

                if analysis["module_name"]:
                    module_name = analysis["module_name"]

                    # Track module location
                    graph["modules"][module_name] = str(file_path)

                    # Track imports
                    all_imports = set(analysis["imports"])
                    all_imports.update(analysis["from_imports"].keys())

                    if all_imports:
                        graph["imports"][module_name] = list(all_imports)

                    # Track symbols
                    if analysis["symbols"]:
                        graph["symbols"][module_name] = analysis["symbols"]

            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                graph["errors"].append(str(file_path))

        logger.info(
            f"Built dependency graph: {len(graph['modules'])} modules, {len(graph['imports'])} with imports"
        )

        return graph
