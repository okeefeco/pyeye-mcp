"""Dependency tracking for smart cache invalidation."""

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DependencyTracker:
    """Tracks module dependencies for smart cache invalidation."""

    def __init__(self):
        """Initialize the dependency tracker."""
        # Map from module to modules it imports
        self.imports: dict[str, set[str]] = defaultdict(set)

        # Map from module to modules that import it (reverse dependencies)
        self.imported_by: dict[str, set[str]] = defaultdict(set)

        # Map from file path to module name
        self.file_to_module: dict[Path, str] = {}

        # Map from module to file path
        self.module_to_file: dict[str, Path] = {}

        # Track which symbols are defined in which modules
        self.symbol_definitions: dict[str, set[str]] = defaultdict(set)

        # Track which symbols are imported from which modules
        self.symbol_imports: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    def add_import(self, from_module: str, to_module: str) -> None:
        """Record an import relationship.

        Args:
            from_module: Module doing the importing
            to_module: Module being imported
        """
        self.imports[from_module].add(to_module)
        self.imported_by[to_module].add(from_module)
        logger.debug(f"Tracked import: {from_module} imports {to_module}")

    def add_file_mapping(self, file_path: Path, module_name: str) -> None:
        """Map a file path to its module name.

        Args:
            file_path: Path to the Python file
            module_name: Dotted module name (e.g., 'mypackage.module')
        """
        file_path = file_path.resolve()
        self.file_to_module[file_path] = module_name
        self.module_to_file[module_name] = file_path
        logger.debug(f"Mapped {file_path} to module {module_name}")

    def add_symbol_definition(self, module_name: str, symbol_name: str) -> None:
        """Track where a symbol is defined.

        Args:
            module_name: Module containing the definition
            symbol_name: Name of the defined symbol
        """
        self.symbol_definitions[module_name].add(symbol_name)
        logger.debug(f"Symbol {symbol_name} defined in {module_name}")

    def add_symbol_import(self, from_module: str, to_module: str, symbol_name: str) -> None:
        """Track symbol-level imports.

        Args:
            from_module: Module doing the importing
            to_module: Module being imported from
            symbol_name: Specific symbol being imported
        """
        self.symbol_imports[from_module][to_module].add(symbol_name)
        self.add_import(from_module, to_module)
        logger.debug(f"{from_module} imports {symbol_name} from {to_module}")

    def get_dependents(self, module_name: str) -> set[str]:
        """Get all modules that depend on the given module.

        Args:
            module_name: Module to find dependents for

        Returns:
            Set of module names that import from the given module
        """
        return self.imported_by.get(module_name, set()).copy()

    def get_dependencies(self, module_name: str) -> set[str]:
        """Get all modules that the given module depends on.

        Args:
            module_name: Module to find dependencies for

        Returns:
            Set of module names that the given module imports
        """
        return self.imports.get(module_name, set()).copy()

    def get_affected_modules(self, file_path: Path) -> set[str]:
        """Get all modules affected by changes to a file.

        This includes:
        1. The module itself
        2. All modules that import from it (direct dependents)
        3. Transitively affected modules (configurable depth)

        Args:
            file_path: Path to the changed file

        Returns:
            Set of module names that need cache invalidation
        """
        file_path = file_path.resolve()
        affected = set()

        # Get the module name for this file
        module_name = self.file_to_module.get(file_path)
        if not module_name:
            logger.warning(f"No module mapping for {file_path}")
            return affected

        # Add the module itself
        affected.add(module_name)

        # Add all direct dependents
        dependents = self.get_dependents(module_name)
        affected.update(dependents)

        # For now, only invalidate direct dependents
        # Could be made configurable for deeper transitive invalidation
        logger.info(f"File {file_path} affects {len(affected)} modules")

        return affected

    def get_affected_symbols(
        self, module_name: str, changed_symbols: set[str] | None = None
    ) -> dict[str, set[str]]:
        """Get symbols affected by changes in a module.

        Args:
            module_name: Module that changed
            changed_symbols: Specific symbols that changed (None = all)

        Returns:
            Dict mapping module names to affected symbols in each
        """
        affected: dict[str, set[str]] = defaultdict(set)

        # If no specific symbols, assume all symbols in module changed
        if changed_symbols is None:
            changed_symbols = self.symbol_definitions.get(module_name, set())

        # Find modules that import these symbols
        for dependent_module in self.get_dependents(module_name):
            imported_symbols = self.symbol_imports.get(dependent_module, {}).get(module_name, set())

            # Find intersection of changed and imported symbols
            affected_in_dependent = imported_symbols & changed_symbols
            if affected_in_dependent:
                affected[dependent_module] = affected_in_dependent

        return affected

    def clear(self) -> None:
        """Clear all dependency tracking data."""
        self.imports.clear()
        self.imported_by.clear()
        self.file_to_module.clear()
        self.module_to_file.clear()
        self.symbol_definitions.clear()
        self.symbol_imports.clear()
        logger.info("Cleared all dependency tracking data")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about tracked dependencies.

        Returns:
            Dict with dependency statistics
        """
        return {
            "total_modules": len(self.file_to_module),
            "modules_with_imports": len(self.imports),
            "modules_imported": len(self.imported_by),
            "total_import_edges": sum(len(deps) for deps in self.imports.values()),
            "total_symbols_tracked": sum(len(syms) for syms in self.symbol_definitions.values()),
            "max_dependencies": max(len(deps) for deps in self.imports.values())
            if self.imports
            else 0,
            "max_dependents": max(len(deps) for deps in self.imported_by.values())
            if self.imported_by
            else 0,
        }
