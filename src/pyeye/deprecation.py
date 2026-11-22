"""A definition's deprecation, from static evidence in its own AST (#1082).

Evidence, in a function's, method's or class's definition:

- ``unconditional`` via ``decorator``: a decorator that is one of
  :data:`DEPRECATION_DECORATORS` (``@deprecated``, PEP 702, or the
  ``Deprecated`` package's), under whatever name the module imports it;
- ``unconditional`` via ``warn``: ``warnings.warn(..., <category>)`` with a
  deprecation category, run on every call: a statement of the body (of
  ``__init__``, for a class), or nested only in ``with`` blocks or a ``try``
  body or ``finally``, which don't branch;
- ``conditional`` via ``warn``: such a warn under a branch (``if``, a loop,
  ``except``, a ``try``'s ``else``, ``match``). It does NOT say the symbol is
  deprecated: it usually deprecates one kind of input or one path.

The ceiling is static: a warn in a helper function, a category built at
runtime, a decorator under an unrecognised name, or an early ``return``
before a warn isn't seen. Nested ``def``/``class`` bodies belong to those
definitions, not this one.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from typing import Any

#: Decorators that mark a definition deprecated, by qualified name.
DEPRECATION_DECORATORS = frozenset(
    {
        "warnings.deprecated",  # PEP 702, Python 3.13
        "typing_extensions.deprecated",
        "deprecated.deprecated",  # the ``Deprecated`` package
        "deprecated.classic.deprecated",
        "deprecated.sphinx.deprecated",
    }
)

#: The function that emits a warning, by qualified name.
_WARN = "warnings.warn"

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_Definition = _FunctionNode | ast.ClassDef

#: Statements whose bodies run every time the statement does (no branch).
_STRAIGHT_THROUGH = (ast.With, ast.AsyncWith)
#: Nested scopes: their bodies are other definitions' code.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def dotted_name(node: ast.expr) -> str | None:
    """``a.b.c`` for a Name/Attribute chain, else ``None``."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def qualify(name: str, import_table: dict[str, str]) -> str:
    """*name* with its head replaced by what the module imported under it, if it did."""
    head, _, rest = name.partition(".")
    target = import_table.get(head)
    if target is None:
        return name
    return f"{target}.{rest}" if rest else target


def evidence(
    definition: _Definition,
    import_table: dict[str, str],
    is_deprecation_category: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Every piece of deprecation evidence in *definition*, in line order.

    Args:
        definition: A function's, method's or class's AST node.
        import_table: Its module's surface name -> qualified name table
            (``build_import_table``), so ``import warnings as w`` and
            ``from warnings import warn`` are recognised.
        is_deprecation_category: Whether a qualified (or module-local) name
            is a deprecation warning category.

    Returns:
        ``{"kind", "via", "line"}`` entries; ``[]`` when there are none.
    """
    found: list[dict[str, Any]] = []
    line = decorator_line(definition, import_table)
    if line is not None:
        found.append({"kind": "unconditional", "via": "decorator", "line": line})

    body = definition.body
    if isinstance(definition, ast.ClassDef):
        init = next(
            (s for s in body if isinstance(s, _FunctionNode) and s.name == "__init__"),
            None,
        )
        body = init.body if init is not None else []
    _scan(body, True, import_table, is_deprecation_category, found)
    return sorted(found, key=lambda entry: entry["line"])


def decorator_line(definition: _Definition, import_table: dict[str, str]) -> int | None:
    """The line of *definition*'s deprecation decorator, or ``None`` if it has none."""
    for decorator in definition.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = dotted_name(target)
        if name is not None and qualify(name, import_table) in DEPRECATION_DECORATORS:
            return decorator.lineno
    return None


def overload_evidence(
    overloads: list[ast.FunctionDef | ast.AsyncFunctionDef], import_table: dict[str, str]
) -> list[dict[str, Any]]:
    """A ``conditional`` decorator entry for each deprecated ``@overload`` (#1088 ruling).

    A ``@deprecated`` on one overload deprecates that call form, not the
    function, so it's conditional evidence, like a warn under a branch.
    """
    found = []
    for overload in overloads:
        line = decorator_line(overload, import_table)
        if line is not None:
            found.append({"kind": "conditional", "via": "decorator", "line": line})
    return found


def _scan(
    statements: list[ast.stmt],
    every_call: bool,
    import_table: dict[str, str],
    is_deprecation_category: Callable[[str], bool],
    found: list[dict[str, Any]],
) -> None:
    """Collect deprecation warns in *statements*; *every_call*: no branch encloses them."""
    for statement in statements:
        if isinstance(statement, _SCOPES):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            if _is_deprecation_warn(statement.value, import_table, is_deprecation_category):
                found.append(
                    {
                        "kind": "unconditional" if every_call else "conditional",
                        "via": "warn",
                        "line": statement.lineno,
                    }
                )
            continue

        def scan(block: list[Any], straight: bool) -> None:
            _scan(block, straight, import_table, is_deprecation_category, found)

        if isinstance(statement, _STRAIGHT_THROUGH):
            scan(statement.body, every_call)
        elif isinstance(statement, ast.Try | ast.TryStar):
            scan(statement.body, every_call)
            scan(statement.finalbody, every_call)
            for handler in statement.handlers:
                scan(handler.body, False)
            scan(statement.orelse, False)
        elif isinstance(statement, ast.Match):
            for case in statement.cases:
                scan(case.body, False)
        else:
            # if / for / while (and their else), or any other compound statement.
            for field in ("body", "orelse"):
                block = getattr(statement, field, None)
                if isinstance(block, list):
                    scan(block, False)


def _is_deprecation_warn(
    call: ast.Call,
    import_table: dict[str, str],
    is_deprecation_category: Callable[[str], bool],
) -> bool:
    """Whether *call* is ``warnings.warn(message, <deprecation category>, ...)``."""
    name = dotted_name(call.func)
    if name is None or qualify(name, import_table) != _WARN:
        return False
    category: ast.expr | None = call.args[1] if len(call.args) > 1 else None
    if category is None:
        category = next((kw.value for kw in call.keywords if kw.arg == "category"), None)
    if category is None:
        return False  # UserWarning by default: not a deprecation
    category_name = dotted_name(category)
    return category_name is not None and is_deprecation_category(
        qualify(category_name, import_table)
    )
