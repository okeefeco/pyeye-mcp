"""Jedi-based analyzer for Python code intelligence."""

import logging
from pathlib import Path
from typing import Any

import jedi

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

    def find_symbol(self, name: str, fuzzy: bool = False) -> list[dict[str, Any]]:
        """Find symbol definitions in the project."""
        results = []

        try:
            search_results = self.project.search(name, all_scopes=True)

            for result in search_results:
                if not fuzzy and result.name != name:
                    continue

                try:
                    results.append(self._serialize_name(result))
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

    def goto_definition(self, file: str, line: int, column: int) -> dict[str, Any] | None:
        """Get definition location from a position."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            definitions = script.goto(line, column)

            if definitions:
                return self._serialize_name(definitions[0], include_docstring=True)

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in goto_definition: {e}")
            # Return None for non-critical errors (e.g., no definition found)

        return None

    def find_references(
        self, file: str, line: int, column: int, include_definitions: bool = True
    ) -> list[dict[str, Any]]:
        """Find all references to a symbol."""
        results: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = file_path.read_text()
            script = jedi.Script(source, path=file_path, project=self.project)
            references = script.get_references(line, column, include_builtins=False)

            for ref in references:
                if not include_definitions and ref.is_definition():
                    continue

                serialized = self._serialize_name(ref)
                serialized["is_definition"] = ref.is_definition()
                results.append(serialized)

        except FileAccessError:
            raise  # Re-raise file access errors
        except Exception as e:
            logger.error(f"Error in find_references: {e}")
            # Return partial results if any

        return results

    def get_completions(self, file: str, line: int, column: int) -> list[dict[str, Any]]:
        """Get code completions at a position."""
        completions: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                raise FileAccessError(f"File not found: {file}", file, "read")

            source = file_path.read_text()
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

    def get_signature_help(self, file: str, line: int, column: int) -> dict[str, Any] | None:
        """Get signature help for function calls."""
        try:
            file_path = Path(file)
            if not file_path.exists():
                return None

            source = file_path.read_text()
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

    def analyze_imports(self, file: str) -> list[dict[str, Any]]:
        """Analyze imports in a file."""
        imports: list[dict[str, Any]] = []

        try:
            file_path = Path(file)
            if not file_path.exists():
                return imports

            source = file_path.read_text()
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

    def _serialize_name(
        self, name: jedi.api.classes.Name, include_docstring: bool = False
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

        return result
