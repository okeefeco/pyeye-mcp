"""Unified lookup tool for any Python identifier form."""

import logging
from pathlib import Path
from typing import Any

from .lookup_builders import assemble_response

logger = logging.getLogger(__name__)


async def lookup(
    identifier: str | None = None,
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    project_path: str = ".",
    limit: int = 20,
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
        result = await _resolve_coordinates(file, line, column, project_path)
    elif any_coord:
        # Branch 3: Partial coordinates — reject with a clear message.
        return {
            "error": (
                "Coordinates incomplete: provide all three (file, line, column)"
                " or use identifier instead"
            )
        }
    elif identifier is not None:
        # Branch 2: Identifier provided, no (or partial) coordinates.
        case_type = _classify_identifier(identifier)
        if case_type == "bare_name":
            result = await _resolve_bare_name(identifier, project_path, limit)
        elif case_type == "file_path":
            result = await _resolve_file_path(identifier, project_path)
        else:  # dotted_path
            result = await _resolve_dotted_path(identifier, project_path, limit)
    else:
        # Branch 4: Nothing provided.
        return {"error": "Either identifier or file+line+column required"}

    # Enrich resolution stubs into full spec-compliant responses.
    if "_resolved_via" in result:
        from .server import get_analyzer

        analyzer = get_analyzer(project_path)
        return await assemble_response(analyzer, result, limit)

    return result


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


async def _resolve_coordinates(
    file: str, line: int, column: int, project_path: str
) -> dict[str, Any]:
    """Resolve a symbol using file + line + column coordinates."""
    try:
        import jedi

        from .server import get_analyzer

        file_path = Path(file)
        if not file_path.exists():
            return {
                "found": False,
                "identifier": f"{file}:{line}:{column}",
                "searched": {
                    "indexed": False,
                    "as_module": False,
                    "as_symbol": False,
                    "scopes": [],
                    "packages": 0,
                    "modules": 0,
                },
            }

        analyzer = get_analyzer(project_path)
        source = file_path.read_text(encoding="utf-8")
        script = jedi.Script(source, path=file, project=analyzer.project)

        try:
            inferred = script.infer(line, column)
        except Exception:
            inferred = []

        if inferred:
            inf = inferred[0]
            return {
                "type": inf.type,
                "name": inf.name,
                "full_name": inf.full_name,
                "file": Path(inf.module_path).as_posix() if inf.module_path else None,
                "line": inf.line,
                "column": column,
                "_resolved_via": "coordinates",
            }
        else:
            # Fall back to goto_definitions
            try:
                definitions = script.goto(line, column)
            except Exception:
                definitions = []

            if definitions:
                defn = definitions[0]
                return {
                    "type": defn.type,
                    "name": defn.name,
                    "full_name": defn.full_name,
                    "file": Path(defn.module_path).as_posix() if defn.module_path else None,
                    "line": defn.line,
                    "column": column,
                    "_resolved_via": "coordinates",
                }
            return {
                "found": False,
                "identifier": f"{file}:{line}:{column}",
                "searched": {
                    "indexed": True,
                    "as_module": False,
                    "as_symbol": True,
                    "scopes": ["main"],
                    "packages": 0,
                    "modules": 0,
                },
            }
    except Exception as e:
        logger.warning(f"Coordinate resolution error: {e}")
        return {
            "found": False,
            "identifier": f"{file}:{line}:{column}",
            "searched": {
                "indexed": False,
                "as_module": False,
                "as_symbol": False,
                "scopes": [],
                "packages": 0,
                "modules": 0,
            },
        }


async def _resolve_bare_name(identifier: str, project_path: str, limit: int) -> dict[str, Any]:
    """Resolve a bare name identifier (no dots or path separators)."""
    try:
        from .server import get_analyzer

        analyzer = get_analyzer(project_path)
        results = await analyzer.find_symbol(identifier)

        if len(results) == 0:
            return {
                "found": False,
                "identifier": identifier,
                "searched": {
                    "indexed": True,
                    "as_module": False,
                    "as_symbol": True,
                    "scopes": ["main"],
                    "packages": 0,
                    "modules": 0,
                },
            }
        elif len(results) == 1:
            r = results[0]
            return {
                "type": r.get("type"),
                "name": r.get("name"),
                "full_name": r.get("full_name"),
                "file": r.get("file"),
                "line": r.get("line"),
                "column": r.get("column"),
                "_resolved_via": "bare_name",
            }
        else:
            # Ambiguous — multiple matches
            capped = results[:limit]
            items = []
            for r in capped:
                full_name = r.get("full_name") or ""
                # Extract parent module from full_name (everything before last dot)
                parts = full_name.rsplit(".", 1)
                parent_module = parts[0] if len(parts) == 2 else full_name
                items.append(
                    {
                        "name": r.get("name"),
                        "full_name": full_name,
                        "file": r.get("file"),
                        "line": r.get("line"),
                        "type": r.get("type"),
                        "context": {
                            "name": parent_module.rsplit(".", 1)[-1] if parent_module else None,
                            "full_name": parent_module or None,
                            "file": r.get("file"),
                            "line": None,
                        },
                    }
                )
            return {
                "ambiguous": True,
                "identifier": identifier,
                "matches": {
                    "total": len(results),
                    "items": items,
                },
            }
    except Exception as e:
        logger.warning(f"Bare name resolution error for '{identifier}': {e}")
        return {
            "found": False,
            "identifier": identifier,
            "searched": {
                "indexed": False,
                "as_module": False,
                "as_symbol": False,
                "scopes": [],
                "packages": 0,
                "modules": 0,
            },
        }


async def _resolve_file_path(identifier: str, project_path: str) -> dict[str, Any]:
    """Resolve a file path identifier (with optional :line suffix)."""
    try:
        from .server import get_analyzer

        # Parse optional :line suffix
        line_num: int | None = None
        if ".py:" in identifier:
            path_part, line_suffix = identifier.rsplit(":", 1)
            try:
                line_num = int(line_suffix)
            except ValueError:
                path_part = identifier
        else:
            path_part = identifier

        # Resolve the file path
        file_path = Path(path_part)
        if not file_path.is_absolute():
            file_path = Path(project_path).resolve() / file_path

        if not file_path.exists():
            return {
                "found": False,
                "identifier": identifier,
                "searched": {
                    "indexed": True,
                    "as_module": False,
                    "as_symbol": False,
                    "scopes": ["main"],
                    "packages": 0,
                    "modules": 0,
                },
            }

        analyzer = get_analyzer(project_path)

        if line_num is not None:
            # Resolve symbol at the given line using Jedi
            import jedi

            try:
                source = file_path.read_text(encoding="utf-8")
                script = jedi.Script(source, path=str(file_path), project=analyzer.project)
                # Try infer first, then goto
                try:
                    names = script.get_names(all_scopes=True, definitions=True)
                    # Find a name that spans this line
                    best = None
                    for n in names:
                        if n.line == line_num:
                            best = n
                            break
                    if best is None:
                        # Try infer at position (column 0)
                        inferred = script.infer(line_num, 0)
                        if inferred:
                            inf = inferred[0]
                            return {
                                "type": inf.type,
                                "name": inf.name,
                                "full_name": inf.full_name,
                                "file": (
                                    Path(inf.module_path).as_posix()
                                    if inf.module_path
                                    else file_path.as_posix()
                                ),
                                "line": inf.line,
                                "column": 0,
                                "_resolved_via": "file_path",
                            }
                    else:
                        return {
                            "type": best.type,
                            "name": best.name,
                            "full_name": best.full_name,
                            "file": file_path.as_posix(),
                            "line": best.line,
                            "column": best.column,
                            "_resolved_via": "file_path",
                        }
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"File+line resolution error: {e}")

            return {
                "found": False,
                "identifier": identifier,
                "searched": {
                    "indexed": True,
                    "as_module": False,
                    "as_symbol": True,
                    "scopes": ["main"],
                    "packages": 0,
                    "modules": 0,
                },
            }
        else:
            # Resolve to module
            module_path = analyzer._get_import_path_for_file(file_path)
            name = file_path.stem
            return {
                "type": "module",
                "name": name,
                "full_name": module_path or name,
                "file": file_path.as_posix(),
                "line": 1,
                "column": 0,
                "_resolved_via": "file_path",
            }
    except Exception as e:
        logger.warning(f"File path resolution error for '{identifier}': {e}")
        return {
            "found": False,
            "identifier": identifier,
            "searched": {
                "indexed": False,
                "as_module": False,
                "as_symbol": False,
                "scopes": [],
                "packages": 0,
                "modules": 0,
            },
        }


async def _resolve_dotted_path(identifier: str, project_path: str, limit: int) -> dict[str, Any]:
    """Resolve a dotted path (module or fully-qualified symbol name)."""
    try:
        from .server import get_analyzer

        analyzer = get_analyzer(project_path)

        # Try as module first
        try:
            module_info = await analyzer.get_module_info(identifier)
            if "error" not in module_info and module_info.get("file"):
                return {
                    "type": "module",
                    "name": identifier.rsplit(".", 1)[-1],
                    "full_name": identifier,
                    "file": module_info.get("file"),
                    "line": 1,
                    "column": 0,
                    "_resolved_via": "dotted_path",
                }
        except Exception:
            pass

        # Not a module — split on last dot, search for symbol
        parts = identifier.rsplit(".", 1)
        if len(parts) == 2:
            _parent_module, symbol_name = parts

            # First try find_symbol with the full name
            try:
                results = await analyzer.find_symbol(identifier)
                matching = [r for r in results if r.get("full_name") == identifier]
                if len(matching) == 1:
                    r = matching[0]
                    return {
                        "type": r.get("type"),
                        "name": r.get("name"),
                        "full_name": r.get("full_name"),
                        "file": r.get("file"),
                        "line": r.get("line"),
                        "column": r.get("column"),
                        "_resolved_via": "dotted_path",
                    }
                elif len(matching) > 1:
                    capped = matching[:limit]
                    items = _build_ambiguous_items(capped)
                    return {
                        "ambiguous": True,
                        "identifier": identifier,
                        "matches": {"total": len(matching), "items": items},
                    }
            except Exception:
                pass

            # Exact match failed — try the bare symbol name and filter by full_name
            try:
                results = await analyzer.find_symbol(symbol_name)
                matching = [r for r in results if r.get("full_name") == identifier]
                if len(matching) == 1:
                    r = matching[0]
                    return {
                        "type": r.get("type"),
                        "name": r.get("name"),
                        "full_name": r.get("full_name"),
                        "file": r.get("file"),
                        "line": r.get("line"),
                        "column": r.get("column"),
                        "_resolved_via": "dotted_path",
                    }
                elif len(matching) > 1:
                    capped = matching[:limit]
                    items = _build_ambiguous_items(capped)
                    return {
                        "ambiguous": True,
                        "identifier": identifier,
                        "matches": {"total": len(matching), "items": items},
                    }
            except Exception:
                pass

        return {
            "found": False,
            "identifier": identifier,
            "searched": {
                "indexed": True,
                "as_module": True,
                "as_symbol": True,
                "scopes": ["main"],
                "packages": 0,
                "modules": 0,
            },
        }
    except Exception as e:
        logger.warning(f"Dotted path resolution error for '{identifier}': {e}")
        return {
            "found": False,
            "identifier": identifier,
            "searched": {
                "indexed": False,
                "as_module": False,
                "as_symbol": False,
                "scopes": [],
                "packages": 0,
                "modules": 0,
            },
        }


def _build_ambiguous_items(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build items list for an ambiguous response."""
    items = []
    for r in results:
        full_name = r.get("full_name") or ""
        parts = full_name.rsplit(".", 1)
        parent_module = parts[0] if len(parts) == 2 else full_name
        items.append(
            {
                "name": r.get("name"),
                "full_name": full_name,
                "file": r.get("file"),
                "line": r.get("line"),
                "type": r.get("type"),
                "context": {
                    "name": parent_module.rsplit(".", 1)[-1] if parent_module else None,
                    "full_name": parent_module or None,
                    "file": r.get("file"),
                    "line": None,
                },
            }
        )
    return items
