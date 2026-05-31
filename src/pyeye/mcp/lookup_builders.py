"""Response assembly builders for the unified lookup tool.

Each builder takes a temporary resolution dict (with ``_resolved_via`` marker)
and produces the full spec-compliant response shape by calling enrichment
methods on the Jedi analyzer.
"""

import ast
import contextlib
import logging
from pathlib import Path
from typing import Any

import jedi

from .. import file_artifact_cache

logger = logging.getLogger(__name__)


def _paginate(items: list, limit: int) -> dict[str, Any]:
    """Wrap a list in the ``{total, items}`` relationship-list shape."""
    return {"total": len(items), "items": items[:limit]}


def _module_ref_for_file(analyzer: Any, file_path: str) -> dict[str, Any]:
    """Build a navigable reference for the module containing *file_path*.

    Uses Jedi's project configuration to derive the correct dotted module path.
    """
    # Use a Jedi script (cached) to get the module's full_name directly from Jedi.
    # Bucket 1: analysis input — cache returns Script, source never escapes.
    try:
        script = file_artifact_cache.get_script(file_path, analyzer.project)
        # Module-level names give us the module's context
        context = script.get_context()
        if context and context.full_name:
            module_path = context.full_name
            short_name = module_path.rsplit(".", 1)[-1]
            return {
                "name": short_name,
                "full_name": module_path,
                "file": file_path,
                "line": None,
            }
    except Exception:
        pass

    # Fallback: use _get_import_path_for_file
    module_path = analyzer._get_import_path_for_file(Path(file_path))
    if module_path:
        short_name = module_path.rsplit(".", 1)[-1]
    else:
        short_name = Path(file_path).stem
        module_path = short_name
    return {
        "name": short_name,
        "full_name": module_path,
        "file": file_path,
        "line": None,
    }


def _make_script(analyzer: Any, file_path: str) -> jedi.Script:
    """Return a cached Jedi Script for a file.

    Bucket 1: analysis input.  Source text is read inside the cache and not
    returned to the caller — pyeye is the semantic layer; raw source belongs
    to the agent's Read tool.
    """
    return file_artifact_cache.get_script(file_path, analyzer.project)


def _get_jedi_names(analyzer: Any, file_path: str, *, all_scopes: bool = True) -> list[Any]:
    """Get Jedi Name objects from a file via ``script.get_names()``.

    Bucket 1: analysis input — uses the cached Script.
    """
    script = file_artifact_cache.get_script(file_path, analyzer.project)
    result: list[Any] = script.get_names(all_scopes=all_scopes, definitions=True)
    return result


def _find_name_at(
    names: list[Any],
    target_name: str,
    target_line: int,
) -> Any | None:
    """Find a Jedi Name matching *target_name* at *target_line*."""
    for n in names:
        if n.name == target_name and n.line == target_line:
            return n
    return None


def _nav_ref(name_obj: Any) -> dict[str, Any]:
    """Build a navigable reference from a Jedi Name object.

    Uses Jedi's own full_name — which is now correct because the Jedi project
    root is configured to include the package name.
    """
    return {
        "name": name_obj.name,
        "full_name": name_obj.full_name,
        "file": Path(name_obj.module_path).as_posix() if name_obj.module_path else None,
        "line": name_obj.line,
    }


async def _resolve_bases_via_goto(
    script: jedi.Script, tree: ast.Module, target_name: str, target_line: int
) -> list[dict[str, Any]]:
    """Resolve base classes using script.goto() on each base class position.

    Uses the pre-parsed AST to find the base class node positions in the
    class definition, then calls script.goto() on each to follow the actual
    import chain.  This is correct because goto() resolves through imports,
    unlike a global name search which can match unrelated classes with the
    same name.

    Bucket 1: AST is supplied by the cached ``file_artifact_cache.get_ast``.
    """
    bases: list[dict[str, Any]] = []
    try:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ClassDef)
                and node.name == target_name
                and node.lineno == target_line
            ):
                for base in node.bases:
                    # Get the position of the base class name in source
                    # For simple names: base.col_offset points to the name
                    # For dotted names (module.Class): we want the last component
                    if isinstance(base, ast.Attribute):
                        # e.g., module.ClassName — goto on the attribute name
                        base_line = base.end_lineno or base.lineno
                        base_col = (
                            base.end_col_offset - len(base.attr)
                            if base.end_col_offset
                            else base.col_offset
                        )
                    else:
                        # Simple name
                        base_line = base.lineno
                        base_col = base.col_offset

                    try:
                        definitions = script.goto(base_line, base_col)
                        if definitions:
                            bases.append(_nav_ref(definitions[0]))
                        else:
                            # goto failed — return what we can from AST
                            bases.append(
                                {
                                    "name": ast.unparse(base),
                                    "full_name": None,
                                    "file": None,
                                    "line": None,
                                }
                            )
                    except Exception:
                        bases.append(
                            {
                                "name": ast.unparse(base),
                                "full_name": None,
                                "file": None,
                                "line": None,
                            }
                        )
                break
    except Exception:
        logger.debug(f"Could not resolve bases for {target_name} at line {target_line}")
    return bases


async def _build_class_result(
    analyzer: Any, name_info: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Assemble a full class response from a resolution stub."""
    file_path = name_info["file"]
    target_name = name_info["name"]
    target_line = name_info["line"]

    result: dict[str, Any] = {
        "type": "class",
        "name": target_name,
        "full_name": name_info.get("full_name"),
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
        script = _make_script(analyzer, file_path)
        tree = file_artifact_cache.get_ast(file_path)
        names = script.get_names(all_scopes=True, definitions=True)
        target = _find_name_at(names, target_name, target_line)

        if target is None:
            return result

        # Docstring
        with contextlib.suppress(Exception):
            result["docstring"] = target.docstring() or None

        # --- Bases via script.goto() (follows imports correctly) ---
        # Bucket 1: AST passed in directly from cache; no source text exchanged.
        result["bases"] = await _resolve_bases_via_goto(script, tree, target_name, target_line)

        # --- Methods and Attributes (plain lists) ---
        # TODO(api-redesign): 2026-05-02 — _enrich_attribute still requires source text
        # (existing analyzer contract).  This is the only remaining read here; classified
        # bucket 4 (bridge read) — the analyzer-side call sites have been migrated to
        # cache.get_ast / cache.get_script in this same commit; this module-level read is
        # the bridge until _enrich_attribute is reshaped to take an AST directly (out of
        # scope for #316 Task 1.5).
        analyzer_source: str | None = None
        try:
            defined = target.defined_names()
            for dn in defined:
                if dn.type == "function":
                    enriched = await analyzer._enrich_method(dn)
                    result["methods"].append(enriched)
                elif dn.type in ("statement", "instance"):
                    if analyzer_source is None:
                        analyzer_source = Path(file_path).read_text(encoding="utf-8")
                    enriched = await analyzer._enrich_attribute(dn, analyzer_source)
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
                        "full_name": ref.get("full_name"),
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
    """Assemble a full function/method response from a resolution stub."""
    file_path = name_info["file"]
    target_name = name_info["name"]
    target_line = name_info["line"]

    result: dict[str, Any] = {
        "type": name_info.get("type", "function"),
        "name": target_name,
        "full_name": name_info.get("full_name"),
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
                        "full_name": ref.get("full_name"),
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
    """Assemble a full module response from a resolution stub."""
    file_path = name_info["file"]
    module_full_name = name_info.get("full_name") or name_info.get("name")

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
        script = _make_script(analyzer, file_path)

        # Docstring (bucket 2 — semantic, bound to the symbol).
        # Use the cached AST and ast.get_docstring rather than the legacy
        # "first-statement-is-a-string" check.  ast.get_docstring already
        # implements PEP-257 correctly.
        try:
            tree = file_artifact_cache.get_ast(file_path)
            result["docstring"] = ast.get_docstring(tree)
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
                        "full_name": n.full_name,
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
                        "full_name": n.full_name,
                        "file": Path(n.module_path).as_posix() if n.module_path else file_path,
                        "line": n.line,
                    }
                )
        result["functions"] = _paginate(func_items, limit)

        # --- Variables (relationship list) ---
        # TODO(api-redesign): 2026-05-02 — _get_module_variables / _enrich_attribute
        # consume source for AST-based annotation extraction; classified bucket 4
        # (bridge read).  The analyzer-side helpers still take a source string; source
        # is read here as a bridge until the analyzer-side helpers are reshaped to take
        # a cached AST directly (out of scope for #316 Task 1.5).
        try:
            module_source = Path(file_path).read_text(encoding="utf-8")
            variables = await analyzer._get_module_variables(script, module_source)
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
                        "full_name": n.full_name,
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
    """Assemble a basic result for types that don't have a dedicated builder."""
    file_path = name_info.get("file")

    result: dict[str, Any] = {
        "type": name_info.get("type"),
        "name": name_info.get("name"),
        "full_name": name_info.get("full_name"),
        "file": file_path,
        "line": name_info.get("line"),
        "column": name_info.get("column"),
        "docstring": None,
        "module": _module_ref_for_file(analyzer, file_path) if file_path else None,
    }

    # Try to get docstring
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
