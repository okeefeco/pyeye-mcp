"""A function's ``@overload`` set, read from its module's AST (#1088).

The overloads of a function are the same-named ``def`` statements beside it,
in the same body (a module, a class, a function), decorated ``@overload``
(``typing.overload`` or ``typing_extensions.overload``, under whatever name
the module imports them). The implementation is the one same-named ``def``
without it. The resolver anchors on the implementation when there is one
(#1089), and ``inspect`` reports the overloads' signatures beside the
implementation's (the maintainer's ruling on #1088).
"""

from __future__ import annotations

import ast

from pyeye.deprecation import dotted_name, qualify

#: The ``@overload`` decorator, by qualified name.
OVERLOAD_DECORATORS = frozenset({"typing.overload", "typing_extensions.overload"})

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def is_overload(definition: _FunctionNode, import_table: dict[str, str]) -> bool:
    """Whether *definition* is decorated ``@overload``."""
    for decorator in definition.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = dotted_name(target)
        if name is not None and qualify(name, import_table) in OVERLOAD_DECORATORS:
            return True
    return False


def overload_set(
    tree: ast.Module, definition: _FunctionNode, import_table: dict[str, str]
) -> tuple[list[_FunctionNode], _FunctionNode | None]:
    """``(overloads, implementation)`` for *definition*'s name in its body.

    ``overloads`` are the same-named ``@overload`` defs in *definition*'s
    body, in source order (``[]`` when there are none). ``implementation`` is
    the single same-named def without ``@overload``, when there are overloads
    and exactly one such def; otherwise ``None`` (overload-only, or no
    overloads at all, or several plain defs such as an ``if``/``else`` pair at
    one level, which aren't an overload set).
    """
    siblings = [
        node
        for node in _body_of(tree, definition)
        if isinstance(node, _FunctionNode) and node.name == definition.name
    ]
    overloads = [node for node in siblings if is_overload(node, import_table)]
    plain = [node for node in siblings if node not in overloads]
    implementation = plain[0] if overloads and len(plain) == 1 else None
    return overloads, implementation


def _body_of(tree: ast.Module, definition: ast.stmt) -> list[ast.stmt]:
    """The statement list *definition* sits in directly (``[definition]`` if not found)."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and any(stmt is definition for stmt in block):
                return block
    return [definition]
