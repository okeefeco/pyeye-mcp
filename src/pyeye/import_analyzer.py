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
                - import_details: List of detailed import info with line numbers
                - symbols: List of defined symbols (classes, functions)
        """
        result: dict[str, Any] = {
            "module_name": None,
            "imports": [],
            "from_imports": {},
            "import_details": [],  # Detailed info including line numbers
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

            tree = ast.parse(source, filename=file_path.as_posix())

            # Extract imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_name = alias.name
                        result["imports"].append(imported_name)
                        # Track detailed info
                        result["import_details"].append(
                            {
                                "resolved_module": imported_name,
                                "line": node.lineno,
                                "column": node.col_offset,
                                "is_relative": False,
                                "level": 0,
                                "original_module": imported_name,
                            }
                        )

                elif isinstance(node, ast.ImportFrom):
                    original_module = node.module  # Can be None for "from . import X"
                    is_relative = node.level > 0

                    # Handle "from . import X" style (no module specified)
                    # In this case, each imported name is a submodule
                    if is_relative and original_module is None:
                        # Get the base package for relative import
                        base_module = self._resolve_relative_import(module_name, None, node.level)
                        if not base_module:
                            continue

                        # Each imported name is a submodule of base_module
                        for alias in node.names:
                            if alias.name != "*":
                                # Resolve to full module path
                                submodule = f"{base_module}.{alias.name}"

                                if submodule not in result["from_imports"]:
                                    result["from_imports"][submodule] = []

                                # Track as module import (not importing specific names)
                                result["import_details"].append(
                                    {
                                        "resolved_module": submodule,
                                        "line": node.lineno,
                                        "column": node.col_offset,
                                        "is_relative": True,
                                        "level": node.level,
                                        "original_module": None,
                                        "imported_names": [alias.name],
                                        "is_submodule_import": True,
                                    }
                                )
                        continue

                    # Handle relative imports with module specified (from .module import X)
                    if is_relative:
                        # Convert relative to absolute
                        resolved_module = self._resolve_relative_import(
                            module_name, original_module, node.level
                        )
                        if resolved_module:
                            module = resolved_module
                        else:
                            # Could not resolve, skip
                            continue
                    elif original_module:
                        # Absolute import: from X import Y
                        module = original_module
                    else:
                        # This shouldn't happen (level=0 and no module)
                        continue

                    if module:
                        if module not in result["from_imports"]:
                            result["from_imports"][module] = []

                        imported_names = []
                        for alias in node.names:
                            if alias.name != "*":
                                result["from_imports"][module].append(alias.name)
                                imported_names.append(alias.name)

                        # Track detailed info for from imports
                        result["import_details"].append(
                            {
                                "resolved_module": module,
                                "line": node.lineno,
                                "column": node.col_offset,
                                "is_relative": is_relative,
                                "level": node.level,
                                "original_module": original_module,
                                "imported_names": imported_names,
                            }
                        )

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
            logger.warning(f"Failed to analyze imports for {file_path.as_posix()}: {e}")

        return result

    def _resolve_relative_import(
        self, current_module: str, imported_module: str | None, level: int
    ) -> str | None:
        """Resolve a relative import to absolute.

        For a module `pkg.sub.module`:
        - level=1 (.) resolves to `pkg.sub`
        - level=2 (..) resolves to `pkg`
        - level=3 (...) resolves to parent of pkg (if exists)

        For a package `pkg.sub` (from __init__.py):
        - level=1 (.) resolves to `pkg.sub` (same package)
        - level=2 (..) resolves to `pkg`
        - level=3 (...) resolves to parent of pkg (if exists)

        Args:
            current_module: Current module name (for __init__.py, this is the package name)
            imported_module: Relative module being imported (None for "from . import X")
            level: Number of parent levels (dots)

        Returns:
            Absolute module name or None
        """
        try:
            # Split current module into parts
            parts = current_module.split(".")

            # For relative imports:
            # - level 1 goes to parent (or stays at package for __init__.py treated as package)
            # - But for packages, level 1 means "this package"
            #
            # Since __init__.py is converted to package name, we need to handle it:
            # In Python, from . import X in pkg/__init__.py imports pkg.X
            # The module name is "pkg" and level is 1
            # We need base_parts to be ["pkg"], not []
            #
            # The fix: for level=1 with a single-part module (likely __init__.py),
            # treat it as the current package, not its parent.
            # More generally, we adjust: go up (level-1) for packages, or handle differently.
            #
            # Actually, the correct logic:
            # - parts[:-level] goes up 'level' directories from the module
            # - But a module at pkg/__init__.py has name "pkg", and . should mean "pkg"
            # - A module at pkg/mod.py has name "pkg.mod", and . should mean "pkg"
            #
            # The difference: for pkg/__init__.py (name="pkg"), going up 1 gives "",
            # but it should give "pkg" because . in __init__.py means the package.
            #
            # Fix: if level > 0 and len(parts) == level, this is likely from __init__.py
            # where . means "this package". Keep the base as the first len(parts)-level+1 parts.

            if level > len(parts):
                return None

            # Adjust for __init__.py case: if we would end up with empty parts,
            # it means we're in a package's __init__.py and . refers to the package itself.
            # In this case, base_parts should be the package (all parts).
            if level > 0 and level == len(parts):
                # We're at package level, . means this package
                base_parts = parts
            elif level > 0:
                base_parts = parts[:-level]
            else:
                base_parts = parts

            # Add the imported module
            if imported_module:
                return ".".join(base_parts + imported_module.split("."))
            else:
                # Import from package (e.g., "from . import X" without module)
                return ".".join(base_parts) if base_parts else None

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
        graph: dict[str, Any] = {
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
                    graph["modules"][module_name] = file_path.as_posix()

                    # Track imports
                    all_imports = set(analysis["imports"])
                    all_imports.update(analysis["from_imports"].keys())

                    if all_imports:
                        graph["imports"][module_name] = list(all_imports)

                    # Track symbols
                    if analysis["symbols"]:
                        graph["symbols"][module_name] = analysis["symbols"]

            except Exception as e:
                logger.error(f"Failed to process {file_path.as_posix()}: {e}")
                graph["errors"].append(file_path.as_posix())

        logger.info(
            f"Built dependency graph: {len(graph['modules'])} modules, {len(graph['imports'])} with imports"
        )

        return graph
