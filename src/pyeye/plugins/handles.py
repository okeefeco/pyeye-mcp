"""Canonical handles, scope and absolute locations for plugin results (#627).

Framework plugins find things by walking source ASTs, so their results say *where*
(``file``, ``line``) and *what it's called* (``name``), not *which symbol*. This
module adds, to every result record of every plugin tool:

``location``
    The primitives' :class:`~pyeye._jedi_location.Location` shape. For a placed
    symbol it is exactly what ``inspect(handle)`` reports: built from the
    resolver's anchor with :func:`~pyeye._jedi_location.location_from_name`
    (``file``, ``line_start``/``line_end`` spanning the definition,
    ``column_start``/``column_end`` spanning the name). Otherwise it is the
    ``total=False`` subset the record supports: ``{file, line_start, line_end}``
    (both the record's ``line``), or ``{file}`` for a record with no line. ``file``
    is the absolute posix path. The record's own ``file`` is left as it was,
    often relative.
``scope``
    ``"project"`` or ``"external"``.
``handle``
    Only for a record that names a symbol, and only from
    :func:`pyeye.resolver.resolve_handle`, the one canonical resolver. The path
    handed to it is the file's module name (:func:`pyeye.project_layout.
    module_name_for_file`) plus the definition's qualified name in that file
    (``Model.validator``), found in the cached AST at the record's line. Aliases,
    re-exports and canonical spelling are the resolver's job; this module never
    builds a handle itself.
``unresolved``
    ``{reason, detail}``, copied from the resolver's ``NotFound``, when a symbol
    record can't be placed (a route defined inside a factory function, a file
    outside every root). Such a record has **no** ``handle``.

A record with neither ``handle`` nor ``unresolved`` is not a symbol result (a
template file, a ``urls.py``, an ``app.config`` access): see :data:`SYMBOLS`.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pyeye import file_artifact_cache
from pyeye._jedi_location import location_from_name
from pyeye.path_utils import normalize_path
from pyeye.project_layout import module_name_for_file
from pyeye.resolver import NotFound, resolve_item
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Symbol:
    """How a tool's records name their symbol.

    Attributes:
        field: The record key holding the symbol's name.
        how: ``"at_line"`` — a def, class or assignment of that name starts at the
            record's ``line``. ``"enclosing_class"`` — the class of that name
            whose body contains ``line`` (``find_model_config`` reports the
            inner ``Config`` or ``model_config`` line). ``"module"`` — the field
            holds a dotted module name.
    """

    field: str
    how: Literal["at_line", "enclosing_class", "module"] = "at_line"


#: Each plugin tool whose records name a symbol. Every other tool's records get
#: ``location`` and ``scope`` only.
SYMBOLS: dict[str, Symbol] = {
    # Pydantic
    "find_pydantic_models": Symbol("name"),
    "get_model_schema": Symbol("model"),
    "find_validators": Symbol("name"),
    "find_field_validators": Symbol("name"),
    "find_model_config": Symbol("model", "enclosing_class"),
    "trace_model_inheritance": Symbol("model"),
    "find_computed_fields": Symbol("name"),
    # Django
    "find_django_models": Symbol("name"),
    "find_django_views": Symbol("name"),
    # Flask
    "find_flask_routes": Symbol("name"),
    "find_flask_blueprints": Symbol("name"),
    "find_flask_views": Symbol("name"),
    "find_flask_extensions": Symbol("extension", "module"),
    "find_error_handlers": Symbol("name"),
    "find_cli_commands": Symbol("function"),
}

#: ``trace_model_inheritance`` lists child models as ``{name, file, line}``.
_CHILD_SYMBOL = Symbol("name")


def enrich(tool_name: str, result: Any, analyzer_for: Callable[[], JediAnalyzer]) -> Any:
    """Add ``location``, ``scope`` and ``handle``/``unresolved`` to *result*'s records.

    Records are updated in place, and *result* is returned. Existing keys are
    never changed.

    Args:
        tool_name: The plugin tool's MCP name.
        result: What the tool returned.
        analyzer_for: Returns the analyzer for the plugin's project. Called at
            most once, and only if some record has a file to enrich, so an empty
            result never builds an analyzer.

    Returns:
        *result*, enriched.
    """
    cached: list[JediAnalyzer] = []

    def analyzer() -> JediAnalyzer:
        if not cached:
            cached.append(analyzer_for())
        return cached[0]

    symbol = SYMBOLS.get(tool_name)
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and _is_template_bundle(item):
                for record in (*item.get("templates", []), *item.get("render_calls", [])):
                    _enrich_record(record, None, analyzer)
            elif isinstance(item, dict):
                _enrich_record(item, symbol, analyzer)
    elif isinstance(result, dict):
        _enrich_record(result, symbol, analyzer)
        for child in result.get("children", []) or []:
            if isinstance(child, dict):
                _enrich_record(child, _CHILD_SYMBOL, analyzer)
    return result


def _is_template_bundle(item: dict[str, Any]) -> bool:
    return "templates" in item and "render_calls" in item


def _enrich_record(
    record: dict[str, Any], symbol: Symbol | None, analyzer_for: Callable[[], JediAnalyzer]
) -> None:
    raw_file = record.get("file")
    if not isinstance(raw_file, str):
        return
    analyzer = analyzer_for()
    path = normalize_path(raw_file)
    location: dict[str, Any] = {"file": path.as_posix()}
    line = record.get("line")
    if isinstance(line, int):
        location["line_start"] = line
        location["line_end"] = line
    record["location"] = location
    record["scope"] = classify_scope(path, analyzer)

    if symbol is None:
        return
    name = record.get(symbol.field)
    if not isinstance(name, str):
        return

    if symbol.how == "module":
        outcome = resolve_item(name, analyzer)  # per record (#704)
    else:
        outcome = _place(path, name, line, symbol, analyzer)
    if isinstance(outcome, NotFound):
        record["unresolved"] = {"reason": outcome.reason, "detail": outcome.detail}
    else:
        record["handle"] = outcome.handle
        record["scope"] = outcome.scope
        placed = _anchor_location(outcome.anchor)
        if placed is not None:
            record["location"] = placed


def _anchor_location(anchor: Any) -> dict[str, Any] | None:
    """The Location ``inspect`` reports for *anchor*, or ``None`` if it has no position.

    Mirrors ``inspect``'s own construction, so a plugin record's location and
    ``inspect(record["handle"])["location"]`` cannot drift apart (#627).
    """
    module_path = getattr(anchor, "module_path", None)
    if module_path is None or not isinstance(getattr(anchor, "line", None), int):
        return None
    return dict(location_from_name(Path(module_path).as_posix(), anchor))


def _place(path: Path, name: str, line: Any, symbol: Symbol, analyzer: JediAnalyzer) -> Any:
    """Resolve the definition named *name* at *line* of *path*, through the resolver."""
    if not isinstance(line, int):
        return NotFound(reason="unresolved", detail=f"{name!r} has no line to place it by.")
    module = module_name_for_file(analyzer, path)
    if module is None:
        return NotFound(
            reason="unresolved",
            detail=f"{path.as_posix()} is outside every project root, so {name!r} has no module.",
        )
    try:
        tree = file_artifact_cache.get_ast(path)
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError, RecursionError) as e:
        return NotFound(reason="unresolved", detail=f"could not read {path.as_posix()}: {e}")
    qualname = _qualname(tree, name, line, symbol.how)
    if qualname is None:
        return NotFound(
            reason="unresolved",
            detail=(
                f"{name!r} at {path.as_posix()}:{line} is not a module- or class-level "
                "definition (for example, it is defined inside a function)."
            ),
        )
    return resolve_item(f"{module}.{qualname}", analyzer)  # per record (#704)


def _qualname(tree: ast.Module, name: str, line: int, how: str) -> str | None:
    """The dotted path of *name*'s definition inside its module, or ``None``.

    Only definitions reachable by attribute access count: module level, or nested
    in classes. Anything inside a function body has no dotted path.
    """

    def visit(body: list[ast.stmt], prefix: tuple[str, ...]) -> str | None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                if node.name == name and _matches(node, line, how):
                    return ".".join((*prefix, name))
                found = visit(node.body, (*prefix, node.name))
                if found is not None:
                    return found
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if how == "at_line" and node.name == name and node.lineno == line:
                    return ".".join((*prefix, name))
            elif how == "at_line" and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if node.lineno == line and any(
                    isinstance(t, ast.Name) and t.id == name for t in targets
                ):
                    return ".".join((*prefix, name))
        return None

    return visit(tree.body, ())


def _matches(node: ast.ClassDef, line: int, how: str) -> bool:
    if how == "enclosing_class":
        end = getattr(node, "end_lineno", None) or node.lineno
        return node.lineno <= line <= end
    return node.lineno == line
