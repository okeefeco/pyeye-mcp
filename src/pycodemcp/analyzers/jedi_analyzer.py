"""Jedi-based analyzer for Python code intelligence."""

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any

import jedi

from ..async_utils import read_file_async, rglob_async
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
                - "all": Everything configured (default)
                - "packages": All configured packages excluding main
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
                # Everything: main + packages + namespaces
                paths.add(self.project_path)
                paths.update(self.additional_paths)
                # Add all namespace paths
                for ns_paths in self.namespace_paths.values():
                    for ns_path in ns_paths:
                        # For namespace packages, add the proper subdirectory
                        paths.update(self._get_namespace_directory_structure(ns_path))

            elif s == "packages":
                # All configured packages excluding main
                paths.update(self.additional_paths)

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

    async def find_symbol(
        self, name: str, fuzzy: bool = False, include_import_paths: bool = True
    ) -> list[dict[str, Any]]:
        """Find symbol definitions in the project.

        Args:
            name: Symbol name to search for
            fuzzy: Enable fuzzy matching
            include_import_paths: Include alternative import paths for re-exported symbols

        Returns:
            List of symbol matches with location and optional import path information
        """
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
        self, file: str, line: int, column: int, include_definitions: bool = True
    ) -> list[dict[str, Any]]:
        """Find all references to a symbol."""
        results: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = await read_file_async(file_path)
            script = jedi.Script(source, path=file_path, project=self.project)
            references = script.get_references(line, column, include_builtins=False)

            for ref in references:
                if not include_definitions and ref.is_definition():
                    continue

                serialized = await self._serialize_name(ref)
                serialized["is_definition"] = ref.is_definition()
                results.append(serialized)

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in find_references: {e}")
            # Return partial results if any

        return results

    async def get_type_info(self, file: str, line: int, column: int) -> dict[str, Any]:
        """Get type information at a specific position.

        Args:
            file: Path to the file
            line: Line number (1-indexed)
            column: Column number (0-indexed)

        Returns:
            Type information including inferred type and docstring
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
            scope: Search scope (default "all"):
                - "main": Only the main project
                - "all": Main project + configured namespaces
                - "namespace:name": Specific namespace
                - ["main", "namespace:x"]: Multiple scopes

        Returns:
            List of import locations
        """
        results = []

        try:
            # Search for import statements across the project
            py_files = await self.get_project_files("*.py", scope)
            for py_file in py_files:
                try:
                    source = await read_file_async(py_file)
                    script = jedi.Script(source, path=py_file.as_posix(), project=self.project)

                    # Get all names in the file
                    names = script.get_names(all_scopes=True, definitions=True, references=True)

                    for name in names:
                        # Check if it's an import of our module
                        if name.type in ["module", "import"] and module_name in name.full_name:
                            results.append(
                                {
                                    "file": py_file.as_posix(),
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
            raise AnalysisError(
                f"Failed to get call hierarchy for function '{function_name}'",
                function=function_name,
                file=file,
                error=str(e),
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

            for py_file in py_files:
                try:
                    content = await read_file_async(py_file)
                    tree = ast.parse(content, filename=py_file.as_posix())

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            # Check if this class inherits from our base class
                            inheritance_info = self._check_inheritance(
                                node, base_class, tree, include_indirect
                            )

                            if inheritance_info and node.name not in processed_classes:
                                processed_classes.add(node.name)

                                subclass_info = {
                                    "name": node.name,
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
        self, class_node: ast.ClassDef, base_class: str, tree: ast.Module, include_indirect: bool
    ) -> dict[str, Any] | None:
        """Check if a class inherits from the base class.

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
                    # Find the parent class definition and check its bases recursively
                    parent_classes = self._find_class_in_tree(tree, base_name)
                    for parent_class in parent_classes:
                        parent_info = self._check_inheritance(
                            parent_class, base_class, tree, include_indirect
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
