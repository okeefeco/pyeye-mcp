"""Unified lookup tool for any Python identifier form."""

from typing import Any


async def lookup(
    identifier: str | None = None,
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    project_path: str = ".",  # noqa: ARG001
    limit: int = 20,  # noqa: ARG001
) -> dict[str, Any]:
    """Python: Look up any identifier — name, full dotted path, file path, or coordinates.

    Returns comprehensive structural information about the resolved Python object.

    Two calling conventions (coordinates take precedence if both provided):
    1. Coordinates: file + line + column (precise, unambiguous)
    2. Identifier: any Python identifier form (convenient; may need disambiguation)

    Identifier forms accepted:
    - Bare name: ``Config``, ``MyClass``, ``my_function``
    - Dotted path: ``pyeye.mcp.server.ServiceManager``
    - File path: ``src/pyeye/server.py``, ``server.py``, ``server.py:42``

    Args:
        identifier: Any Python identifier — bare name, dotted module path, or file path.
            Ignored if all three coordinates are provided.
        file: Path to the file (required with line and column for coordinate lookup)
        line: Line number, 1-indexed (required with file and column)
        column: Column number, 0-indexed (required with file and line)
        project_path: Root directory of the project to analyse
        limit: Maximum number of results to return for ambiguous lookups
    """
    # Determine which branch to take based on supplied arguments.
    all_coords = file is not None and line is not None and column is not None
    any_coord = file is not None or line is not None or column is not None

    if all_coords:
        # Branch 1: All coordinates provided — use them (ignore identifier).
        return {"error": "Coordinate resolution not yet implemented"}

    if any_coord:
        # Branch 3: Partial coordinates — reject with a clear message.
        return {
            "error": (
                "Coordinates incomplete: provide all three (file, line, column)"
                " or use identifier instead"
            )
        }

    if identifier is not None:
        # Branch 2: Identifier provided, no (or partial) coordinates.
        case_type = _classify_identifier(identifier)
        return {
            "error": (f"Identifier resolution not yet implemented (classified as: {case_type})")
        }

    # Branch 4: Nothing provided.
    return {"error": "Either identifier or file+line+column required"}


def _classify_identifier(identifier: str) -> str:
    """Classify an identifier string into one of three canonical forms.

    Args:
        identifier: Raw identifier string supplied by the caller.

    Returns:
        One of ``"bare_name"``, ``"file_path"``, or ``"dotted_path"``.
    """
    # File path: contains a path separator OR ends with .py OR matches name.py:N
    # The last rule handles "server.py:42" which doesn't literally end in ".py".
    has_path_sep = "/" in identifier or "\\" in identifier
    ends_with_py = identifier.endswith(".py")
    has_py_colon = ".py:" in identifier  # e.g. "server.py:42"
    if has_path_sep or ends_with_py or has_py_colon:
        return "file_path"

    # Dotted path: contains dots but no path separators (already ruled out above)
    if "." in identifier:
        return "dotted_path"

    # Bare name: no dots, no path separators, does not end with .py
    return "bare_name"
