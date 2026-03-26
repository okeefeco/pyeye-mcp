"""Jedi-based analyzer for PyEye."""

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any

import jedi

from ..async_utils import read_file_async, rglob_async, ripgrep_async
from ..config import ProjectConfig
from ..dependency_tracker import DependencyTracker
from ..exceptions import AnalysisError, FileAccessError, ProjectNotFoundError
from ..import_analyzer import ImportAnalyzer
from ..scope_utils import (
    LazyNamespaceLoader,
    ScopedCache,
    ScopeDebugger,
    ScopeValidator,
    SmartScopeResolver,
    parallel_search,
)
from ..symbol_parser import get_parent_and_member, is_compound_symbol, parse_compound_symbol

logger = logging.getLogger(__name__)

# Type alias for scope specification
Scope = str | list[str]


class JediAnalyzer:
    """Wrapper around Jedi for semantic Python analysis."""

    def __init__(self, project_path: str = ".", config: ProjectConfig | None = None):
        """Initialize the Jedi analyzer.

        Args:
            project_path: Root path of the project to analyze
            config: Optional project configuration for smart defaults

        Raises:
            ProjectNotFoundError: If the project path doesn't exist
        """
        self.project_path = Path(project_path)
        self.additional_paths: list[Path] = []  # For additional package paths
        self.namespace_paths: dict[str, list[Path]] = {}  # For namespace packages
        self.standalone_paths: list[Path] = []  # For standalone script directories
        self.source_roots: list[Path] = []  # For src-layout roots (e.g., src/)
        self._additional_projects: dict[Path, jedi.Project] = {}  # Cached Jedi projects
        self.config = config

        # Initialize scope utilities
        self.smart_resolver = SmartScopeResolver(config)
        self.scoped_cache = ScopedCache(ttl_seconds=300)
        self.lazy_loader = LazyNamespaceLoader()
        self.scope_debugger = ScopeDebugger(self._resolve_scope_to_paths)

        # Validator will be initialized after paths are set
        self.scope_validator: ScopeValidator | None = None

        # Validate project path exists
        if not self.project_path.exists():
            raise ProjectNotFoundError(self.project_path.as_posix())

        try:
            # Get additional sys paths from config (e.g., src/ layout detection)
            added_sys_path: list[str] | None = None
            if config:
                package_paths = config.get_package_paths()
                # Filter to paths that are subdirectories of the project (like src/)
                # These need to be added to sys.path for proper module resolution
                additional = []
                # Resolve project path for consistent comparison (handles Windows short paths)
                resolved_project = self.project_path.resolve()
                for pkg_path in package_paths:
                    pkg = Path(pkg_path).resolve()
                    # Skip the project path itself and external paths
                    if pkg != resolved_project and self._is_subpath(pkg, resolved_project):
                        additional.append(pkg.as_posix())
                        logger.info(f"Adding {pkg.as_posix()} to Jedi sys path")
                if additional:
                    added_sys_path = additional
                    # Store source roots for use in import path computation
                    self.source_roots = [Path(p) for p in additional]

            # Pass POSIX string to Jedi to avoid Path object cache issues (Jedi bug with Path as dict keys)
            # Using as_posix() ensures cross-platform compatibility with forward slashes
            # Only pass added_sys_path if we have paths (Jedi doesn't accept None)
            if added_sys_path:
                self.project = jedi.Project(
                    path=self.project_path.as_posix(),
                    added_sys_path=added_sys_path,
                )
            else:
                self.project = jedi.Project(path=self.project_path.as_posix())
            logger.info(f"Initialized JediAnalyzer for {self.project_path.as_posix()}")
        except Exception as e:
            logger.error(f"Failed to initialize Jedi project: {e}")
            raise AnalysisError(
                f"Failed to initialize analyzer for {self.project_path.as_posix()}",
                file_path=self.project_path.as_posix(),
                error=str(e),
            ) from e

    def set_additional_paths(self, paths: list[Path]) -> None:
        """Set additional paths from ProjectManager.

        Args:
            paths: List of additional package paths to include in analysis
        """
        self.additional_paths = paths
        logger.info(f"Set {len(paths)} additional paths for {self.project_path}")
        self._update_validator()

    def set_namespace_paths(self, namespaces: dict[str, list[str]]) -> None:
        """Set namespace package mappings.

        Args:
            namespaces: Dictionary mapping namespace names to their paths
        """
        self.namespace_paths = {ns: [Path(p) for p in paths] for ns, paths in namespaces.items()}
        logger.info(f"Set {len(self.namespace_paths)} namespace mappings for {self.project_path}")
        self._update_validator()
        # Invalidate lazy loader cache when namespaces change
        self.lazy_loader.invalidate()

    def set_standalone_paths(self, paths: list[Path]) -> None:
        """Set standalone script directories.

        Args:
            paths: List of directories containing standalone Python scripts
        """
        self.standalone_paths = paths
        logger.info(f"Set {len(paths)} standalone script directories for {self.project_path}")
        # Invalidate cache when standalone paths change
        self.scoped_cache.invalidate_all()

    def _get_project_for_path(self, path: Path) -> jedi.Project:
        """Get or create a cached Jedi project for an additional path.

        Args:
            path: Filesystem path to create a Jedi project for

        Returns:
            A Jedi Project instance for the given path
        """
        resolved = path.resolve()
        if resolved not in self._additional_projects:
            self._additional_projects[resolved] = jedi.Project(path=resolved.as_posix())
        return self._additional_projects[resolved]

    async def _search_all_scopes(self, name: str, scope: Scope | None = None) -> list[Any]:
        """Search for a symbol name across all configured scopes.

        Uses Jedi project.search() on the main project, then searches
        additional and namespace paths. Deduplicates by (name, file, line).

        Args:
            name: Symbol name to search for
            scope: Search scope - "main", "all", "namespace:name", etc.
                   Defaults to "all" if not specified.

        Returns:
            List of Jedi Name objects from all matching scopes
        """
        effective_scope = scope if scope is not None else "all"
        search_paths = await self._resolve_scope_to_paths(effective_scope)

        results: list[Any] = []
        seen: set[tuple[str, str, int]] = set()

        for path in search_paths:
            is_main = path == self.project_path
            try:
                project = self.project if is_main else self._get_project_for_path(path)

                for r in project.search(name, all_scopes=True):
                    key = (r.name, str(r.module_path), r.line)
                    if key not in seen:
                        seen.add(key)
                        results.append(r)
            except Exception as e:
                if is_main:
                    # Let main project errors propagate for proper error handling
                    raise
                logger.debug(f"Could not search {path}: {e}")

        return results

    def _update_validator(self) -> None:
        """Update the scope validator with current configuration."""
        scope_aliases = self.config.get_scope_aliases() if self.config else {}
        self.scope_validator = ScopeValidator(
            self.namespace_paths, self.additional_paths, scope_aliases
        )

    @staticmethod
    def _is_subpath(path: Path, parent: Path) -> bool:
        """Check if path is a subdirectory of parent.

        Args:
            path: The path to check
            parent: The potential parent path

        Returns:
            True if path is under parent, False otherwise
        """
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    async def get_project_files(
        self,
        pattern: str = "*.py",
        scope: Scope | None = None,
        method_name: str | None = None,
    ) -> list[Path]:
        """Get files from project based on scope specification.

        Args:
            pattern: File pattern to search for (e.g., "*.py", "test_*.py")
            scope: Search scope specification - can be:
                - "main": Just the main project
                - "all": Everything configured (default) - includes standalone scripts
                - "packages": All configured packages excluding main
                - "standalone": Only standalone script directories
                - "namespace:name": Specific namespace (e.g., "namespace:aac")
                - "namespace:name.sub": Sub-namespace (e.g., "namespace:aac.tools")
                - "package:path": Specific package path
                - List of scopes: Multiple scopes combined
                - None: Use smart default based on method_name
            method_name: Name of the calling method (for smart defaults)

        Returns:
            List of matching file paths

        Examples:
            # Get all Python files in main project only
            files = await analyzer.get_project_files(scope="main")

            # Get test files from a specific namespace
            files = await analyzer.get_project_files("test_*.py", "namespace:mycompany.tests")

            # Get files from multiple scopes
            files = await analyzer.get_project_files(scope=["main", "namespace:utils"])

            # Use smart defaults
            files = await analyzer.get_project_files(method_name="list_modules")
        """
        # Apply smart defaults if no scope specified
        if scope is None and method_name:
            scope = self.smart_resolver.get_smart_default(method_name)
        elif scope is None:
            scope = "all"  # Fallback default

        # Resolve aliases
        scope = self.smart_resolver.resolve_aliases(scope)

        # Check cache first
        cache_key = f"files:{pattern}"
        cached = self.scoped_cache.get(cache_key, scope)
        if cached is not None:
            return list(cached) if isinstance(cached, list) else []

        search_paths = await self._resolve_scope_to_paths(scope)

        # Use parallel search for better performance
        unique_files = await parallel_search(pattern, list(search_paths))

        # Cache the result
        self.scoped_cache.set(cache_key, unique_files, scope)

        return unique_files

    async def _resolve_scope_to_paths(self, scope: Scope) -> set[Path]:
        """Resolve scope specification to actual filesystem paths.

        Args:
            scope: Scope specification (string or list of strings)

        Returns:
            Set of filesystem paths to search
        """
        paths = set()

        # Normalize to list for uniform processing
        scopes = [scope] if isinstance(scope, str) else scope

        for s in scopes:
            if s == "main":
                # Just the main project
                paths.add(self.project_path)

            elif s == "all":
                # Everything: main + packages + namespaces + standalone
                paths.add(self.project_path)
                paths.update(self.additional_paths)
                # Add all namespace paths
                for ns_paths in self.namespace_paths.values():
                    for ns_path in ns_paths:
                        # For namespace packages, add the proper subdirectory
                        paths.update(self._get_namespace_directory_structure(ns_path))
                # Add standalone directories
                paths.update(self.standalone_paths)

            elif s == "packages":
                # All configured packages excluding main
                paths.update(self.additional_paths)

            elif s == "standalone":
                # Only standalone script directories
                paths.update(self.standalone_paths)

            elif s.startswith("namespace:"):
                # Specific namespace or sub-namespace
                ns_name = s[10:]  # Remove "namespace:" prefix
                paths.update(self._resolve_namespace_scope(ns_name))

            elif s.startswith("package:"):
                # Specific package path
                pkg_path = Path(s[8:])  # Remove "package:" prefix
                if pkg_path.exists():
                    paths.add(pkg_path)
                else:
                    logger.warning(f"Package path does not exist: {pkg_path.as_posix()}")

            else:
                logger.warning(f"Unknown scope specification: {s}")

        return paths

    def _resolve_namespace_scope(self, namespace: str) -> set[Path]:
        """Resolve a namespace specification to paths.

        Args:
            namespace: Namespace name (e.g., "aac" or "aac.tools")

        Returns:
            Set of paths for this namespace
        """
        paths = set()

        # Check for exact namespace match
        if namespace in self.namespace_paths:
            for ns_path in self.namespace_paths[namespace]:
                paths.update(self._get_namespace_directory_structure(ns_path))

        # Check for parent namespace (e.g., "aac" when looking for "aac.tools")
        parts = namespace.split(".")
        for i in range(len(parts)):
            parent_ns = ".".join(parts[: i + 1])
            if parent_ns in self.namespace_paths:
                # Build the sub-namespace path
                sub_parts = parts[i + 1 :]
                for ns_path in self.namespace_paths[parent_ns]:
                    # For namespace packages, the namespace name is typically a subdirectory
                    base_path = self._get_namespace_base_path(ns_path, parent_ns)
                    if sub_parts:
                        full_path = base_path / Path(*sub_parts)
                        if full_path.exists():
                            paths.add(full_path)
                    else:
                        paths.add(base_path)

        return paths

    def _get_namespace_directory_structure(self, ns_path: Path) -> set[Path]:
        """Get the proper directory structure for a namespace package.

        For a namespace "aac" with path "/path/to/aac-tools", this returns
        the actual Python package directories like "/path/to/aac-tools/aac".

        Args:
            ns_path: Base path for the namespace package

        Returns:
            Set of actual package directories
        """
        paths = set()

        # Check if the namespace path itself is a package
        if (ns_path / "__init__.py").exists() or any(ns_path.glob("*.py")):
            paths.add(ns_path)

        # Look for subdirectories that are Python packages
        for subdir in ns_path.iterdir():
            if subdir.is_dir() and not subdir.name.startswith("."):
                # Check if it's a Python package
                if (subdir / "__init__.py").exists() or any(subdir.glob("*.py")):
                    paths.add(subdir)

        # If no packages found, return the base path as fallback
        if not paths:
            paths.add(ns_path)

        return paths

    def _get_import_path_for_file(self, py_file: Path) -> str | None:
        """Get the import path for a Python file.

        Args:
            py_file: Path to the Python file

        Returns:
            Import path string, or None if it can't be determined
        """
        # Try source roots first (e.g., src/ layout)
        # This ensures files in src/package/module.py return "package.module"
        # instead of "src.package.module"
        for source_root in self.source_roots:
            try:
                rel_path = py_file.relative_to(source_root)
                module_parts = list(rel_path.parts[:-1])  # directories
                if py_file.name != "__init__.py":
                    module_parts.append(py_file.stem)
                return ".".join(module_parts) if module_parts else py_file.stem
            except ValueError:
                continue

        # Try main project
        try:
            rel_path = py_file.relative_to(self.project_path)
            module_parts = list(rel_path.parts[:-1])  # directories
            if py_file.name != "__init__.py":
                module_parts.append(py_file.stem)
            return ".".join(module_parts) if module_parts else py_file.stem
        except ValueError:
            pass

        # Try namespaces
        for ns_name, ns_paths in self.namespace_paths.items():
            for ns_path in ns_paths:
                try:
                    if py_file.is_relative_to(ns_path):
                        ns_rel_path = py_file.relative_to(ns_path)
                        module_parts = list(ns_rel_path.parts[:-1])
                        if py_file.name != "__init__.py":
                            module_parts.append(py_file.stem)
                        if module_parts:
                            return f"{ns_name}.{'.'.join(module_parts)}"
                        else:
                            return py_file.stem
                except (ValueError, AttributeError):
                    continue

        return None

    def _get_namespace_base_path(self, ns_path: Path, namespace: str) -> Path:
        """Get the base path for a namespace within a repository.

        Args:
            ns_path: Repository path containing the namespace
            namespace: Namespace name

        Returns:
            Path to the namespace directory
        """
        # Try to find the namespace directory within the repository
        ns_parts = namespace.split(".")

        # Check if namespace directory exists at the repository root
        potential_path = ns_path / ns_parts[0]
        if potential_path.exists() and potential_path.is_dir():
            # Build the full namespace path
            if len(ns_parts) > 1:
                return potential_path / Path(*ns_parts[1:])
            return potential_path

        # Otherwise, assume the repository root is the namespace
        return ns_path

    async def _discover_standalone_files(
        self,
        file_pattern: str = "*.py",
        exclude_patterns: list[str] | None = None,
    ) -> list[Path]:
        """Discover standalone Python files in configured directories.

        Args:
            file_pattern: Glob pattern for files to include (default "*.py")
            exclude_patterns: List of patterns to exclude

        Returns:
            List of discovered standalone Python file paths
        """
        if not self.standalone_paths:
            return []

        if exclude_patterns is None:
            exclude_patterns = []

        # Default excludes for common non-code directories
        default_excludes = {"__pycache__", ".git", ".venv", "venv", "env", ".tox", "dist", "build"}

        discovered_files = []

        for standalone_dir in self.standalone_paths:
            if not standalone_dir.exists():
                logger.warning(f"Standalone directory does not exist: {standalone_dir.as_posix()}")
                continue

            # Get standalone config from project config
            standalone_config = self.config.get_standalone_config() if self.config else {}
            recursive = standalone_config.get("recursive", True)

            # Discover files
            pattern_to_use = standalone_config.get("file_pattern", file_pattern)

            if recursive:
                files = standalone_dir.rglob(pattern_to_use)
            else:
                files = standalone_dir.glob(pattern_to_use)

            for file_path in files:
                # Skip if it's in a package (has __init__.py in same directory)
                if (file_path.parent / "__init__.py").exists():
                    continue

                # Skip default excludes
                if any(exclude_dir in file_path.parts for exclude_dir in default_excludes):
                    continue

                # Skip user-defined excludes
                should_exclude = False
                for exclude_pattern in exclude_patterns:
                    if file_path.match(exclude_pattern):
                        should_exclude = True
                        break

                if not should_exclude:
                    discovered_files.append(file_path)

        logger.info(f"Discovered {len(discovered_files)} standalone files")
        return discovered_files

    async def find_symbol(
        self,
        name: str,
        fuzzy: bool = False,
        include_import_paths: bool = True,
        scope: Scope | None = None,
    ) -> list[dict[str, Any]]:
        """Find symbol definitions across all configured scopes.

        Searches the main project plus any configured additional packages
        and namespace packages.

        Args:
            name: Symbol name to search for (supports compound symbols like "Model.__init__")
            fuzzy: Enable fuzzy matching
            include_import_paths: Include alternative import paths for re-exported symbols
            scope: Search scope - "main", "all", "namespace:name", etc.
                   Defaults to "all" (searches everything configured).

        Returns:
            List of symbol matches with location and optional import path information
        """
        # Check if this is a compound symbol (e.g., "Model.__init__")
        if is_compound_symbol(name):
            return await self._find_compound_symbol(name, include_import_paths, scope)

        results = []

        try:
            search_results = await self._search_all_scopes(name, scope)

            for result in search_results:
                if not fuzzy and result.name != name:
                    continue

                try:
                    results.append(
                        await self._serialize_name(
                            result, include_import_paths=include_import_paths
                        )
                    )
                except Exception as e:
                    # Log but don't fail entire search for one bad result
                    logger.warning(f"Could not serialize result {result.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in find_symbol: {e}")
            # Don't raise - return partial results if any
            if not results:
                # Convert Path objects in exception to strings for serialization
                error_str = str(e)
                # Special handling for exceptions that contain Path objects
                if hasattr(e, "args") and e.args and any(isinstance(arg, Path) for arg in e.args):
                    converted_args = []
                    for arg in e.args:
                        if isinstance(arg, Path):
                            converted_args.append(arg.as_posix())
                        else:
                            converted_args.append(str(arg))
                    error_str = " ".join(converted_args) if converted_args else str(e)

                raise AnalysisError(
                    f"Failed to search for symbol '{name}'",
                    operation="find_symbol",
                    symbol=name,
                    error=error_str,
                ) from e

        return results

    async def _find_compound_symbol(
        self,
        name: str,
        include_import_paths: bool = True,
        scope: Scope | None = None,
    ) -> list[dict[str, Any]]:
        """Find compound symbol definitions (e.g., "Model.__init__").

        Args:
            name: Compound symbol name (e.g., "Model.__init__", "module.Class.method")
            include_import_paths: Include alternative import paths
            scope: Search scope - "main", "all", "namespace:name", etc.

        Returns:
            List of symbol matches with location information
        """
        results = []

        # Parse the compound symbol
        components, valid = parse_compound_symbol(name)
        if not valid:
            logger.warning(f"Invalid compound symbol: {name}")
            return []

        if len(components) < 2:
            # Not actually a compound symbol
            return await self.find_symbol(
                name, include_import_paths=include_import_paths, scope=scope
            )

        try:
            # Get parent and member names
            parent_path, member_name = get_parent_and_member(components)

            # First, find the parent symbol (class or module) across all scopes
            parent_results = await self._search_all_scopes(components[-2], scope)

            for parent_result in parent_results:
                # Check if this parent matches our full parent path
                parent_full_name = parent_result.full_name
                if parent_full_name and not parent_full_name.endswith(components[-2]):
                    continue

                # Get the parent's defined names (methods, attributes, etc.)
                try:
                    parent_names = parent_result.defined_names()

                    # Search for the member within the parent's scope
                    for defined_name in parent_names:
                        if defined_name.name == member_name:
                            # Found the member in this parent
                            try:
                                serialized = await self._serialize_name(
                                    defined_name, include_import_paths=include_import_paths
                                )
                                # Ensure the full name reflects the compound nature
                                if "full_name" in serialized:
                                    # Verify this is the right match
                                    full_name = serialized["full_name"]
                                    # Check if it matches our expected pattern
                                    if components[-2] in full_name and member_name in full_name:
                                        results.append(serialized)
                            except Exception as e:
                                logger.warning(f"Could not serialize {defined_name.name}: {e}")
                                continue
                except Exception as e:
                    logger.debug(f"Could not get defined names for {parent_result.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in _find_compound_symbol: {e}")
            # Return empty list rather than raising
            return []

        return results

    async def goto_definition(self, file: str, line: int, column: int) -> dict[str, Any] | None:
        """Get definition location from a position."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)
            definitions = script.goto(line, column)

            if definitions:
                return await self._serialize_name(definitions[0], include_docstring=True)

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in goto_definition: {e}")
            # Return None for non-critical errors (e.g., no definition found)

        return None

    async def find_references(
        self,
        file: str,
        line: int,
        column: int,
        include_definitions: bool = True,
        include_subclasses: bool = False,
    ) -> list[dict[str, Any]]:
        """Find all references to a symbol.

        This searches both the main project (via Jedi) and standalone files
        (via manual search) to find all references to the symbol at the given position.

        When the symbol is a class and include_subclasses=True, this performs a
        polymorphic search - finding references to the base class AND all its subclasses.

        Args:
            file: Path to the file containing the symbol
            line: Line number (1-indexed)
            column: Column number (0-indexed)
            include_definitions: Whether to include definitions in results
            include_subclasses: If symbol is a class, also find references to all subclasses
                (polymorphic search). Default False for backward compatibility.

        Returns:
            List of reference locations with file, line, column, and is_definition info.
            When include_subclasses=True, each result includes "referenced_class" field
            showing which class in the hierarchy the reference is for.

        Example:
            # Find references to BaseService and all its subclasses
            refs = await analyzer.find_references(
                "components.py", 40, 6, include_subclasses=True
            )
            # Returns references to BaseService, ProdService, TestService, etc.
        """
        results: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)

            # Get references from Jedi (searches main project paths)
            references = script.get_references(line, column, include_builtins=False)

            for ref in references:
                if not include_definitions and ref.is_definition():
                    continue

                serialized = await self._serialize_name(ref)
                serialized["is_definition"] = ref.is_definition()
                results.append(serialized)

            # Also search standalone files if configured
            # Jedi's get_references() won't find these because standalone directories
            # aren't in the Jedi project's sys_path
            if self.standalone_paths and references:
                # Get the symbol name from the first reference
                # All references should be to the same symbol
                symbol_name = references[0].name

                # Search each standalone file for the symbol
                standalone_files = await self._discover_standalone_files()

                # Track files we've already searched via Jedi to avoid duplicates
                searched_files = {ref.module_path for ref in references if ref.module_path}

                for standalone_file in standalone_files:
                    # Skip if already searched by Jedi
                    if standalone_file in searched_files:
                        continue

                    try:
                        standalone_source = await read_file_async(standalone_file)
                        standalone_script = jedi.Script(
                            standalone_source, path=standalone_file, project=self.project
                        )

                        # Get all names in the standalone file
                        # IMPORTANT: Include both definitions AND references (call sites)
                        names = standalone_script.get_names(
                            all_scopes=True, definitions=True, references=True
                        )

                        # Filter to only names matching our symbol
                        for name in names:
                            if name.name == symbol_name:
                                # Check if this is the same symbol by trying goto_definitions
                                # If it resolves to our original symbol, it's a reference
                                try:
                                    serialized = await self._serialize_name(name)
                                    serialized["is_definition"] = name.is_definition()

                                    # Avoid duplicates
                                    if serialized not in results:
                                        results.append(serialized)
                                except Exception as e:
                                    logger.debug(
                                        f"Error serializing name in standalone file {standalone_file}: {e}"
                                    )

                    except Exception as e:
                        logger.debug(f"Error searching standalone file {standalone_file}: {e}")

            # Polymorphic search: if symbol is a class and include_subclasses=True,
            # also find references to all subclasses
            if include_subclasses and references:
                # Check if the symbol at this position is a class
                inferred = script.infer(line, column)
                is_class = any(inf.type == "class" for inf in inferred)

                if is_class and inferred:
                    # Get the class name
                    class_name = inferred[0].name
                    logger.info(
                        f"Polymorphic search: finding references to {class_name} and all subclasses"
                    )

                    try:
                        # Find all subclasses (including indirect)
                        subclasses = await self.find_subclasses(
                            class_name, include_indirect=True, show_hierarchy=False
                        )

                        if subclasses:
                            logger.info(f"Found {len(subclasses)} subclasses of {class_name}")

                            # Track locations we've already found to avoid duplicates
                            seen_locations = {(r["file"], r["line"], r["column"]) for r in results}

                            # Find references to each subclass
                            for subclass in subclasses:
                                subclass_name = subclass["name"]
                                subclass_file = subclass["file"]
                                subclass_line = subclass["line"]
                                subclass_column = subclass["column"]

                                try:
                                    # Recursively find references to this subclass
                                    # IMPORTANT: Set include_subclasses=False to avoid infinite recursion
                                    subclass_refs = await self.find_references(
                                        subclass_file,
                                        subclass_line,
                                        subclass_column,
                                        include_definitions=include_definitions,
                                        include_subclasses=False,  # Prevent recursion
                                    )

                                    # Add subclass references to results, avoiding duplicates
                                    for ref in subclass_refs:
                                        location = (ref["file"], ref["line"], ref["column"])
                                        if location not in seen_locations:
                                            # Add metadata showing which class this reference is for
                                            ref["referenced_class"] = subclass_name
                                            results.append(ref)
                                            seen_locations.add(location)
                                        else:
                                            # Location already found - keep the most specific class
                                            # (prefer subclass over base class for same location)
                                            logger.debug(
                                                f"Duplicate reference at {location}, keeping existing"
                                            )

                                except Exception as e:
                                    logger.warning(
                                        f"Error finding references to subclass {subclass_name}: {e}"
                                    )
                                    # Continue with other subclasses
                        else:
                            logger.info(f"No subclasses found for {class_name}")

                        # Add "referenced_class" metadata to base class references
                        # (do this even if no subclasses were found)
                        for ref in results:
                            if "referenced_class" not in ref:
                                ref["referenced_class"] = class_name

                    except Exception as e:
                        logger.warning(f"Error during polymorphic search: {e}")
                        # Continue with base class references only
                        # Still add metadata
                        for ref in results:
                            if "referenced_class" not in ref:
                                ref["referenced_class"] = class_name

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in find_references: {e}")
            # Return partial results if any

        return results

    async def get_type_info(
        self,
        file: str,
        line: int,
        column: int,
        detailed: bool = False,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get type information at a specific position.

        Args:
            file: Path to the file
            line: Line number (1-indexed)
            column: Column number (0-indexed)
            detailed: Include additional information like methods and attributes
            fields: Optional list of top-level fields to include in response.
                   Valid fields: position, inferred_types, docstring
                   Example: ["position", "docstring"] returns only those fields

        Returns:
            Type information including inferred type, docstring, and for classes:
            base classes and MRO
        """
        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)

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
                type_info: dict[str, Any] = {
                    "name": inf.name,
                    "type": inf.type,
                    "description": inf.description,
                    "full_name": inf.full_name,
                    "module_name": inf.module_name,
                }

                # Add base classes and MRO for classes
                if inf.type == "class":
                    base_classes, mro = await self._get_class_inheritance_info(script, inf)
                    type_info["base_classes"] = base_classes
                    type_info["mro"] = mro

                    # Add detailed info if requested
                    if detailed:
                        type_info["methods"] = []
                        type_info["attributes"] = []

                        # Get defined names (methods and attributes)
                        try:
                            for defined in inf.defined_names():
                                if defined.type == "function":
                                    type_info["methods"].append(
                                        {
                                            "name": defined.name,
                                            "description": defined.description,
                                        }
                                    )
                                elif defined.type in ["statement", "instance"]:
                                    type_info["attributes"].append(
                                        {
                                            "name": defined.name,
                                            "type": defined.type,
                                        }
                                    )
                        except Exception:
                            # Some definitions might not support defined_names
                            pass

                result["inferred_types"].append(type_info)

            # Apply field filtering if requested
            if fields is not None:
                from ..mcp.server import filter_fields

                result = filter_fields(result, fields)  # type: ignore[assignment]

            return result

        except (FileAccessError, ValueError):
            raise  # Re-raise file access errors and validation errors
        except Exception as e:
            logger.error(f"Error getting type info: {e}")
            raise AnalysisError(
                f"Failed to get type info at {file}:{line}:{column}",
                file_path=file,
                line=line,
                error=str(e),
            ) from e

    async def find_imports(self, module_name: str, scope: Scope = "all") -> list[dict[str, Any]]:
        """Find all imports of a specific module in the project.

        Args:
            module_name: Name of the module to find imports for
            scope: Search scope (default "main" for better performance):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes

        Returns:
            List of import locations
        """
        # Check cache first
        cache_key = f"imports:{module_name}"
        cached_result = self.scoped_cache.get(cache_key, scope)
        if cached_result is not None:
            return cached_result  # type: ignore[no-any-return]

        results: list[dict[str, Any]] = []

        try:
            # Get search paths based on scope
            search_paths = []
            if scope == "main" or scope == "all" or (isinstance(scope, list) and "main" in scope):
                search_paths.append(self.project_path)

            # Add namespace paths if needed
            if (
                scope == "all"
                or (isinstance(scope, str) and scope.startswith("namespace:"))
                or (isinstance(scope, list) and any("namespace:" in s for s in scope))
            ):
                # Get namespace paths from stored namespace_paths or config
                namespaces_to_use = {}

                # First check if namespace_paths was set directly via set_namespace_paths
                if self.namespace_paths:
                    namespaces_to_use = self.namespace_paths
                # Otherwise check config
                elif self.config and self.config.config.get("namespaces"):
                    namespaces_to_use = {
                        ns: [Path(p) for p in paths]
                        for ns, paths in self.config.config["namespaces"].items()
                    }

                for namespace_name, namespace_paths in namespaces_to_use.items():
                    if scope == "all" or f"namespace:{namespace_name}" in (
                        scope if isinstance(scope, list) else [scope]
                    ):
                        for path in namespace_paths:
                            if isinstance(path, str):
                                path = Path(path).expanduser().resolve()
                            if path.exists():
                                search_paths.append(path)

            if not search_paths:
                search_paths = [self.project_path]

            # Step 1: Use ripgrep to pre-filter files containing the module name
            # Escape dots in module name for regex (dots are literal in module names)
            escaped_module = re.escape(module_name)

            # Extract the leaf module name for relative import matching
            # e.g., "anz_devenv.nodejs" -> "nodejs"
            leaf_module = module_name.split(".")[-1]
            escaped_leaf = re.escape(leaf_module)

            # Create patterns for different import styles
            import_patterns = [
                # Absolute import patterns (existing)
                f"import {escaped_module}",
                f"from {escaped_module}",
                f"import.*{escaped_module}",
                f"from.*{escaped_module}",
                # Relative import patterns (new)
                # Match "from . import nodejs" or "from .. import nodejs" etc.
                # \.+ matches one or more literal dots
                f"from \\.+ import.*\\b{escaped_leaf}\\b",
                # Match "from .nodejs import" or "from ..nodejs import"
                f"from \\.+{escaped_leaf} import",
                # Match "from .subpkg.nodejs import" or from ..subpkg.nodejs import"
                f"from \\.+\\w+\\.{escaped_leaf} import",
                # Match deeper nesting like "from .a.b.nodejs import"
                f"from \\.+[\\w.]+\\.{escaped_leaf} import",
            ]

            # Find files that might contain imports
            candidate_files = set()
            for pattern in import_patterns:
                matching_files = await ripgrep_async(
                    pattern, search_paths, include_pattern="*.py", case_sensitive=True
                )
                candidate_files.update(matching_files)

            # If no files found with ripgrep, return empty
            if not candidate_files:
                # Cache empty result
                self.scoped_cache.set(cache_key, results, scope)
                return results

            # Step 2: Use ImportAnalyzer for fast AST-based parsing
            for py_file in candidate_files:
                try:
                    # Create ImportAnalyzer for the appropriate root
                    # Try source roots first (e.g., src/ layout) to ensure
                    # modules in src/package/module.py are recognized as "package.module"
                    # instead of "src.package.module"
                    analyzer_root = None

                    # Resolve py_file to handle symlinks (e.g., /var -> /private/var on macOS)
                    py_file_resolved = py_file.resolve()

                    # First check source roots
                    for source_root in self.source_roots:
                        try:
                            # Resolve both paths for consistent comparison
                            source_root_resolved = source_root.resolve()
                            py_file_resolved.relative_to(source_root_resolved)
                            analyzer_root = source_root_resolved
                            break
                        except ValueError:
                            continue

                    # Then try project_path
                    if analyzer_root is None:
                        try:
                            project_path_resolved = self.project_path.resolve()
                            py_file_resolved.relative_to(project_path_resolved)
                            analyzer_root = project_path_resolved
                        except ValueError:
                            pass

                    # Finally check namespace paths and fall back to walking up
                    if analyzer_root is None:
                        # Check namespace paths
                        for ns_paths in self.namespace_paths.values():
                            for ns_path in ns_paths:
                                try:
                                    ns_path_resolved = (
                                        ns_path.resolve()
                                        if isinstance(ns_path, Path)
                                        else Path(ns_path).resolve()
                                    )
                                    py_file_resolved.relative_to(ns_path_resolved)
                                    analyzer_root = ns_path_resolved
                                    break
                                except ValueError:
                                    continue
                            if analyzer_root:
                                break

                    # Last resort: walk up to find appropriate root
                    if analyzer_root is None:
                        analyzer_root = py_file_resolved.parent
                        while analyzer_root.parent != analyzer_root:
                            if (analyzer_root / "__init__.py").exists() or any(
                                (analyzer_root / p).is_dir()
                                and (analyzer_root / p / "__init__.py").exists()
                                for p in ["src", "lib"]
                                if (analyzer_root / p).exists()
                            ):
                                break
                            analyzer_root = analyzer_root.parent

                    import_analyzer = ImportAnalyzer(analyzer_root)

                    # Use AST-based analysis for speed
                    import_info = import_analyzer.analyze_imports(py_file)

                    # Find matching imports using import_details (includes line numbers)
                    matching_details = []
                    for detail in import_info.get("import_details", []):
                        resolved = detail.get("resolved_module", "")
                        # Check if the resolved module matches our target
                        if resolved == module_name or resolved.startswith(f"{module_name}."):
                            matching_details.append(detail)

                    # If we found imports, extract line information using the details
                    if matching_details:
                        source = await read_file_async(py_file)
                        lines = source.splitlines()

                        for detail in matching_details:
                            line_num = detail.get("line", 0)
                            col = detail.get("column", 0)

                            # Get the actual line content
                            if 0 < line_num <= len(lines):
                                line_content = lines[line_num - 1].strip()
                            else:
                                line_content = ""

                            results.append(
                                {
                                    "file": py_file.as_posix(),
                                    "line": line_num,
                                    "column": col,
                                    "import_statement": line_content,
                                    "type": "import",
                                    "is_relative": detail.get("is_relative", False),
                                    "resolved_module": detail.get("resolved_module", ""),
                                }
                            )

                except Exception as e:
                    logger.warning(f"Error processing {py_file}: {e}")
                    continue

            # Cache the results
            self.scoped_cache.set(cache_key, results, scope)

        except Exception as e:
            logger.error(f"Error finding imports: {e}")
            raise AnalysisError(
                f"Failed to find imports of module '{module_name}'",
                module=module_name,
                error=str(e),
            ) from e

        return results

    async def get_call_hierarchy(
        self, function_name: str, file: str | None = None
    ) -> dict[str, Any]:
        """Get the call hierarchy for a function or class.

        For functions, finds callers (who calls it) and callees (what it calls).
        For classes, finds instantiation sites (callers) and what __init__ calls (callees).

        Args:
            function_name: Name of the function or class
            file: Optional file to search in (searches whole project if not specified)

        Returns:
            Call hierarchy with callers and callees
        """
        result = {
            "function": function_name,
            "callers": [],
            "callees": [],
        }

        try:
            # First find the function or class definition across all scopes
            search_results = await self._search_all_scopes(function_name)

            function_def = None
            for res in search_results:
                if res.type in ("function", "class") and (
                    file is None or str(res.module_path) == file
                ):
                    function_def = res
                    break

            if not function_def or not function_def.module_path:
                return {"error": f"Symbol {function_name} not found"}

            # Get the function's source
            source = await read_file_async(function_def.module_path)
            script = jedi.Script(
                source,
                path=(
                    function_def.module_path.as_posix()
                    if isinstance(function_def.module_path, Path)
                    else function_def.module_path
                ),
                project=self.project,
            )

            # Find references (callers)
            refs = script.get_references(function_def.line, function_def.column)
            for ref in refs:
                if not ref.is_definition():
                    callers_list = result["callers"]
                    if isinstance(callers_list, list):
                        callers_list.append(
                            {
                                "file": (
                                    Path(ref.module_path).as_posix() if ref.module_path else None
                                ),
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
                if (
                    name.type == "function"
                    and name.line >= function_def.line
                    and name.line <= function_def.line + 50
                ):  # Rough heuristic
                    # Check if this is a function call within our function
                    if name.is_definition():
                        continue
                    callees_list = result["callees"]
                    if isinstance(callees_list, list):
                        callees_list.append(
                            {
                                "name": name.name,
                                "file": (
                                    Path(name.module_path).as_posix() if name.module_path else None
                                ),
                                "line": name.line,
                                "column": name.column,
                                "type": name.type,
                            }
                        )

        except FileNotFoundError as e:
            raise ProjectNotFoundError(str(self.project_path)) from e
        except Exception as e:
            logger.error(f"Error getting call hierarchy: {e}")
            # Convert Path objects in exception to strings for serialization
            error_str = str(e)
            # Special handling for exceptions that contain Path objects (like Jedi's KeyError)
            if hasattr(e, "args") and e.args and any(isinstance(arg, Path) for arg in e.args):
                # If the exception has Path objects in args, convert them
                converted_args = []
                for arg in e.args:
                    if isinstance(arg, Path):
                        converted_args.append(arg.as_posix())
                    else:
                        converted_args.append(str(arg))
                error_str = " ".join(converted_args) if converted_args else str(e)

            raise AnalysisError(
                f"Failed to get call hierarchy for function '{function_name}'",
                function=function_name,
                file=file,
                error=error_str,
            ) from e

        return result

    async def get_completions(self, file: str, line: int, column: int) -> list[dict[str, Any]]:
        """Get code completions at a position."""
        completions: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)

            for completion in script.complete(line, column):
                completions.append(
                    {
                        "name": completion.name,
                        "complete": completion.complete,
                        "type": completion.type,
                        "description": completion.description,
                        "docstring": completion.docstring(),
                    }
                )

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in get_completions: {e}")
            # Return partial results if any

        return completions

    async def get_signature_help(self, file: str, line: int, column: int) -> dict[str, Any] | None:
        """Get signature help for function calls."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                return None

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)
            signatures = script.get_signatures(line, column)

            if signatures:
                sig = signatures[0]
                return {
                    "name": sig.name,
                    "params": [param.description for param in sig.params],
                    "index": sig.index,
                    "docstring": sig.docstring(),
                }

        except Exception as e:
            logger.error(f"Error in get_signature_help: {e}")

        return None

    async def analyze_imports(self, file: str) -> list[dict[str, Any]]:
        """Analyze imports in a file."""
        imports: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                return imports

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)

            names = script.get_names(all_scopes=True, definitions=True, references=False)

            for name in names:
                if name.type in ["module", "import"]:
                    imports.append(
                        {
                            "name": name.name,
                            "full_name": name.full_name,
                            "line": name.line,
                            "column": name.column,
                            "description": name.description,
                        }
                    )

        except Exception as e:
            logger.error(f"Error in analyze_imports: {e}")

        return imports

    async def list_packages(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """List all Python packages in the project.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes
        """
        packages: list[dict[str, Any]] = []
        seen_packages = set()

        try:
            # Walk the project directory to find packages
            init_files = await self.get_project_files("__init__.py", scope)
            for path in init_files:
                package_dir = path.parent
                # Resolve to handle symlinks (e.g., /var -> /private/var on macOS)
                package_dir_resolved = package_dir.resolve()

                # Determine package name based on which search path this file belongs to
                package_name = None
                rel_path = None

                # Try source roots first (e.g., src/ layout)
                # This ensures packages in src/package/ return "package"
                # instead of "src.package"
                for source_root in self.source_roots:
                    try:
                        # Resolve both paths for consistent comparison
                        source_root_resolved = source_root.resolve()
                        rel_path = package_dir_resolved.relative_to(source_root_resolved)
                        if rel_path == Path("."):
                            # Package is at the root of source_root
                            package_name = package_dir.name
                        else:
                            package_name = rel_path.as_posix().replace("/", ".")
                        break
                    except ValueError:
                        continue

                # Try main project if not found in source roots
                if not package_name:
                    try:
                        project_path_resolved = self.project_path.resolve()
                        rel_path = package_dir_resolved.relative_to(project_path_resolved)
                        package_name = rel_path.as_posix().replace("/", ".")
                    except ValueError:
                        pass

                # Check namespace paths if still not found
                if not package_name:
                    for ns_name, ns_paths in self.namespace_paths.items():
                        for ns_path in ns_paths:
                            try:
                                # Check if package_dir is under this namespace path
                                if package_dir.is_relative_to(ns_path):
                                    ns_rel_path = package_dir.relative_to(ns_path)
                                    if ns_rel_path == Path("."):
                                        package_name = ns_name
                                    else:
                                        package_name = (
                                            f"{ns_name}.{ns_rel_path.as_posix().replace('/', '.')}"
                                        )
                                    rel_path = ns_rel_path
                                    break
                            except (ValueError, AttributeError):
                                continue
                        if package_name:
                            break

                if not package_name:
                    # Skip if we can't determine the package name
                    continue

                # Skip hidden directories and common non-package directories
                if rel_path:
                    parts = rel_path.parts
                    if any(
                        p.startswith(".") or p in ["__pycache__", "build", "dist", "egg-info"]
                        for p in parts
                    ):
                        continue
                if package_name not in seen_packages:
                    seen_packages.add(package_name)

                    # Find subpackages and modules
                    subpackages = []
                    modules = []

                    for item in package_dir.iterdir():
                        if item.is_dir() and (item / "__init__.py").exists():
                            subpackages.append(item.name)
                        elif item.is_file() and item.suffix == ".py" and item.name != "__init__.py":
                            modules.append(item.stem)

                    packages.append(
                        {
                            "name": package_name,
                            "path": package_dir.as_posix(),
                            "is_namespace": not (package_dir / "__init__.py").exists(),
                            "subpackages": sorted(subpackages),
                            "modules": sorted(modules),
                        }
                    )

            # Sort packages by name
            packages.sort(key=lambda p: str(p["name"]))

        except Exception as e:
            logger.error(f"Error in list_packages: {e}")
            raise AnalysisError(
                "Failed to list packages", operation="list_packages", error=str(e)
            ) from e

        return packages

    async def list_modules(self, scope: Scope = "main") -> list[dict[str, Any]]:
        """List all Python modules with exports and metrics.

        Args:
            scope: Search scope (default "main"):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes
        """
        modules = []

        try:
            # Find all Python files in the project
            py_files = await self.get_project_files("*.py", scope)
            for py_file in py_files:
                # Resolve to handle symlinks (e.g., /var -> /private/var on macOS)
                py_file_resolved = py_file.resolve()

                # Determine import path based on which search path this file belongs to
                import_path = None
                rel_path = None

                # Try source roots first (e.g., src/ layout)
                # This ensures modules in src/package/module.py return "package.module"
                # instead of "src.package.module"
                for source_root in self.source_roots:
                    try:
                        # Resolve both paths for consistent comparison
                        source_root_resolved = source_root.resolve()
                        rel_path = py_file_resolved.relative_to(source_root_resolved)
                        module_parts = list(rel_path.parts[:-1])  # directories
                        if py_file.name != "__init__.py":
                            module_parts.append(py_file.stem)
                        import_path = ".".join(module_parts) if module_parts else py_file.stem
                        break
                    except ValueError:
                        continue

                # Try main project if not found in source roots
                if not import_path:
                    try:
                        project_path_resolved = self.project_path.resolve()
                        rel_path = py_file_resolved.relative_to(project_path_resolved)
                        module_parts = list(rel_path.parts[:-1])  # directories
                        if py_file.name != "__init__.py":
                            module_parts.append(py_file.stem)
                        import_path = ".".join(module_parts) if module_parts else py_file.stem
                    except ValueError:
                        pass

                # Check namespace paths if still not found
                if not import_path:
                    for ns_name, ns_paths in self.namespace_paths.items():
                        for ns_path in ns_paths:
                            try:
                                ns_path_resolved = (
                                    ns_path.resolve()
                                    if isinstance(ns_path, Path)
                                    else Path(ns_path).resolve()
                                )
                                if py_file_resolved.is_relative_to(ns_path_resolved):
                                    ns_rel_path = py_file_resolved.relative_to(ns_path_resolved)
                                    module_parts = list(ns_rel_path.parts[:-1])
                                    if py_file.name != "__init__.py":
                                        module_parts.append(py_file.stem)
                                    if module_parts:
                                        import_path = f"{ns_name}.{'.'.join(module_parts)}"
                                    else:
                                        import_path = py_file.stem
                                    rel_path = ns_rel_path
                                    break
                            except (ValueError, AttributeError):
                                continue
                        if import_path:
                            break

                if not import_path:
                    # Skip if we can't determine the import path
                    continue

                # Skip hidden directories and common non-source directories
                if rel_path:
                    parts = rel_path.parts
                    if any(
                        p.startswith(".") or p in ["__pycache__", "build", "dist", "tests", "test"]
                        for p in parts[:-1]
                    ):
                        continue

                try:
                    # Read file for analysis
                    source = await read_file_async(py_file)
                    lines = source.count("\n") + 1

                    # Parse with AST to extract structure
                    tree = ast.parse(source)

                    exports = []
                    classes = []
                    functions = []
                    imports_from = set()

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            classes.append(node.name)
                            exports.append(node.name)
                        elif isinstance(node, ast.FunctionDef):
                            if not node.name.startswith("_"):  # Public functions
                                functions.append(node.name)
                                exports.append(node.name)
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                imports_from.add(alias.name.split(".")[0])
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports_from.add(node.module.split(".")[0])

                    # Check if has tests
                    test_patterns = ["test_" + py_file.stem, py_file.stem + "_test"]
                    has_tests = False
                    tests_dir = self.project_path / "tests"
                    if tests_dir.exists():
                        for pattern in test_patterns:
                            test_files = await rglob_async(f"{pattern}.py", tests_dir)
                            if test_files:
                                has_tests = True
                                break

                    modules.append(
                        {
                            "name": py_file.stem if py_file.name != "__init__.py" else "__init__",
                            "import_path": import_path,
                            "file": py_file.as_posix(),
                            "exports": sorted(exports),
                            "classes": sorted(classes),
                            "functions": sorted(functions),
                            "imports_from": sorted(imports_from),
                            "size_lines": lines,
                            "has_tests": has_tests,
                        }
                    )

                except Exception as e:
                    logger.warning(f"Could not analyze module {py_file}: {e}")
                    continue

            # Sort modules by import path
            modules.sort(key=lambda m: str(m["import_path"]))

        except Exception as e:
            logger.error(f"Error in list_modules: {e}")
            raise AnalysisError(
                "Failed to list modules", operation="list_modules", error=str(e)
            ) from e

        return modules

    async def analyze_dependencies(
        self, module_path: str, scope: Scope = "all", _visited: set[str] | None = None
    ) -> dict[str, Any]:
        """Analyze import dependencies for a module.

        Args:
            module_path: The module to analyze dependencies for
            scope: Search scope (default "all"):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes
            _visited: Internal parameter for recursion tracking
        """
        result: dict[str, Any] = {
            "module": module_path,
            "imports": {"internal": [], "external": [], "stdlib": []},
            "imported_by": [],
            "circular_dependencies": [],
        }

        try:
            # Find the module file
            module_file = None
            module_parts = module_path.split(".")

            # Try different possible paths
            # First check source roots (e.g., src/ layout), then project root
            search_roots = list(self.source_roots) + [self.project_path]

            for root in search_roots:
                possible_paths = [
                    root / Path(*module_parts[:-1]) / f"{module_parts[-1]}.py",
                    root / Path(*module_parts) / "__init__.py",
                    root / f"{module_path.replace('.', os.sep)}.py",
                ]

                for path in possible_paths:
                    if path.exists():
                        module_file = path
                        break
                if module_file:
                    break

            if not module_file:
                raise FileAccessError(f"Module not found: {module_path}", module_path, "read")

            # Analyze imports in this module
            source = await read_file_async(module_file)
            tree = ast.parse(source)

            # Standard library modules (common ones, not exhaustive)
            stdlib_modules = {
                "os",
                "sys",
                "re",
                "json",
                "math",
                "random",
                "datetime",
                "collections",
                "itertools",
                "functools",
                "pathlib",
                "typing",
                "enum",
                "dataclasses",
                "logging",
                "argparse",
                "subprocess",
                "threading",
                "multiprocessing",
                "urllib",
                "http",
                "socket",
                "ssl",
                "hashlib",
                "hmac",
                "base64",
                "pickle",
                "csv",
                "xml",
                "html",
                "email",
                "sqlite3",
                "asyncio",
                "contextlib",
                "tempfile",
                "shutil",
                "glob",
                "fnmatch",
                "platform",
            }

            # Get project modules for internal/external classification
            project_modules = set()
            py_files = await self.get_project_files("*.py", scope)
            for py_file in py_files:
                # Determine the module root based on which search path this file belongs to
                module_root = None
                rel_path = None

                try:
                    rel_path = py_file.relative_to(self.project_path)
                    module_parts = list(rel_path.parts[:-1])
                    if py_file.name != "__init__.py":
                        module_parts.append(py_file.stem)
                    if module_parts:
                        module_root = module_parts[0]
                except ValueError:
                    # Not under main project, check namespaces
                    for ns_name, ns_paths in self.namespace_paths.items():
                        for ns_path in ns_paths:
                            try:
                                if py_file.is_relative_to(ns_path):
                                    rel_path = py_file.relative_to(ns_path)
                                    module_root = ns_name
                                    break
                            except (ValueError, AttributeError):
                                continue
                        if module_root:
                            break

                if module_root and rel_path:
                    if not any(
                        p.startswith(".") or p in ["__pycache__", "build", "dist"]
                        for p in rel_path.parts
                    ):
                        project_modules.add(module_root)

            # Analyze imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split(".")[0]
                        if module_name in stdlib_modules:
                            result["imports"]["stdlib"].append(alias.name)
                        elif module_name in project_modules:
                            result["imports"]["internal"].append(alias.name)
                        else:
                            result["imports"]["external"].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        module_name = node.module.split(".")[0]
                        if module_name in stdlib_modules:
                            result["imports"]["stdlib"].append(node.module)
                        elif module_name in project_modules:
                            result["imports"]["internal"].append(node.module)
                        else:
                            result["imports"]["external"].append(node.module)

            # Remove duplicates and sort
            stdlib_imports = result["imports"]["stdlib"]
            internal_imports = result["imports"]["internal"]
            external_imports = result["imports"]["external"]
            result["imports"]["stdlib"] = sorted(set(stdlib_imports))
            result["imports"]["internal"] = sorted(set(internal_imports))
            result["imports"]["external"] = sorted(set(external_imports))

            # Find what imports this module
            py_files = await self.get_project_files("*.py", scope)
            for py_file in py_files:
                if py_file == module_file:
                    continue

                try:
                    source = await read_file_async(py_file)
                    if module_path in source or module_path.replace(".", "/") in source:
                        # More precise check with AST
                        tree = ast.parse(source)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    if alias.name == module_path or alias.name.startswith(
                                        module_path + "."
                                    ):
                                        import_path = self._get_import_path_for_file(py_file)
                                        if import_path:
                                            result["imported_by"].append(import_path)
                                        break
                            elif isinstance(node, ast.ImportFrom):
                                if node.module and (
                                    node.module == module_path
                                    or node.module.startswith(module_path + ".")
                                ):
                                    import_path = self._get_import_path_for_file(py_file)
                                    if import_path:
                                        result["imported_by"].append(import_path)
                                    break
                except Exception as e:
                    logger.warning(f"Could not analyze {py_file} for imports: {e}")
                    continue

            result["imported_by"] = sorted(set(result["imported_by"]))

            # Check for circular dependencies
            # Use visited set to prevent infinite recursion
            if _visited is None:
                _visited = set()

            if module_path not in _visited:
                _visited.add(module_path)
                for imported_module in result["imports"]["internal"]:
                    # Skip if we've already visited this module to avoid infinite recursion
                    if imported_module not in _visited:
                        # Check if the imported module also imports this module
                        try:
                            deps = await self.analyze_dependencies(
                                imported_module, scope=scope, _visited=_visited
                            )
                            if module_path in deps["imports"]["internal"]:
                                result["circular_dependencies"].append(imported_module)
                        except Exception:
                            # Ignore errors in recursive analysis
                            pass

        except FileAccessError:
            raise
        except Exception as e:
            logger.error(f"Error in analyze_dependencies: {e}")
            raise AnalysisError(
                f"Failed to analyze dependencies for {module_path}",
                operation="analyze_dependencies",
                error=str(e),
            ) from e

        return result

    async def get_module_info(self, module_path: str) -> dict[str, Any]:
        """Get detailed information about a specific module."""
        info: dict[str, Any] = {
            "module": module_path,
            "file": None,
            "docstring": None,
            "exports": [],
            "classes": [],
            "functions": [],
            "variables": [],
            "imports": [],
            "metrics": {"lines": 0, "classes": 0, "functions": 0, "complexity": 0},
            "dependencies": None,
        }

        try:
            # Find the module file
            module_file = None
            module_parts = module_path.split(".")

            # Try different possible paths
            # First check source roots (e.g., src/ layout), then project root
            search_roots = list(self.source_roots) + [self.project_path]

            for root in search_roots:
                possible_paths = [
                    root / Path(*module_parts[:-1]) / f"{module_parts[-1]}.py",
                    root / Path(*module_parts) / "__init__.py",
                    root / f"{module_path.replace('.', os.sep)}.py",
                ]

                for path in possible_paths:
                    if path.exists():
                        module_file = path
                        break
                if module_file:
                    break

            if not module_file:
                raise FileAccessError(f"Module not found: {module_path}", module_path, "read")

            info["file"] = module_file.as_posix()

            # Read and parse the module
            source = await read_file_async(module_file)
            info["metrics"]["lines"] = source.count("\n") + 1

            tree = ast.parse(source)

            # Get module docstring
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
            ):
                info["docstring"] = tree.body[0].value.value

            # Analyze module contents
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_info: dict[str, Any] = {
                        "name": node.name,
                        "line": node.lineno,
                        "methods": [],
                        "docstring": ast.get_docstring(node),
                    }

                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            class_info["methods"].append(
                                {
                                    "name": item.name,
                                    "line": item.lineno,
                                    "is_private": item.name.startswith("_"),
                                }
                            )

                    info["classes"].append(class_info)
                    info["exports"].append(node.name)
                    info["metrics"]["classes"] += 1

                elif isinstance(node, ast.FunctionDef):
                    func_info = {
                        "name": node.name,
                        "line": node.lineno,
                        "args": [arg.arg for arg in node.args.args],
                        "docstring": ast.get_docstring(node),
                        "is_private": node.name.startswith("_"),
                    }
                    info["functions"].append(func_info)
                    if not node.name.startswith("_"):
                        info["exports"].append(node.name)
                    info["metrics"]["functions"] += 1

                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if not target.id.startswith("_"):
                                info["variables"].append({"name": target.id, "line": node.lineno})
                                info["exports"].append(target.id)

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        info["imports"].append(
                            {"module": alias.name, "alias": alias.asname, "line": node.lineno}
                        )

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for alias in node.names:
                            info["imports"].append(
                                {
                                    "module": node.module,
                                    "name": alias.name,
                                    "alias": alias.asname,
                                    "line": node.lineno,
                                }
                            )

            # Calculate cyclomatic complexity (simplified)
            complexity = 1  # Base complexity
            for ast_node in ast.walk(tree):
                if isinstance(ast_node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                    complexity += 1
                elif isinstance(ast_node, ast.BoolOp):
                    complexity += len(ast_node.values) - 1
            info["metrics"]["complexity"] = complexity

            # Get dependency information
            info["dependencies"] = await self.analyze_dependencies(module_path)

        except FileAccessError:
            raise
        except Exception as e:
            logger.error(f"Error in get_module_info: {e}")
            raise AnalysisError(
                f"Failed to get module info for {module_path}",
                operation="get_module_info",
                error=str(e),
            ) from e

        return info

    async def _serialize_name(
        self,
        name: jedi.api.classes.Name,
        include_docstring: bool = False,
        include_import_paths: bool = False,
    ) -> dict[str, Any]:
        """Serialize a Jedi Name object to a dictionary."""
        result = {
            "name": name.name,
            "type": name.type,
            "line": name.line,
            "column": name.column,
            "description": name.description,
            "full_name": name.full_name,
        }

        if name.module_path:
            result["file"] = Path(name.module_path).as_posix()

        if include_docstring:
            result["docstring"] = name.docstring()

        # Add import paths if requested and we have module information
        if include_import_paths and name.full_name:
            # Use our _get_import_path_for_file to get correct module path
            # This properly handles src-layout by using source_roots
            if name.module_path:
                module_path = self._get_import_path_for_file(Path(name.module_path))
            else:
                # Fall back to extracting from full_name if no file path
                parts = name.full_name.split(".")
                module_path = ".".join(parts[:-1]) if len(parts) > 1 else None

            if module_path:
                file_path = Path(name.module_path).as_posix() if name.module_path else None
                import_paths = await self.find_reexports(name.name, module_path, file_path)
                if import_paths:
                    result["import_paths"] = import_paths

        return result

    async def find_reexports(
        self, symbol_name: str, original_module: str, file_path: str | None = None
    ) -> list[str]:
        """Find re-export paths for a symbol.

        Args:
            symbol_name: Name of the symbol to find re-exports for
            original_module: The module path where the symbol is originally defined
            file_path: Optional file path to help determine full module path

        Returns:
            List of import paths where the symbol can be imported from
        """
        import_paths = []

        # Determine the full module path
        if original_module:
            # If we have a file path, try to determine the full module path
            # using our _get_import_path_for_file which handles src-layout
            if file_path and self.project_path:
                try:
                    file_path_obj = Path(file_path)
                    module_from_file = self._get_import_path_for_file(file_path_obj)
                    # Use the module from file if it's more complete
                    if module_from_file and len(module_from_file.split(".")) > len(
                        original_module.split(".")
                    ):
                        original_module = module_from_file.rsplit(".", 1)[
                            0
                        ]  # Remove the filename part
                except (ValueError, Exception):
                    pass  # Keep original module if conversion fails

            module_parts = original_module.split(".")
            direct_import = f"from {original_module} import {symbol_name}"
            import_paths.append(direct_import)

            # Check for re-exports in parent __init__.py files
            for i in range(len(module_parts) - 1, 0, -1):
                parent_module = ".".join(module_parts[:i])
                init_file = self._find_init_file(parent_module)

                if init_file and await self._check_symbol_in_init(
                    init_file, symbol_name, module_parts[i]
                ):
                    shorter_import = f"from {parent_module} import {symbol_name}"
                    # Insert at beginning as shorter imports are preferred
                    import_paths.insert(0, shorter_import)

        return import_paths

    def _find_init_file(self, module_path: str) -> Path | None:
        """Find the __init__.py file for a module."""
        try:
            # Convert module path to file system path
            path_parts = module_path.split(".")

            # Search in source roots first (e.g., src/), then project path and additional paths
            search_paths = list(self.source_roots) + [self.project_path]
            if hasattr(self, "additional_paths"):
                search_paths.extend(self.additional_paths)

            for base_path in search_paths:
                # Try to find the module relative to the base path
                # First check if the full module path exists as a package
                potential_path = base_path / Path(*path_parts) / "__init__.py"
                if potential_path.exists():
                    return potential_path

                # Also check if it's a submodule of a package in the base path
                # (e.g., base_path contains "reexport_test" and we're looking for "reexport_test.models")
                if len(path_parts) > 1 and base_path.name == path_parts[0]:
                    # Skip the first part if it matches the base directory name
                    potential_path = base_path / Path(*path_parts[1:]) / "__init__.py"
                    if potential_path.exists():
                        return potential_path

        except Exception as e:
            logger.debug(f"Error finding __init__.py for {module_path}: {e}")

        return None

    async def _check_symbol_in_init(
        self, init_file: Path, symbol_name: str, submodule: str
    ) -> bool:
        """Check if a symbol is re-exported in an __init__.py file."""
        try:
            content = await read_file_async(init_file)

            # Check for direct import: from .submodule import symbol
            import_patterns = [
                f"from .{submodule} import {symbol_name}",
                f"from .{submodule} import .*{symbol_name}",  # Handle multi-imports
                f"from .{submodule} import .*\\bas {symbol_name}\\b",  # Handle aliased imports
            ]

            for pattern in import_patterns:
                if re.search(pattern, content):
                    return True

            # Check if symbol is in __all__
            all_match = re.search(r"__all__\s*=\s*\[([^\]]+)\]", content, re.DOTALL)
            if all_match:
                all_content = all_match.group(1)
                if f'"{symbol_name}"' in all_content or f"'{symbol_name}'" in all_content:
                    # Verify the symbol is actually imported
                    if f"import {symbol_name}" in content or f"from .{submodule}" in content:
                        return True

        except Exception as e:
            logger.debug(f"Error checking symbol in {init_file}: {e}")

        return False

    async def find_subclasses(
        self,
        base_class: str,
        scope: Scope | None = None,
        include_indirect: bool = True,
        show_hierarchy: bool = False,
    ) -> list[dict[str, Any]]:
        """Find all classes that inherit from a given base class.

        Uses a hybrid Jedi + AST approach for performance:
        1. Single-pass AST parsing of scoped files (no double-read)
        2. Builds a parent->children graph for efficient indirect lookups
        3. Uses Jedi Script.goto() to resolve aliased imports

        Args:
            base_class: Name of the base class to find subclasses for
            scope: Search scope (default from smart defaults):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes
                - None: Use smart default ("all" for this method)
            include_indirect: Include indirect inheritance (grandchildren, etc.)
            show_hierarchy: Show the full inheritance chain

        Returns:
            List of subclasses with their locations and inheritance details
        """
        subclasses = []
        processed_classes: set[str] = set()

        try:
            # Get all Python files in scope (cached by get_project_files)
            py_files = await self.get_project_files("*.py", scope, method_name="find_subclasses")

            # Single pass: parse each file once, extract all class info
            # Maps class simple name -> list of (node, tree, file) for cross-file lookups
            classes_by_name: dict[str, list[tuple[ast.ClassDef, ast.Module, Path]]] = {}
            # Maps FQN -> (node, tree, file) for deduplication
            classes_by_fqn: dict[str, tuple[ast.ClassDef, ast.Module, Path]] = {}
            # Maps parent name -> set of child FQNs (for indirect traversal)
            parent_to_children: dict[str, set[str]] = {}

            for py_file in py_files:
                try:
                    content = await read_file_async(py_file)
                    tree = ast.parse(content, filename=py_file.as_posix())

                    for node in ast.walk(tree):
                        if not isinstance(node, ast.ClassDef):
                            continue

                        module_path = self._get_import_path_for_file(py_file)
                        fqn = (
                            f"{module_path}.{node.name}"
                            if module_path
                            else f"{py_file.stem}.{node.name}"
                        )

                        classes_by_fqn[fqn] = (node, tree, py_file)
                        classes_by_name.setdefault(node.name, []).append((node, tree, py_file))

                        # Record parent->child edges for all bases
                        for base in node.bases:
                            parent_name = self._get_base_name_from_ast(base)
                            if parent_name and parent_name != "object":
                                parent_to_children.setdefault(parent_name, set()).add(fqn)
                except Exception as e:
                    logger.debug(f"Error parsing {py_file}: {e}")

            # Find all direct subclasses by name match
            direct_fqns: set[str] = set()

            # Check simple name match (e.g., base_class="Animal", class Foo(Animal))
            if base_class in parent_to_children:
                direct_fqns.update(parent_to_children[base_class])

            # Check dotted name matches (e.g., class Foo(module.Animal))
            for parent_name, children in parent_to_children.items():
                if parent_name != base_class and parent_name.endswith(f".{base_class}"):
                    direct_fqns.update(children)

            # Try Jedi-based resolution for aliased imports
            # e.g., "from module import Animal as A" -> class Foo(A)
            direct_fqns.update(
                await self._resolve_aliased_bases(base_class, classes_by_fqn, parent_to_children)
            )

            # Collect indirect subclasses via graph traversal
            if include_indirect:
                all_matching_fqns = set(direct_fqns)
                queue = list(direct_fqns)
                while queue:
                    current_fqn = queue.pop()
                    if current_fqn not in classes_by_fqn:
                        continue
                    current_node = classes_by_fqn[current_fqn][0]
                    current_name = current_node.name
                    # Find children of this class
                    if current_name in parent_to_children:
                        for child_fqn in parent_to_children[current_name]:
                            if child_fqn not in all_matching_fqns:
                                all_matching_fqns.add(child_fqn)
                                queue.append(child_fqn)
            else:
                all_matching_fqns = direct_fqns

            # Build result list
            for fqn in all_matching_fqns:
                if fqn in processed_classes or fqn not in classes_by_fqn:
                    continue
                processed_classes.add(fqn)

                node, tree, py_file = classes_by_fqn[fqn]
                is_direct = fqn in direct_fqns

                # Determine direct parent name
                direct_parent = self._find_direct_parent_name(node, base_class, is_direct)

                subclass_info: dict[str, Any] = {
                    "name": node.name,
                    "full_name": fqn,
                    "file": py_file.as_posix(),
                    "line": node.lineno,
                    "column": node.col_offset,
                    "direct_parent": direct_parent,
                    "is_direct": is_direct,
                }

                if show_hierarchy:
                    subclass_info["inheritance_chain"] = self._build_inheritance_chain(
                        node, classes_by_name
                    )

                subclasses.append(subclass_info)

        except Exception as e:
            logger.error(f"Error finding subclasses: {e}")
            raise AnalysisError(
                f"Failed to find subclasses of {base_class}",
                error=str(e),
            ) from e

        return subclasses

    async def _resolve_aliased_bases(
        self,
        base_class: str,
        classes_by_fqn: dict[str, tuple[ast.ClassDef, ast.Module, Path]],
        parent_to_children: dict[str, set[str]],
    ) -> set[str]:
        """Use Jedi goto() to resolve aliased base class references.

        Handles cases like 'from module import Animal as A; class Foo(A):'
        where AST name matching alone would miss the relationship.
        """
        resolved_fqns: set[str] = set()

        # Only check parent names that didn't match the base_class by simple name
        # These are candidates for aliased imports
        candidate_parents = {
            name
            for name in parent_to_children
            if name != base_class and not name.endswith(f".{base_class}")
        }

        if not candidate_parents:
            return resolved_fqns

        # Group classes by file to minimize Jedi Script creation
        file_to_classes: dict[str, list[tuple[str, ast.ClassDef]]] = {}
        for fqn, (node, _tree, py_file) in classes_by_fqn.items():
            file_key = py_file.as_posix()
            for base in node.bases:
                parent_name = self._get_base_name_from_ast(base)
                if parent_name in candidate_parents:
                    file_to_classes.setdefault(file_key, []).append((fqn, node))
                    break

        for file_path_str, class_entries in file_to_classes.items():
            try:
                file_path = Path(file_path_str)
                content = await read_file_async(file_path)
                script = jedi.Script(content, path=file_path, project=self.project)

                for fqn, node in class_entries:
                    for base in node.bases:
                        parent_name = self._get_base_name_from_ast(base)
                        if parent_name not in candidate_parents:
                            continue

                        # Use goto() to resolve what this base name points to
                        try:
                            goto_results = script.goto(
                                base.lineno, base.col_offset, follow_imports=True
                            )
                            for result in goto_results:
                                if result.name == base_class:
                                    resolved_fqns.add(fqn)
                                    break
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Error resolving aliases in {file_path_str}: {e}")

        return resolved_fqns

    def _find_direct_parent_name(
        self,
        node: ast.ClassDef,
        base_class: str,
        is_direct: bool,
    ) -> str:
        """Determine the direct parent class name for a subclass result."""
        if is_direct:
            return base_class

        # For indirect subclasses, find which base is in the inheritance chain
        for base in node.bases:
            parent_name = self._get_base_name_from_ast(base)
            if parent_name:
                return parent_name
        return "unknown"

    @staticmethod
    def _get_base_name_from_ast(base: Any) -> str | None:
        """Extract the name from an AST base class node."""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            parts = []
            node: Any = base
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    @staticmethod
    def _build_inheritance_chain(
        class_node: ast.ClassDef,
        classes_by_name: dict[str, list[tuple[ast.ClassDef, ast.Module, Path]]],
    ) -> list[str]:
        """Build the inheritance chain using the pre-built class map."""
        chain = [class_node.name]
        visited = {class_node.name}

        current_bases = class_node.bases

        while current_bases:
            next_bases: list[Any] = []
            for base in current_bases:
                base_name: str | None = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr

                if base_name and base_name not in visited:
                    chain.append(base_name)
                    visited.add(base_name)

                    # Look up parent class in the cross-file map
                    if base_name in classes_by_name:
                        for parent_node, _, _ in classes_by_name[base_name]:
                            next_bases.extend(parent_node.bases)

            current_bases = next_bases

        if "object" not in chain:
            chain.append("object")

        return chain

    async def populate_dependencies(self, dependency_tracker: DependencyTracker) -> None:
        """Populate dependency tracker with project imports.

        Args:
            dependency_tracker: Tracker to populate with dependencies
        """
        try:
            # Find all Python files in the project (use "all" scope for complete dependency tracking)
            python_files = await self.get_project_files("*.py", "all")

            logger.info(f"Analyzing dependencies for {len(python_files)} Python files")

            # Create import analyzer
            import_analyzer = ImportAnalyzer(self.project_path)

            # Build dependency graph
            graph = import_analyzer.build_dependency_graph(python_files)

            # Populate dependency tracker
            for module_name, file_path in graph["modules"].items():
                file_path_obj = Path(file_path)

                # Add file to module mapping
                dependency_tracker.add_file_mapping(file_path_obj, module_name)

                # Add imports
                if module_name in graph["imports"]:
                    for imported_module in graph["imports"][module_name]:
                        # Only track project-internal imports
                        if imported_module in graph["modules"]:
                            dependency_tracker.add_import(module_name, imported_module)

                # Add symbol definitions
                if module_name in graph["symbols"]:
                    for symbol in graph["symbols"][module_name]:
                        dependency_tracker.add_symbol_definition(module_name, symbol)

            stats = dependency_tracker.get_stats()
            logger.info(
                f"Dependency graph built: {stats['total_modules']} modules, {stats['total_import_edges']} import edges"
            )

        except Exception as e:
            logger.error(f"Failed to populate dependencies: {e}")

    def _extract_base_name_from_parso_node(self, node: Any) -> str | None:
        """Extract qualified name from a parso node (Jedi's parse tree).

        Handles both simple names and dotted names like:
        - BaseClass (name node)
        - module.BaseClass (power/atom_expr node)
        - a.b.c.d.BaseClass (nested power/atom_expr)

        Args:
            node: Parso node representing a base class reference

        Returns:
            Qualified name as string, or None if extraction fails
        """
        try:
            # Simple name node
            if hasattr(node, "type") and node.type == "name":
                return str(node.value) if hasattr(node, "value") else None

            # Dotted name (power or atom_expr in parso)
            # Use get_code() to extract the actual source text
            if hasattr(node, "type") and node.type in ("power", "atom_expr"):
                if hasattr(node, "get_code"):
                    # get_code() returns the source code representation
                    code: str = node.get_code().strip()
                    if code:
                        return code

                # Fallback: traverse the node structure
                parts: list[str] = []
                self._collect_dotted_name_parts(node, parts)
                if parts:
                    return ".".join(parts)

            # Final fallback: try to get value directly
            if hasattr(node, "value"):
                return str(node.value)

        except Exception as e:
            logger.debug(f"Could not extract base name from parso node: {e}")

        return None

    def _collect_dotted_name_parts(self, node: Any, parts: list[str]) -> None:
        """Recursively collect parts of a dotted name from parso nodes.

        For a.b.c, this collects ['a', 'b', 'c'] in order.
        """
        if not hasattr(node, "children"):
            # Leaf node - check if it's a name
            if hasattr(node, "type") and node.type == "name" and hasattr(node, "value"):
                parts.append(node.value)
            return

        # Process children
        for child in node.children:
            if hasattr(child, "type"):
                if child.type == "name" and hasattr(child, "value"):
                    parts.append(child.value)
                elif child.type in ("power", "atom_expr", "trailer"):
                    # Recursively process nested structures
                    self._collect_dotted_name_parts(child, parts)
                elif child.type == "operator" and hasattr(child, "value") and child.value == ".":
                    # Skip dot operators
                    continue

    async def _get_class_inheritance_info(
        self, script: jedi.Script, class_def: Any
    ) -> tuple[list[str], list[str]]:
        """Extract base classes and MRO for a class definition.

        Uses Jedi's internal py__mro__() for accurate C3 linearization MRO,
        with a fallback to Parso AST parsing for base class extraction.

        Args:
            script: The Jedi script instance
            class_def: The Jedi class definition (Name object)

        Returns:
            Tuple of (base_classes, mro) where both are lists of fully qualified names
        """
        base_classes: list[str] = []
        mro: list[str] = []

        try:
            # Try Jedi's internal MRO first - gives accurate C3 linearization
            mro = self._get_jedi_mro(class_def)

            # Jedi MRO with only the class itself (no resolved bases) means
            # Jedi couldn't resolve the inheritance - fall through to Parso
            if len(mro) > 1:
                # Extract direct base classes from the MRO
                # Direct bases are the classes listed in the class definition,
                # not the full MRO chain. Use Parso to get just the direct bases.
                base_classes = self._get_direct_bases_from_parso(script, class_def)

                # If Parso extraction failed, derive direct bases from MRO
                # (everything except self and object)
                if not base_classes and len(mro) > 2:
                    base_classes = [cls for cls in mro[1:] if cls != "builtins.object"]

                return base_classes, mro

            # Fallback: extract base classes from Parso AST and build simplified MRO
            base_classes = self._get_direct_bases_from_parso(script, class_def)

            # Build MRO from base classes
            if base_classes:
                if class_def.full_name:
                    mro.append(class_def.full_name)
                mro.extend(base_classes)
                if "builtins.object" not in mro and "object" not in mro:
                    mro.append("builtins.object")
            else:
                if class_def.full_name:
                    mro = [class_def.full_name, "builtins.object"]

        except Exception as e:
            logger.debug(f"Could not extract inheritance info: {e}")

        return base_classes, mro

    def _get_jedi_mro(self, class_def: Any) -> list[str]:
        """Extract full MRO using Jedi's internal class hierarchy with C3 linearization.

        Jedi's py__mro__() doesn't correctly implement C3 linearization for
        diamond inheritance, so we use Jedi to discover the class hierarchy
        and compute the MRO ourselves.

        Args:
            class_def: A Jedi Name object for a class

        Returns:
            List of fully qualified class names in MRO order, or empty list on failure
        """
        try:
            if not hasattr(class_def, "_name") or not hasattr(class_def._name, "infer"):
                return []

            values = list(class_def._name.infer())
            for value in values:
                if not hasattr(value, "py__mro__"):
                    continue

                # Use py__mro__() to discover all classes in the hierarchy
                mro_classes = list(value.py__mro__())

                # Build name->FQN mapping and bases graph from Jedi values
                name_to_fqn: dict[str, str] = {}
                bases_map: dict[str, list[str]] = {}

                for cls in mro_classes:
                    cls_name = cls.py__name__() if hasattr(cls, "py__name__") else None
                    if not cls_name:
                        continue

                    # Build FQN
                    fqn = cls_name
                    module = cls.get_root_context()
                    if hasattr(module, "py__name__"):
                        module_name = module.py__name__()
                        if module_name:
                            fqn = f"{module_name}.{cls_name}"

                    name_to_fqn[cls_name] = fqn

                    # Resolve direct bases via py__bases__()
                    resolved_bases: list[str] = []
                    if hasattr(cls, "py__bases__"):
                        for lazy_base in cls.py__bases__():
                            if hasattr(lazy_base, "infer"):
                                for base_val in lazy_base.infer():
                                    if hasattr(base_val, "py__name__"):
                                        resolved_bases.append(base_val.py__name__())
                    bases_map[cls_name] = resolved_bases

                if not name_to_fqn:
                    continue

                # Get the target class name
                root_cls = mro_classes[0]
                root_name = root_cls.py__name__() if hasattr(root_cls, "py__name__") else None
                if not root_name:
                    continue

                # Compute correct C3 linearization
                c3_order = self._c3_linearize(root_name, bases_map)

                # Convert to FQNs
                mro = [name_to_fqn.get(name, name) for name in c3_order]

                if mro:
                    return mro
        except Exception as e:
            logger.debug(f"Could not get Jedi MRO: {e}")

        return []

    @staticmethod
    def _c3_linearize(cls_name: str, bases_map: dict[str, list[str]]) -> list[str]:
        """Compute C3 linearization (MRO) for a class hierarchy.

        Implements the same algorithm Python uses for method resolution order.

        Args:
            cls_name: Name of the class to compute MRO for
            bases_map: Mapping of class name -> list of direct base class names

        Returns:
            List of class names in MRO order
        """
        if cls_name not in bases_map or not bases_map[cls_name]:
            return [cls_name]

        bases = bases_map[cls_name]
        # Recursively get MRO for each base
        base_mros = [JediAnalyzer._c3_linearize(b, bases_map) for b in bases]
        # Add the list of direct bases as the final constraint
        base_mros.append(list(bases))

        result = [cls_name]
        while base_mros:
            # Find a candidate: head of some list that doesn't appear in the
            # tail of any other list
            candidate = None
            for mro_list in base_mros:
                if not mro_list:
                    continue
                head = mro_list[0]
                in_tail = any(head in ml[1:] for ml in base_mros if ml)
                if not in_tail:
                    candidate = head
                    break

            if candidate is None:
                # Inconsistent hierarchy — append remaining classes
                for ml in base_mros:
                    for name in ml:
                        if name not in result:
                            result.append(name)
                break

            result.append(candidate)
            # Remove candidate from all lists
            base_mros = [
                [x for x in ml if x != candidate] if ml and ml[0] == candidate else ml
                for ml in base_mros
            ]
            base_mros = [ml for ml in base_mros if ml]

        return result

    def _get_direct_bases_from_parso(self, script: jedi.Script, class_def: Any) -> list[str]:
        """Extract direct base class names using Parso AST parsing.

        Args:
            script: The Jedi script instance (for resolving base class FQNs)
            class_def: A Jedi Name object for a class

        Returns:
            List of fully qualified base class names
        """
        base_classes: list[str] = []

        try:
            if (
                not hasattr(class_def, "_name")
                or not hasattr(class_def._name, "tree_name")
                or isinstance(class_def._name, type(None))
            ):
                return base_classes

            try:
                tree_node = class_def._name.tree_name
                classdef = tree_node.parent if hasattr(tree_node, "parent") else None
            except (AttributeError, TypeError):
                return base_classes

            # Navigate to find the classdef node
            max_depth = 10
            depth = 0
            while (
                classdef
                and hasattr(classdef, "type")
                and classdef.type != "classdef"
                and depth < max_depth
            ):
                if hasattr(classdef, "parent"):
                    classdef = classdef.parent
                    depth += 1
                else:
                    classdef = None
                    break

            if not (classdef and hasattr(classdef, "type") and hasattr(classdef, "children")):
                return base_classes

            try:
                children = list(classdef.children)
            except (TypeError, AttributeError):
                return base_classes

            # Collect base class nodes from between parentheses
            base_nodes: list[Any] = []
            in_bases = False
            for child in children:
                if hasattr(child, "type") and child.type == "operator":
                    if child.value == "(":
                        in_bases = True
                        continue
                    elif child.value == ")":
                        break

                if in_bases and hasattr(child, "type"):
                    if child.type in ("name", "power", "atom_expr"):
                        base_nodes.append(child)
                    elif child.type == "arglist":
                        for arg in child.children:
                            if hasattr(arg, "type") and arg.type in (
                                "name",
                                "power",
                                "atom_expr",
                            ):
                                base_nodes.append(arg)

            # Resolve each base node to a FQN
            for node in base_nodes:
                base_name = self._resolve_base_node(script, node)
                if base_name:
                    base_classes.append(base_name)

        except Exception as e:
            logger.debug(f"Could not extract direct bases from Parso: {e}")

        return base_classes

    def _resolve_base_node(self, script: jedi.Script, node: Any) -> str | None:
        """Resolve a Parso base class node to a fully qualified name.

        Tries Jedi inference first, falls back to AST extraction.

        Args:
            script: The Jedi script instance
            node: A Parso AST node for a base class reference

        Returns:
            Fully qualified name string, or None
        """
        try:
            base_line = node.start_pos[0]
            base_column = node.start_pos[1]
            base_inferred = script.infer(base_line, base_column)

            if base_inferred:
                for base_inf in base_inferred:
                    if base_inf.full_name:
                        return str(base_inf.full_name)
            else:
                return self._extract_base_name_from_parso_node(node)
        except Exception:
            return self._extract_base_name_from_parso_node(node)

        return None
