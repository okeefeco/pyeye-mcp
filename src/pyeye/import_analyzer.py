"""Import analysis for dependency tracking."""

import ast
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_relative_import(
    current_module: str,
    imported_module: str | None,
    level: int,
    is_package: bool = False,
) -> str | None:
    """Resolve a relative import to an absolute module path.

    Single source of truth for relative-import resolution (#426). The stable
    module-level seam (#421) so callers outside :class:`ImportAnalyzer` (e.g.
    the ``find_subclasses`` AST resolution tables in ``jedi_analyzer``) can
    resolve relative imports without reaching into a private method on an
    unrelated class. :meth:`ImportAnalyzer._resolve_relative_import` and
    :meth:`JediAnalyzer._resolve_relative_import` both delegate here.

    The anchor is the importer's **containing package**, which depends on
    whether the importer is a package ``__init__`` — this is why *is_package*
    must be passed explicitly rather than inferred from the dotted string (a
    module ``pkg.sub`` and a package ``pkg.sub`` are indistinguishable by name).
    This mirrors Python's own ``importlib`` semantics:

    - a regular module ``pkg.sub.mod`` (``is_package=False``) has containing
      package ``pkg.sub``; ``level=1`` (``.``) anchors there, each extra level
      strips one more trailing component.
    - a package ``pkg.sub`` (``is_package=True``, its ``__init__``) IS its own
      package; ``level=1`` anchors at ``pkg.sub`` itself, ``level=2`` at ``pkg``.
    - resolving above the top-level package yields ``None`` (a relative import
      that walks past the root, which Python rejects as an ``ImportError``).

    Args:
        current_module: The importer's dotted module name (for a package
            ``__init__`` this is the package name itself).
        imported_module: Relative module text after the dots (``None`` for
            ``from . import X``).
        level: Number of leading dots (0 = absolute import, returned unchanged).
        is_package: ``True`` when the importer is a package ``__init__`` (its
            name already denotes the package, so it is not stripped).

    Returns:
        Absolute module name, or ``None`` if it cannot be resolved.
    """
    if level <= 0:
        # Absolute import: the imported module is already absolute.
        return imported_module
    parts = current_module.split(".") if current_module else []
    # The containing package: a package __init__ IS its own package; a regular
    # module's package is its parent (drop the module's own trailing component).
    anchor_parts = parts if is_package else parts[:-1]
    strip = level - 1
    if strip > len(anchor_parts):
        # Walks above the top-level package — Python rejects this.
        return None
    base = anchor_parts[: len(anchor_parts) - strip] if strip else anchor_parts
    suffix = imported_module.split(".") if imported_module else []
    combined = base + suffix
    return ".".join(combined) if combined else None


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

            # A package __init__ anchors relative imports at the package itself
            # (not its parent) — pass this explicitly so nested-package
            # re-exports resolve correctly (#426).
            is_package = file_path.name == "__init__.py"

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
                        base_module = self._resolve_relative_import(
                            module_name, None, node.level, is_package
                        )
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
                            module_name, original_module, node.level, is_package
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
        self,
        current_module: str,
        imported_module: str | None,
        level: int,
        is_package: bool = False,
    ) -> str | None:
        """Resolve a relative import to absolute.

        Thin instance-method wrapper over the module-level
        :func:`resolve_relative_import` (the stable seam, #421/#426). Kept so
        existing callers/tests that reach it as a method stay unchanged.

        Args:
            current_module: Current module name (for __init__.py, this is the package name)
            imported_module: Relative module being imported (None for "from . import X")
            level: Number of parent levels (dots)
            is_package: ``True`` when the importer is a package ``__init__``.

        Returns:
            Absolute module name or None
        """
        return resolve_relative_import(current_module, imported_module, level, is_package)

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
