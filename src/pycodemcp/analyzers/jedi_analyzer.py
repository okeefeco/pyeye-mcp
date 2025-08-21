"""Jedi-based analyzer for Python code intelligence."""

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any

import jedi

from ..async_utils import read_file_async, rglob_async
from ..exceptions import AnalysisError, FileAccessError, ProjectNotFoundError

logger = logging.getLogger(__name__)


class JediAnalyzer:
    """Wrapper around Jedi for semantic Python analysis."""

    def __init__(self, project_path: str = "."):
        """Initialize the Jedi analyzer.

        Args:
            project_path: Root path of the project to analyze

        Raises:
            ProjectNotFoundError: If the project path doesn't exist
        """
        self.project_path = Path(project_path)
        self.additional_paths: list[Path] = []  # For additional package paths

        # Validate project path exists
        if not self.project_path.exists():
            raise ProjectNotFoundError(str(project_path))

        try:
            self.project = jedi.Project(path=self.project_path)
            logger.info(f"Initialized JediAnalyzer for {self.project_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Jedi project: {e}")
            raise AnalysisError(
                f"Failed to initialize analyzer for {project_path}",
                file_path=str(project_path),
                error=str(e),
            ) from e

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
                raise AnalysisError(
                    f"Failed to search for symbol '{name}'",
                    operation="find_symbol",
                    symbol=name,
                    error=str(e),
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

    async def find_imports(self, module_name: str) -> list[dict[str, Any]]:
        """Find all imports of a specific module in the project.

        Args:
            module_name: Name of the module to find imports for

        Returns:
            List of import locations
        """
        results = []

        try:
            # Search for import statements across the project
            py_files = await rglob_async("*.py", self.project_path)
            for py_file in py_files:
                try:
                    source = await read_file_async(py_file)
                    script = jedi.Script(source, path=py_file, project=self.project)

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
            script = jedi.Script(source, path=function_def.module_path, project=self.project)

            # Find references (callers)
            refs = script.get_references(function_def.line, function_def.column)
            for ref in refs:
                if not ref.is_definition():
                    callers_list = result["callers"]
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

    async def list_packages(self) -> list[dict[str, Any]]:
        """List all Python packages in the project."""
        packages: list[dict[str, Any]] = []
        seen_packages = set()

        try:
            # Walk the project directory to find packages
            init_files = await rglob_async("__init__.py", self.project_path)
            for path in init_files:
                package_dir = path.parent
                rel_path = package_dir.relative_to(self.project_path)

                # Skip hidden directories and common non-package directories
                parts = rel_path.parts
                if any(
                    p.startswith(".") or p in ["__pycache__", "build", "dist", "egg-info"]
                    for p in parts
                ):
                    continue

                package_name = str(rel_path).replace(os.sep, ".")
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
                            "path": str(package_dir),
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

    async def list_modules(self) -> list[dict[str, Any]]:
        """List all Python modules with exports and metrics."""
        modules = []

        try:
            # Find all Python files in the project
            py_files = await rglob_async("*.py", self.project_path)
            for py_file in py_files:
                # Skip hidden directories and common non-source directories
                rel_path = py_file.relative_to(self.project_path)
                parts = rel_path.parts
                if any(
                    p.startswith(".") or p in ["__pycache__", "build", "dist", "tests", "test"]
                    for p in parts[:-1]
                ):
                    continue

                try:
                    # Get module import path
                    module_parts = list(rel_path.parts[:-1])  # directories
                    if py_file.name != "__init__.py":
                        module_parts.append(py_file.stem)
                    import_path = ".".join(module_parts) if module_parts else py_file.stem

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
                            "file": str(py_file),
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
        self, module_path: str, _visited: set[str] | None = None
    ) -> dict[str, Any]:
        """Analyze import dependencies for a module."""
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
            py_files = await rglob_async("*.py", self.project_path)
            for py_file in py_files:
                rel_path = py_file.relative_to(self.project_path)
                if not any(
                    p.startswith(".") or p in ["__pycache__", "build", "dist"]
                    for p in rel_path.parts
                ):
                    module_parts = list(rel_path.parts[:-1])
                    if py_file.name != "__init__.py":
                        module_parts.append(py_file.stem)
                    if module_parts:
                        project_modules.add(module_parts[0])

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
            py_files = await rglob_async("*.py", self.project_path)
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
                                        rel_path = py_file.relative_to(self.project_path)
                                        import_path = (
                                            str(rel_path).replace(os.sep, ".").replace(".py", "")
                                        )
                                        result["imported_by"].append(import_path)
                                        break
                            elif isinstance(node, ast.ImportFrom):
                                if node.module and (
                                    node.module == module_path
                                    or node.module.startswith(module_path + ".")
                                ):
                                    rel_path = py_file.relative_to(self.project_path)
                                    import_path = (
                                        str(rel_path).replace(os.sep, ".").replace(".py", "")
                                    )
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
                            deps = await self.analyze_dependencies(imported_module, _visited)
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

            info["file"] = str(module_file)

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
            result["file"] = str(name.module_path)

        if include_docstring:
            result["docstring"] = name.docstring()

        # Add import paths if requested and we have module information
        if include_import_paths and name.full_name:
            # Extract module path from full_name (everything except the last part)
            parts = name.full_name.split(".")
            if len(parts) > 1:
                module_path = ".".join(parts[:-1])
                file_path = str(name.module_path) if name.module_path else None
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
                    module_from_file = str(rel_path.with_suffix("")).replace(os.sep, ".")
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
