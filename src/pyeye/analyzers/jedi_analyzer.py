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
            # Pass POSIX string to Jedi to avoid Path object cache issues (Jedi bug with Path as dict keys)
            # Using as_posix() ensures cross-platform compatibility with forward slashes
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

    def _update_validator(self) -> None:
        """Update the scope validator with current configuration."""
        scope_aliases = self.config.get_scope_aliases() if self.config else {}
        self.scope_validator = ScopeValidator(
            self.namespace_paths, self.additional_paths, scope_aliases
        )

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
        # Try main project first
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
        self, name: str, fuzzy: bool = False, include_import_paths: bool = True
    ) -> list[dict[str, Any]]:
        """Find symbol definitions in the project.

        Args:
            name: Symbol name to search for (supports compound symbols like "Model.__init__")
            fuzzy: Enable fuzzy matching
            include_import_paths: Include alternative import paths for re-exported symbols

        Returns:
            List of symbol matches with location and optional import path information
        """
        # Check if this is a compound symbol (e.g., "Model.__init__")
        if is_compound_symbol(name):
            return await self._find_compound_symbol(name, include_import_paths)

        # Original implementation for simple symbols
        results = []

        try:
            search_results = self.project.search(name, all_scopes=True)

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
                    # If the exception has Path objects in args, convert them
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
        self, name: str, include_import_paths: bool = True
    ) -> list[dict[str, Any]]:
        """Find compound symbol definitions (e.g., "Model.__init__").

        Args:
            name: Compound symbol name (e.g., "Model.__init__", "module.Class.method")
            include_import_paths: Include alternative import paths

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
            return await self.find_symbol(name, include_import_paths=include_import_paths)

        try:
            # Get parent and member names
            parent_path, member_name = get_parent_and_member(components)

            # First, find the parent symbol (class or module)
            parent_results = self.project.search(components[-2], all_scopes=True)

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
        self, file: str, line: int, column: int, detailed: bool = False
    ) -> dict[str, Any]:
        """Get type information at a specific position.

        Args:
            file: Path to the file
            line: Line number (1-indexed)
            column: Column number (0-indexed)
            detailed: Include additional information like methods and attributes

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

            return result

        except FileAccessError:
            raise  # Re-raise file access errors
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
            # Create patterns for different import styles
            import_patterns = [
                f"import {escaped_module}",
                f"from {escaped_module}",
                f"import.*{escaped_module}",
                f"from.*{escaped_module}",
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
                    # For files under project_path, use project_path
                    # For files elsewhere (namespace packages), use a suitable parent
                    try:
                        py_file.relative_to(self.project_path)
                        analyzer_root = self.project_path
                    except ValueError:
                        # File is not under project_path, find appropriate root
                        analyzer_root = py_file.parent
                        # Walk up to find a directory with __init__.py or that contains Python packages
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

                    # Check if this file imports our module
                    found_imports = False

                    # Check direct imports
                    for imported in import_info["imports"]:
                        if imported == module_name or imported.startswith(f"{module_name}."):
                            found_imports = True
                            break

                    # Check from imports
                    if not found_imports:
                        for from_module in import_info["from_imports"]:
                            if from_module == module_name or from_module.startswith(
                                f"{module_name}."
                            ):
                                found_imports = True
                                break

                    # If we found imports, extract line information
                    if found_imports:
                        source = await read_file_async(py_file)

                        # Use simple line-by-line search since AST already confirmed the import exists
                        lines = source.splitlines()
                        for line_num, line in enumerate(lines, 1):
                            # Check if this line contains the import
                            # Handle both "import module" and "from module import ..."
                            if f"import {module_name}" in line or f"from {module_name}" in line:
                                # Find the column where the module name starts
                                col = line.find(module_name)
                                if col == -1:
                                    col = 0

                                results.append(
                                    {
                                        "file": py_file.as_posix(),
                                        "line": line_num,
                                        "column": col,
                                        "import_statement": line.strip(),
                                        "type": "import",
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
        """Get the call hierarchy for a function.

        Args:
            function_name: Name of the function
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
            # First find the function definition
            search_results = self.project.search(function_name, all_scopes=True)

            function_def = None
            for res in search_results:
                if res.type == "function" and (file is None or str(res.module_path) == file):
                    function_def = res
                    break

            if not function_def or not function_def.module_path:
                return {"error": f"Function {function_name} not found"}

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

                # Determine package name based on which search path this file belongs to
                package_name = None
                rel_path = None

                # Try to make relative to main project first
                try:
                    rel_path = package_dir.relative_to(self.project_path)
                    package_name = rel_path.as_posix().replace("/", ".")
                except ValueError:
                    # Not under main project, check if it's in a namespace
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
                # Determine import path based on which search path this file belongs to
                import_path = None
                rel_path = None

                # Try to make relative to main project first
                try:
                    rel_path = py_file.relative_to(self.project_path)
                    module_parts = list(rel_path.parts[:-1])  # directories
                    if py_file.name != "__init__.py":
                        module_parts.append(py_file.stem)
                    import_path = ".".join(module_parts) if module_parts else py_file.stem
                except ValueError:
                    # Not under main project, check if it's in a namespace
                    for ns_name, ns_paths in self.namespace_paths.items():
                        for ns_path in ns_paths:
                            try:
                                if py_file.is_relative_to(ns_path):
                                    ns_rel_path = py_file.relative_to(ns_path)
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
            possible_paths = [
                self.project_path / Path(*module_parts[:-1]) / f"{module_parts[-1]}.py",
                self.project_path / Path(*module_parts) / "__init__.py",
                self.project_path / f"{module_path.replace('.', os.sep)}.py",
            ]

            for path in possible_paths:
                if path.exists():
                    module_file = path
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
            possible_paths = [
                self.project_path / Path(*module_parts[:-1]) / f"{module_parts[-1]}.py",
                self.project_path / Path(*module_parts) / "__init__.py",
                self.project_path / f"{module_path.replace('.', os.sep)}.py",
            ]

            for path in possible_paths:
                if path.exists():
                    module_file = path
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
            # Extract module path from full_name (everything except the last part)
            parts = name.full_name.split(".")
            if len(parts) > 1:
                module_path = ".".join(parts[:-1])
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
            if file_path and self.project_path:
                try:
                    # Convert file path to module path relative to project
                    file_path_obj = Path(file_path)
                    rel_path = file_path_obj.relative_to(self.project_path)
                    # Remove .py extension and convert to module path
                    module_from_file = rel_path.with_suffix("").as_posix().replace("/", ".")
                    # Use the module from file if it's more complete
                    if len(module_from_file.split(".")) > len(original_module.split(".")):
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

            # Search in project path and any additional package paths
            search_paths = [self.project_path]
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
        processed_classes = set()  # To avoid duplicates

        try:
            # First, try to find the base class definition (may not exist for builtins)
            base_symbols = await self.find_symbol(base_class, fuzzy=False)
            if not base_symbols:
                # For built-in classes like Exception, str, int, etc., we still want to proceed
                logger.info(
                    f"Base class '{base_class}' not found in project, checking for subclasses anyway"
                )

            # Get all Python files in the project (with smart default)
            py_files = await self.get_project_files("*.py", scope, method_name="find_subclasses")

            # Build a global class map for cross-file inheritance checking
            # Maps: FQN -> (node, tree, file)
            class_map: dict[str, tuple[ast.ClassDef, ast.Module, Path]] = {}

            if include_indirect:
                for py_file in py_files:
                    try:
                        content = await read_file_async(py_file)
                        tree = ast.parse(content, filename=py_file.as_posix())

                        for node in ast.walk(tree):
                            if isinstance(node, ast.ClassDef):
                                module_path = self._get_import_path_for_file(py_file)
                                fqn = (
                                    f"{module_path}.{node.name}"
                                    if module_path
                                    else f"{py_file.stem}.{node.name}"
                                )
                                class_map[fqn] = (node, tree, py_file)
                                # Also map simple name for lookups
                                if node.name not in class_map:
                                    class_map[node.name] = (node, tree, py_file)
                    except Exception as e:
                        logger.debug(f"Error parsing {py_file} for class map: {e}")

            for py_file in py_files:
                try:
                    content = await read_file_async(py_file)
                    tree = ast.parse(content, filename=py_file.as_posix())

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            # Check if this class inherits from our base class
                            inheritance_info = self._check_inheritance(
                                node, base_class, tree, include_indirect, class_map
                            )

                            if inheritance_info:
                                # Calculate FQN for unique identification
                                # Use module path + class name to avoid name collisions
                                module_path = self._get_import_path_for_file(py_file)
                                fqn = (
                                    f"{module_path}.{node.name}"
                                    if module_path
                                    else f"{py_file.stem}.{node.name}"
                                )

                                if fqn not in processed_classes:
                                    processed_classes.add(fqn)

                                    subclass_info = {
                                        "name": node.name,
                                        "full_name": fqn,
                                        "file": py_file.as_posix(),
                                        "line": node.lineno,
                                        "column": node.col_offset,
                                        "direct_parent": inheritance_info["direct_parent"],
                                        "is_direct": inheritance_info["is_direct"],
                                    }

                                # Add inheritance chain if requested
                                if show_hierarchy:
                                    subclass_info["inheritance_chain"] = (
                                        await self._get_inheritance_chain(node, tree)
                                    )

                                subclasses.append(subclass_info)

                except Exception as e:
                    logger.debug(f"Error parsing {py_file}: {e}")

        except Exception as e:
            logger.error(f"Error finding subclasses: {e}")
            raise AnalysisError(
                f"Failed to find subclasses of {base_class}",
                error=str(e),
            ) from e

        return subclasses

    def _check_inheritance(
        self,
        class_node: ast.ClassDef,
        base_class: str,
        tree: ast.Module,
        include_indirect: bool,
        class_map: dict[str, tuple[ast.ClassDef, ast.Module, Path]] | None = None,
    ) -> dict[str, Any] | None:
        """Check if a class inherits from the base class.

        Args:
            class_node: The AST node of the class to check
            base_class: The name of the base class we're looking for
            tree: The AST tree of the file containing class_node
            include_indirect: Whether to check for indirect inheritance
            class_map: Optional global map of all classes for cross-file lookups

        Returns dict with inheritance info if it does, None otherwise.
        """
        # Check direct inheritance
        for base in class_node.bases:
            base_name = self._get_base_name(base)
            if base_name == base_class:
                return {
                    "direct_parent": base_class,
                    "is_direct": True,
                }

        # Check indirect inheritance if requested
        if include_indirect:
            for base in class_node.bases:
                base_name = self._get_base_name(base)
                if base_name and base_name != "object":
                    # Try to find parent class definition
                    parent_classes: list[tuple[ast.ClassDef, ast.Module]] = []

                    # First check in the current file's tree
                    local_parents = self._find_class_in_tree(tree, base_name)
                    parent_classes.extend([(p, tree) for p in local_parents])

                    # If not found and we have a global class map, search there
                    if not parent_classes and class_map:
                        # Try both FQN and simple name lookups
                        if base_name in class_map:
                            parent_node, parent_tree, parent_file = class_map[base_name]
                            parent_classes.append((parent_node, parent_tree))

                    # Recursively check each parent class
                    for parent_class, parent_tree in parent_classes:
                        parent_info = self._check_inheritance(
                            parent_class, base_class, parent_tree, include_indirect, class_map
                        )
                        if parent_info:
                            return {
                                "direct_parent": base_name,
                                "is_direct": False,
                            }

        return None

    def _get_base_name(self, base: Any) -> str | None:
        """Extract the name from a base class node."""
        if isinstance(base, ast.Name):
            return base.id
        elif isinstance(base, ast.Attribute):
            # Handle module.Class style bases
            parts = []
            node: Any = base
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
        return None

    def _find_class_in_tree(self, tree: ast.Module, class_name: str) -> list[ast.ClassDef]:
        """Find class definitions by name in the AST tree."""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                classes.append(node)
        return classes

    async def _get_inheritance_chain(self, class_node: ast.ClassDef, tree: ast.Module) -> list[str]:
        """Build the complete inheritance chain for a class."""
        chain = [class_node.name]
        visited = {class_node.name}  # Prevent infinite loops

        current_bases = class_node.bases

        while current_bases:
            next_bases = []
            for base in current_bases:
                base_name = self._get_base_name(base)
                if base_name and base_name not in visited:
                    chain.append(base_name)
                    visited.add(base_name)

                    # Find this base class and get its bases
                    parent_classes = self._find_class_in_tree(tree, base_name)
                    for parent_class in parent_classes:
                        next_bases.extend(parent_class.bases)

            current_bases = next_bases

        # Add object if not already present
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

        Args:
            script: The Jedi script instance
            class_def: The Jedi class definition

        Returns:
            Tuple of (base_classes, mro) where both are lists of fully qualified names
        """
        base_classes: list[str] = []
        mro: list[str] = []

        try:
            # Try to get base classes from the class definition
            # Only process real Jedi objects, not mocks
            if (
                hasattr(class_def, "_name")
                and hasattr(class_def._name, "tree_name")
                and not isinstance(class_def._name, type(None))
            ):
                try:
                    tree_node = class_def._name.tree_name
                    classdef = tree_node.parent if hasattr(tree_node, "parent") else None
                except (AttributeError, TypeError):
                    # If we can't get tree_node or parent, bail out
                    return base_classes, mro

                # Navigate to find the classdef node with a max depth to prevent infinite loops
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

                if classdef and hasattr(classdef, "type") and hasattr(classdef, "children"):
                    # Find base classes - they can be directly as name nodes or in arglist
                    in_bases = False
                    try:
                        children = list(
                            classdef.children
                        )  # Convert to list to prevent iterator issues
                    except (TypeError, AttributeError):
                        return base_classes, mro

                    for _, child in enumerate(children):
                        # Start collecting after opening parenthesis
                        if (
                            hasattr(child, "type")
                            and child.type == "operator"
                            and child.value == "("
                        ):
                            in_bases = True
                            continue
                        # Stop at closing parenthesis
                        elif (
                            hasattr(child, "type")
                            and child.type == "operator"
                            and child.value == ")"
                        ):
                            in_bases = False
                            continue

                        # Collect base class names
                        if in_bases:
                            if hasattr(child, "type"):
                                if child.type == "name":
                                    # Single base class (simple name)
                                    try:
                                        base_line = child.start_pos[0]
                                        base_column = child.start_pos[1]
                                        base_inferred = script.infer(base_line, base_column)

                                        # Check if Jedi successfully resolved the base class
                                        if base_inferred:
                                            # Jedi found the base class
                                            for base_inf in base_inferred:
                                                if base_inf.full_name:
                                                    base_classes.append(base_inf.full_name)
                                                    break
                                        else:
                                            # Jedi couldn't resolve - use AST fallback
                                            base_name = self._extract_base_name_from_parso_node(
                                                child
                                            )
                                            if base_name:
                                                base_classes.append(base_name)
                                    except Exception:
                                        # Exception during inference - use AST fallback
                                        base_name = self._extract_base_name_from_parso_node(child)
                                        if base_name:
                                            base_classes.append(base_name)

                                elif child.type in ("power", "atom_expr"):
                                    # Qualified/dotted base class name (e.g., module.BaseClass)
                                    # Try Jedi inference first, fall back to AST extraction
                                    try:
                                        base_line = child.start_pos[0]
                                        base_column = child.start_pos[1]
                                        base_inferred = script.infer(base_line, base_column)

                                        if base_inferred:
                                            # Jedi resolved it
                                            for base_inf in base_inferred:
                                                if base_inf.full_name:
                                                    base_classes.append(base_inf.full_name)
                                                    break
                                        else:
                                            # Jedi couldn't resolve - extract from AST
                                            base_name = self._extract_base_name_from_parso_node(
                                                child
                                            )
                                            if base_name:
                                                base_classes.append(base_name)
                                    except Exception:
                                        # Exception during inference - extract from AST
                                        base_name = self._extract_base_name_from_parso_node(child)
                                        if base_name:
                                            base_classes.append(base_name)

                                elif child.type == "arglist":
                                    # Multiple base classes in arglist
                                    for arg in child.children:
                                        if hasattr(arg, "type"):
                                            if arg.type == "name":
                                                # Simple name in arglist
                                                try:
                                                    base_line = arg.start_pos[0]
                                                    base_column = arg.start_pos[1]
                                                    base_inferred = script.infer(
                                                        base_line, base_column
                                                    )

                                                    if base_inferred:
                                                        # Jedi resolved it
                                                        for base_inf in base_inferred:
                                                            if base_inf.full_name:
                                                                base_classes.append(
                                                                    base_inf.full_name
                                                                )
                                                                break
                                                    else:
                                                        # Jedi couldn't resolve - use AST fallback
                                                        base_name = (
                                                            self._extract_base_name_from_parso_node(
                                                                arg
                                                            )
                                                        )
                                                        if base_name:
                                                            base_classes.append(base_name)
                                                except Exception:
                                                    # Exception - use AST fallback
                                                    base_name = (
                                                        self._extract_base_name_from_parso_node(arg)
                                                    )
                                                    if base_name:
                                                        base_classes.append(base_name)

                                            elif arg.type in ("power", "atom_expr"):
                                                # Qualified name in arglist
                                                try:
                                                    base_line = arg.start_pos[0]
                                                    base_column = arg.start_pos[1]
                                                    base_inferred = script.infer(
                                                        base_line, base_column
                                                    )

                                                    if base_inferred:
                                                        # Jedi resolved it
                                                        for base_inf in base_inferred:
                                                            if base_inf.full_name:
                                                                base_classes.append(
                                                                    base_inf.full_name
                                                                )
                                                                break
                                                    else:
                                                        # Jedi couldn't resolve - extract from AST
                                                        base_name = (
                                                            self._extract_base_name_from_parso_node(
                                                                arg
                                                            )
                                                        )
                                                        if base_name:
                                                            base_classes.append(base_name)
                                                except Exception:
                                                    # Exception - extract from AST
                                                    base_name = (
                                                        self._extract_base_name_from_parso_node(arg)
                                                    )
                                                    if base_name:
                                                        base_classes.append(base_name)

            # Build MRO
            if base_classes:
                # Start with the class itself
                if class_def.full_name:
                    mro.append(class_def.full_name)

                # Add base classes (simplified MRO - in practice Python's MRO is more complex)
                mro.extend(base_classes)

                # Add object if not already present
                if "builtins.object" not in mro and "object" not in mro:
                    mro.append("builtins.object")
            else:
                # Class with no explicit bases inherits from object
                if class_def.full_name:
                    mro = [class_def.full_name, "builtins.object"]

        except Exception as e:
            logger.debug(f"Could not extract inheritance info: {e}")
            # Return empty lists on error
            pass

        return base_classes, mro
