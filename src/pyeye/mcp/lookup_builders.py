"""Response assembly builders for the unified lookup tool.

Each builder takes a temporary resolution dict (with ``_resolved_via`` marker)
and produces the full spec-compliant response shape by calling enrichment
methods on the Jedi analyzer.
"""

import contextlib
import logging
from pathlib import Path
from typing import Any

import jedi

logger = logging.getLogger(__name__)


def _paginate(items: list, limit: int) -> dict[str, Any]:
    """Wrap a list in the ``{total, items}`` relationship-list shape.

    Structural lists (bases, methods, attributes, parameters) are plain arrays.
    Relationship lists use this helper so the caller always knows the true count
    even when truncated.

    Args:
        items: Full list of results.
        limit: Maximum number of items to include.

    Returns:
        Dict with ``total`` (int) and ``items`` (list capped at *limit*).
    """
    return {"total": len(items), "items": items[:limit]}


def _get_package_prefix(analyzer: Any) -> str | None:
    """Return the project root's package name if the root is itself a package.

    When the project root contains ``__init__.py``, the root directory is a
    Python package and its name must be prepended to all dotted paths that
    Jedi or ``_get_import_path_for_file`` produce (since those are relative
    to the root).

    Returns:
        The root directory name (e.g. ``"lookup_project"``), or *None* if the
        root is not a package.
    """
    project_path = Path(analyzer.project_path).resolve()
    if (project_path / "__init__.py").exists():
        return project_path.name
    return None


def _qualify_full_name(analyzer: Any, raw_full_name: str | None) -> str | None:
    """Ensure *raw_full_name* includes the project-root package prefix.

    Jedi and ``_get_import_path_for_file`` report dotted paths relative to
    the project root.  When the root IS a package this strips the leading
    component.  This helper re-adds it if missing.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        raw_full_name: The dotted path as reported by Jedi / import-path
            resolution.  May be ``None``.

    Returns:
        The corrected full_name, or *None* if *raw_full_name* is None.
    """
    if not raw_full_name:
        return raw_full_name
    prefix = _get_package_prefix(analyzer)
    if prefix and not raw_full_name.startswith(f"{prefix}.") and raw_full_name != prefix:
        return f"{prefix}.{raw_full_name}"
    return raw_full_name


def _module_ref_for_file(analyzer: Any, file_path: str) -> dict[str, Any]:
    """Build a navigable reference for the module containing *file_path*.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        file_path: POSIX file path string.

    Returns:
        A navigable ref dict with ``name``, ``full_name``, ``file``, ``line``
        (line is always ``None`` for a module-level ref).
    """
    module_path = analyzer._get_import_path_for_file(Path(file_path))
    if module_path:
        module_path = _qualify_full_name(analyzer, module_path)
        short_name = module_path.rsplit(".", 1)[-1] if module_path else Path(file_path).stem
    else:
        short_name = Path(file_path).stem
        module_path = short_name
    return {
        "name": short_name,
        "full_name": module_path,
        "file": file_path,
        "line": None,
    }


def _qualify_ref(analyzer: Any, ref: dict[str, Any]) -> dict[str, Any]:
    """Apply package prefix qualification to a navigable reference's full_name."""
    if ref and ref.get("full_name"):
        ref["full_name"] = _qualify_full_name(analyzer, ref["full_name"])
    return ref


def _get_jedi_names(analyzer: Any, file_path: str, *, all_scopes: bool = True) -> list[Any]:
    """Get Jedi Name objects from a file via ``script.get_names()``.

    Args:
        analyzer: A ``JediAnalyzer`` instance (needs ``.project``).
        file_path: POSIX file path.
        all_scopes: Whether to include nested scopes.

    Returns:
        List of Jedi Name objects.
    """
    source = Path(file_path).read_text(encoding="utf-8")
    script = jedi.Script(source, path=file_path, project=analyzer.project)
    result: list[Any] = script.get_names(all_scopes=all_scopes, definitions=True)
    return result


def _find_name_at(
    names: list[Any],
    target_name: str,
    target_line: int,
) -> Any | None:
    """Find a Jedi Name matching *target_name* at *target_line*.

    Args:
        names: List of Jedi Name objects to search.
        target_name: Expected ``name`` attribute.
        target_line: Expected ``line`` attribute.

    Returns:
        The matching Name, or ``None``.
    """
    for n in names:
        if n.name == target_name and n.line == target_line:
            return n
    return None


async def _build_class_result(
    analyzer: Any, name_info: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Assemble a full class response from a resolution stub.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        name_info: Temporary dict from resolution (must have ``file``, ``line``,
            ``name``, ``full_name``, etc.).
        limit: Cap for relationship lists (subclasses, references).

    Returns:
        Spec-compliant class result dict.
    """
    file_path = name_info["file"]
    target_name = name_info["name"]
    target_line = name_info["line"]

    qualified_full_name = _qualify_full_name(analyzer, name_info.get("full_name"))

    result: dict[str, Any] = {
        "type": "class",
        "name": target_name,
        "full_name": qualified_full_name,
        "file": file_path,
        "line": target_line,
        "column": name_info.get("column"),
        "docstring": None,
        "module": _module_ref_for_file(analyzer, file_path),
        "bases": [],
        "methods": [],
        "attributes": [],
        "subclasses": _paginate([], limit),
        "references": _paginate([], limit),
    }

    try:
        source = Path(file_path).read_text(encoding="utf-8")
        script = jedi.Script(source, path=file_path, project=analyzer.project)
        names = script.get_names(all_scopes=True, definitions=True)
        target = _find_name_at(names, target_name, target_line)

        if target is None:
            return result

        # Docstring
        with contextlib.suppress(Exception):
            result["docstring"] = target.docstring() or None

        # --- Bases (plain list of navigable refs) ---
        try:
            inferred = script.infer(target_line, name_info.get("column") or 0)
            if inferred:
                cls_obj = inferred[0]
                # Use Jedi's defined_names to access the class, but for bases
                # we go through the Name's internal API to get super classes.
                try:
                    # Access the internal tree node to get base class names
                    tree_node = cls_obj._name.tree_name
                    if tree_node is not None:
                        # Walk up to find the classdef node
                        classdef = tree_node.parent
                        while classdef is not None and classdef.type != "classdef":
                            classdef = classdef.parent
                        if classdef is not None:
                            # classdef children: 'class' NAME '(' arglist ')' ':' suite
                            # Find the arglist (base classes)
                            for child in classdef.children:
                                if hasattr(child, "type") and child.type in (
                                    "arglist",
                                    "atom",
                                ):
                                    # Extract base names
                                    for base_node in child.children:
                                        if hasattr(base_node, "value"):
                                            base_name = base_node.value
                                            if base_name not in (",", "(", ")"):
                                                base_refs = await analyzer._search_all_scopes(
                                                    base_name
                                                )
                                                if base_refs:
                                                    result["bases"].append(
                                                        _qualify_ref(
                                                            analyzer,
                                                            analyzer._build_navigable_ref(
                                                                base_refs[0]
                                                            ),
                                                        )
                                                    )
                                                else:
                                                    result["bases"].append(
                                                        {
                                                            "name": base_name,
                                                            "full_name": None,
                                                            "file": None,
                                                            "line": None,
                                                        }
                                                    )
                                elif hasattr(child, "value") and child.type == "name":
                                    # Single base class (no arglist)
                                    base_name = child.value
                                    if base_name not in (target_name, "(", ")", ":", "class"):
                                        base_refs = await analyzer._search_all_scopes(base_name)
                                        if base_refs:
                                            result["bases"].append(
                                                _qualify_ref(
                                                    analyzer,
                                                    analyzer._build_navigable_ref(base_refs[0]),
                                                )
                                            )
                                        else:
                                            result["bases"].append(
                                                {
                                                    "name": base_name,
                                                    "full_name": None,
                                                    "file": None,
                                                    "line": None,
                                                }
                                            )
                except Exception:
                    logger.debug(f"Could not extract base classes for {target_name}")
        except Exception:
            logger.debug(f"Could not infer class {target_name} for base extraction")

        # If we didn't find bases via tree, try AST fallback
        if not result["bases"]:
            try:
                import ast

                tree_ast = ast.parse(source)
                for node in ast.walk(tree_ast):
                    if (
                        isinstance(node, ast.ClassDef)
                        and node.name == target_name
                        and node.lineno == target_line
                    ):
                        for base in node.bases:
                            base_name_str = ast.unparse(base)
                            # Try to resolve the base name
                            base_refs = await analyzer._search_all_scopes(
                                base_name_str.split(".")[-1]
                            )
                            if base_refs:
                                result["bases"].append(
                                    _qualify_ref(
                                        analyzer, analyzer._build_navigable_ref(base_refs[0])
                                    )
                                )
                            else:
                                result["bases"].append(
                                    {
                                        "name": base_name_str,
                                        "full_name": None,
                                        "file": None,
                                        "line": None,
                                    }
                                )
                        break
            except Exception:
                logger.debug(f"AST fallback for bases of {target_name} also failed")

        # --- Methods and Attributes (plain lists) ---
        try:
            defined = target.defined_names()
            for dn in defined:
                if dn.type == "function":
                    enriched = await analyzer._enrich_method(dn)
                    result["methods"].append(enriched)
                elif dn.type in ("statement", "instance"):
                    enriched = await analyzer._enrich_attribute(dn, source)
                    result["attributes"].append(enriched)
        except Exception:
            logger.debug(f"Could not enumerate members of {target_name}")

        # --- Subclasses (relationship list) ---
        try:
            subclasses_raw = await analyzer.find_subclasses(target_name)
            sub_items = []
            for sc in subclasses_raw:
                sub_items.append(
                    {
                        "name": sc.get("name"),
                        "full_name": sc.get("full_name"),
                        "file": sc.get("file"),
                        "line": sc.get("line"),
                    }
                )
            result["subclasses"] = _paginate(sub_items, limit)
        except Exception:
            logger.debug(f"Could not find subclasses of {target_name}")

        # --- References (relationship list) ---
        try:
            column = name_info.get("column") or 0
            refs_raw = await analyzer.find_references(
                file_path, target_line, column, include_definitions=False
            )
            ref_items = []
            for ref in refs_raw:
                ref_items.append(
                    {
                        "name": ref.get("name"),
                        "full_name": _qualify_full_name(analyzer, ref.get("full_name")),
                        "file": ref.get("file"),
                        "line": ref.get("line"),
                    }
                )
            result["references"] = _paginate(ref_items, limit)
        except Exception:
            logger.debug(f"Could not find references to {target_name}")

    except Exception as e:
        logger.warning(f"Error building class result for {target_name}: {e}")

    return result


async def _build_function_result(
    analyzer: Any, name_info: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Assemble a full function/method response from a resolution stub.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        name_info: Temporary dict from resolution.
        limit: Cap for relationship lists (callers, callees, references).

    Returns:
        Spec-compliant function result dict.
    """
    file_path = name_info["file"]
    target_name = name_info["name"]
    target_line = name_info["line"]

    qualified_full_name = _qualify_full_name(analyzer, name_info.get("full_name"))

    result: dict[str, Any] = {
        "type": name_info.get("type", "function"),
        "name": target_name,
        "full_name": qualified_full_name,
        "file": file_path,
        "line": target_line,
        "column": name_info.get("column"),
        "docstring": None,
        "module": _module_ref_for_file(analyzer, file_path),
        "signature": None,
        "return_type": None,
        "parameters": [],
        "callers": _paginate([], limit),
        "callees": _paginate([], limit),
        "references": _paginate([], limit),
    }

    try:
        names = _get_jedi_names(analyzer, file_path)
        target = _find_name_at(names, target_name, target_line)

        if target is not None:
            # Docstring
            with contextlib.suppress(Exception):
                result["docstring"] = target.docstring() or None

            # Enrich with signature, return_type, parameters
            try:
                enriched = await analyzer._enrich_method(target)
                result["signature"] = enriched.get("signature")
                result["return_type"] = enriched.get("return_type")
                result["parameters"] = enriched.get("parameters", [])
            except Exception:
                logger.debug(f"Could not enrich method {target_name}")

        # --- Callers and Callees (relationship lists) ---
        try:
            hierarchy = await analyzer.get_call_hierarchy(target_name, file=file_path)
            if "error" not in hierarchy:
                caller_items = []
                for c in hierarchy.get("callers", []):
                    caller_items.append(
                        {
                            "name": c.get("name"),
                            "full_name": c.get("full_name"),
                            "file": c.get("file"),
                            "line": c.get("line"),
                        }
                    )
                result["callers"] = _paginate(caller_items, limit)

                callee_items = []
                for c in hierarchy.get("callees", []):
                    callee_items.append(
                        {
                            "name": c.get("name"),
                            "full_name": c.get("full_name"),
                            "file": c.get("file"),
                            "line": c.get("line"),
                        }
                    )
                result["callees"] = _paginate(callee_items, limit)
        except Exception:
            logger.debug(f"Could not get call hierarchy for {target_name}")

        # --- References (relationship list) ---
        try:
            column = name_info.get("column") or 0
            refs_raw = await analyzer.find_references(
                file_path, target_line, column, include_definitions=False
            )
            ref_items = []
            for ref in refs_raw:
                ref_items.append(
                    {
                        "name": ref.get("name"),
                        "full_name": _qualify_full_name(analyzer, ref.get("full_name")),
                        "file": ref.get("file"),
                        "line": ref.get("line"),
                    }
                )
            result["references"] = _paginate(ref_items, limit)
        except Exception:
            logger.debug(f"Could not find references to {target_name}")

    except Exception as e:
        logger.warning(f"Error building function result for {target_name}: {e}")

    return result


async def _build_module_result(
    analyzer: Any, name_info: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Assemble a full module response from a resolution stub.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        name_info: Temporary dict from resolution.
        limit: Cap for relationship lists.

    Returns:
        Spec-compliant module result dict.
    """
    file_path = name_info["file"]
    raw_module_name = name_info.get("full_name") or name_info.get("name")
    module_full_name = _qualify_full_name(analyzer, raw_module_name)

    # Parent package ref
    parts = module_full_name.rsplit(".", 1) if module_full_name else []
    if len(parts) == 2:
        parent_ref: dict[str, Any] | None = {
            "name": parts[0].rsplit(".", 1)[-1],
            "full_name": parts[0],
            "file": None,
            "line": None,
        }
    else:
        parent_ref = None

    result: dict[str, Any] = {
        "type": "module",
        "name": name_info.get("name"),
        "full_name": module_full_name,
        "file": file_path,
        "line": None,
        "column": None,
        "docstring": None,
        "module": parent_ref,
        "classes": _paginate([], limit),
        "functions": _paginate([], limit),
        "variables": _paginate([], limit),
        "imports": _paginate([], limit),
        "imported_by": _paginate([], limit),
    }

    try:
        source = Path(file_path).read_text(encoding="utf-8")
        script = jedi.Script(source, path=file_path, project=analyzer.project)

        # Docstring (first expression if it's a string)
        try:
            import ast

            tree = ast.parse(source)
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                result["docstring"] = tree.body[0].value.value
        except Exception:
            pass

        # Get all top-level names
        names = script.get_names(all_scopes=False, definitions=True)

        # --- Classes (relationship list) ---
        class_items = []
        for n in names:
            if n.type == "class":
                class_items.append(
                    {
                        "name": n.name,
                        "full_name": _qualify_full_name(analyzer, n.full_name),
                        "file": Path(n.module_path).as_posix() if n.module_path else file_path,
                        "line": n.line,
                    }
                )
        result["classes"] = _paginate(class_items, limit)

        # --- Functions (relationship list) ---
        func_items = []
        for n in names:
            if n.type == "function":
                func_items.append(
                    {
                        "name": n.name,
                        "full_name": _qualify_full_name(analyzer, n.full_name),
                        "file": Path(n.module_path).as_posix() if n.module_path else file_path,
                        "line": n.line,
                    }
                )
        result["functions"] = _paginate(func_items, limit)

        # --- Variables (relationship list) ---
        try:
            variables = await analyzer._get_module_variables(script, source)
            result["variables"] = _paginate(variables, limit)
        except Exception:
            logger.debug(f"Could not extract variables from {file_path}")

        # --- Imports (relationship list) ---
        import_items = []
        for n in names:
            if n.type == "module" and n.is_definition():
                import_items.append(
                    {
                        "name": n.name,
                        "full_name": n.full_name,  # imports keep their original full_name
                        "file": Path(n.module_path).as_posix() if n.module_path else None,
                        "line": n.line,
                    }
                )
        result["imports"] = _paginate(import_items, limit)

        # --- Imported_by (relationship list) ---
        try:
            module_name = module_full_name or name_info.get("name")
            if module_name:
                imported_by_raw = await analyzer.find_imports(module_name, scope="main")
                ib_items = []
                for imp in imported_by_raw:
                    ib_items.append(
                        {
                            "name": imp.get("name") or imp.get("importing_module"),
                            "full_name": imp.get("full_name") or imp.get("importing_module"),
                            "file": imp.get("file"),
                            "line": imp.get("line"),
                        }
                    )
                result["imported_by"] = _paginate(ib_items, limit)
        except Exception:
            logger.debug(f"Could not find importers of {module_full_name}")

    except Exception as e:
        logger.warning(f"Error building module result for {module_full_name}: {e}")

    return result


async def _build_basic_result(analyzer: Any, name_info: dict[str, Any]) -> dict[str, Any]:
    """Assemble a basic result for types that don't have a dedicated builder.

    Used for statements, instances, and other non-class/function/module types.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        name_info: Temporary dict from resolution.

    Returns:
        A minimal result dict with standard fields.
    """
    file_path = name_info.get("file")

    result: dict[str, Any] = {
        "type": name_info.get("type"),
        "name": name_info.get("name"),
        "full_name": _qualify_full_name(analyzer, name_info.get("full_name")),
        "file": file_path,
        "line": name_info.get("line"),
        "column": name_info.get("column"),
        "docstring": None,
        "module": _module_ref_for_file(analyzer, file_path) if file_path else None,
    }

    # Try to get docstring and type info
    if file_path and name_info.get("line"):
        try:
            names = _get_jedi_names(analyzer, file_path)
            target = _find_name_at(names, name_info["name"], name_info["line"])
            if target is not None:
                with contextlib.suppress(Exception):
                    result["docstring"] = target.docstring() or None
        except Exception:
            pass

    return result


async def assemble_response(
    analyzer: Any, resolution: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Dispatch a resolution stub to the appropriate builder.

    If the resolution dict contains a ``_resolved_via`` key it is a successful
    resolution stub that needs enrichment.  Otherwise it is already a terminal
    response (not-found, ambiguous, or error) and is returned unchanged.

    Args:
        analyzer: A ``JediAnalyzer`` instance.
        resolution: The dict returned by the resolution functions.
        limit: Cap for relationship lists.

    Returns:
        The enriched or pass-through response dict.
    """
    if "_resolved_via" not in resolution:
        return resolution

    resolved_type = resolution.get("type")
    try:
        if resolved_type == "class":
            return await _build_class_result(analyzer, resolution, limit)
        elif resolved_type in ("function", "method"):
            return await _build_function_result(analyzer, resolution, limit)
        elif resolved_type == "module":
            return await _build_module_result(analyzer, resolution, limit)
        else:
            return await _build_basic_result(analyzer, resolution)
    except Exception as e:
        logger.warning(f"Error assembling response for {resolution.get('name')}: {e}")
        # Fall back to returning the resolution stub minus the internal marker
        fallback = {k: v for k, v in resolution.items() if k != "_resolved_via"}
        return fallback
