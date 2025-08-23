"""Namespace package resolution for distributed Python packages."""

import ast
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class NamespaceResolver:
    """Resolves Python namespace packages across multiple repositories."""

    def __init__(self) -> None:
        """Initialize the namespace resolver."""
        # Maps namespace to list of paths
        self.namespace_paths: dict[str, list[Path]] = {}
        # Cache of package structures
        self.package_cache: dict[str, dict] = {}

    def register_namespace(self, namespace: str, paths: list[str]) -> None:
        """Register paths for a namespace package.

        Args:
            namespace: Package namespace (e.g., "mycompany.plugins")
            paths: List of paths containing parts of this namespace
        """
        resolved_paths = []
        for path in paths:
            p = Path(path).resolve()
            if p.exists():
                resolved_paths.append(p)
                logger.info(f"Registered {namespace} at {p}")
            else:
                logger.warning(f"Path does not exist: {Path(path).as_posix()}")

        self.namespace_paths[namespace] = resolved_paths

    def discover_namespaces(self, root_paths: list[str]) -> dict[str, list[Path]]:
        """Auto-discover namespace packages across multiple repos.

        Args:
            root_paths: List of repository root paths

        Returns:
            Dictionary mapping namespaces to their paths
        """
        namespaces: dict[str, list[Path]] = {}

        for root in root_paths:
            root_path = Path(root).resolve()
            if not root_path.exists():
                continue

            # Look for __init__.py files with namespace declarations
            for init_file in root_path.rglob("__init__.py"):
                namespace = self._detect_namespace_package(init_file)
                if namespace:
                    if namespace not in namespaces:
                        namespaces[namespace] = []
                    namespaces[namespace].append(init_file.parent)

            # Also check for PEP 420 implicit namespace packages
            # (directories without __init__.py but with .py files)
            for py_file in root_path.rglob("*.py"):
                if py_file.name == "__init__.py":
                    continue

                parent = py_file.parent
                if not (parent / "__init__.py").exists():
                    # Might be a namespace package
                    namespace = self._path_to_namespace(parent, root_path)
                    if namespace and self._is_valid_namespace(namespace):
                        if namespace not in namespaces:
                            namespaces[namespace] = []
                        if parent not in namespaces[namespace]:
                            namespaces[namespace].append(parent)

        # Update our registry
        for namespace, paths in namespaces.items():
            self.namespace_paths[namespace] = paths
            logger.info(f"Discovered namespace {namespace} at {len(paths)} locations")

        return namespaces

    def _detect_namespace_package(self, init_file: Path) -> str | None:
        """Detect if an __init__.py declares a namespace package.

        Args:
            init_file: Path to __init__.py

        Returns:
            Namespace name if detected, None otherwise
        """
        try:
            content = init_file.read_text()

            # Check for various namespace package declarations
            # PEP 420 style (empty or with declare_namespace)
            if not content.strip():
                # Empty __init__.py might be namespace
                return self._path_to_namespace(init_file.parent, init_file.parent)

            # pkgutil style
            if "pkgutil" in content and "extend_path" in content:
                return self._extract_namespace_from_init(init_file)

            # pkg_resources style
            if "declare_namespace" in content:
                return self._extract_namespace_from_init(init_file)

            # Check for __path__ manipulation (common namespace pattern)
            if "__path__" in content:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Name) and target.id == "__path__":
                                return self._path_to_namespace(init_file.parent, init_file.parent)

        except Exception as e:
            logger.debug(f"Error checking {init_file.as_posix()}: {e}")

        return None

    def _extract_namespace_from_init(self, init_file: Path) -> str | None:
        """Extract namespace name from __init__.py content."""
        # Get the package path relative to a reasonable root
        parts: list[str] = []
        current = init_file.parent

        # Walk up the directory tree collecting package names
        while current.name and not current.name.startswith("."):
            parts.insert(0, current.name)
            parent = current.parent

            # Stop when we reach a directory that doesn't have __init__.py
            # (meaning we've left the Python package structure)
            if not (parent / "__init__.py").exists():
                break

            current = parent

        if parts:
            return ".".join(parts)
        return None

    def _path_to_namespace(self, path: Path, root: Path) -> str:
        """Convert a path to a namespace string."""
        try:
            relative = path.relative_to(root)
            parts = [p for p in relative.parts if not p.startswith(".")]
            return ".".join(parts)
        except ValueError:
            return path.name

    def _is_valid_namespace(self, namespace: str) -> bool:
        """Check if a string is a valid Python namespace."""
        if not namespace:
            return False
        parts = namespace.split(".")
        return all(part.isidentifier() for part in parts)

    def get_all_paths_for_import(self, import_name: str) -> list[Path]:
        """Get all possible paths for an import.

        Args:
            import_name: Import like "mycompany.auth.models"

        Returns:
            List of paths where this module might exist
        """
        paths = []

        # Check if it's a registered namespace
        parts = import_name.split(".")
        for i in range(len(parts)):
            namespace = ".".join(parts[: i + 1])
            if namespace in self.namespace_paths:
                # Add paths for this namespace
                remaining = parts[i + 1 :]
                for base_path in self.namespace_paths[namespace]:
                    if remaining:
                        full_path = base_path / Path(*remaining)
                        paths.append(full_path)
                    else:
                        paths.append(base_path)

        return paths

    def resolve_import(self, import_name: str, search_paths: list[str]) -> list[Path]:
        """Resolve an import to actual file paths.

        Args:
            import_name: Import statement like "company.auth.user"
            search_paths: Additional paths to search

        Returns:
            List of resolved file paths
        """
        resolved = []

        # First check namespace paths
        namespace_paths = self.get_all_paths_for_import(import_name)

        for path in namespace_paths:
            # Could be a module (file) or package (directory)
            py_file = path.with_suffix(".py")
            if py_file.exists():
                resolved.append(py_file)
            elif path.exists() and path.is_dir():
                init_file = path / "__init__.py"
                if init_file.exists():
                    resolved.append(init_file)

        # Also check additional search paths
        module_parts = import_name.split(".")
        for search_path in search_paths:
            base = Path(search_path)
            potential = base / Path(*module_parts)

            py_file = potential.with_suffix(".py")
            if py_file.exists():
                resolved.append(py_file)
            elif potential.exists() and potential.is_dir():
                init_file = potential / "__init__.py"
                if init_file.exists():
                    resolved.append(init_file)

        return list(set(resolved))  # Remove duplicates

    def build_namespace_map(self, root_paths: list[str]) -> dict[str, dict]:
        """Build a complete map of namespace packages.

        Args:
            root_paths: Repository root paths

        Returns:
            Hierarchical namespace structure
        """
        structure: dict[str, Any] = {}

        # Discover all namespaces
        namespaces = self.discover_namespaces(root_paths)

        for namespace, paths in namespaces.items():
            parts = namespace.split(".")
            current = structure

            for part in parts:
                if part not in current:
                    current[part] = {"__paths__": [], "__subpackages__": {}}
                current = current[part]["__subpackages__"]

            # Add paths at the appropriate level
            parent = structure
            for part in parts[:-1]:
                parent = parent[part]["__subpackages__"]
            parent[parts[-1]]["__paths__"].extend([str(p) for p in paths])

        return structure
