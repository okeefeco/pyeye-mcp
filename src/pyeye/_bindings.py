"""The names a scope binds, by the Python reference's "Naming and binding" (#1049).

The ONE count behind local-name uniqueness, shared by the resolver (#1022: a
name several definitions share in one function resolves to none of them) and
#1024's class-graph naming (a function-local class is named only when its name
is bound once), so the two can't disagree.

Jedi can't be the source: it lists a parameter with no ``full_name``, names an
import after its target (``os``, ``os.path``), leaves out match captures and
type parameters, and reports a lambda's or comprehension's names under the
enclosing function. This reads the AST instead.

Per the maintainer's ruling (via designer, 2026-11-21) a name is bound in a
scope by a formal parameter, an import (a dotted ``import a.b`` binds ``a``), a
``def`` or ``class``, an assignment, augmented or annotated target, a ``:=``
target (one in a comprehension binds in the enclosing scope), a ``for`` target,
an ``as`` name in ``with``, ``except`` or ``match``, a match capture, a ``type``
statement or one of the scope's own type parameters, and also by ``del``.

Not bindings of the scope: names inside a nested function, class, lambda or
comprehension (their own scopes), attribute and subscript targets, a star
import, and ``global``/``nonlocal``, which declare rather than bind.

This is a lower layer: it must not import ``pyeye.mcp``.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BindingSite:
    """Where a scope binds a name, and how: ``form`` is a word for a reader."""

    line: int
    column: int
    form: str


#: Records one binding: ``(name, node it is at, form)``.
_Add = Callable[[str, ast.AST, str], None]

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def binding_sites(scope: ast.AST) -> dict[str, list[BindingSite]]:
    """Every name *scope* binds, with its sites in source order.

    *scope* is a function, class or module node. Its own parameters and type
    parameters count; its body is walked without entering nested scopes.
    """
    sites: dict[str, list[BindingSite]] = {}

    def add(name: str, node: ast.AST, form: str) -> None:
        site = BindingSite(getattr(node, "lineno", 0), getattr(node, "col_offset", 0), form)
        sites.setdefault(name, []).append(site)

    if isinstance(scope, _FUNCTIONS):
        args = scope.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
            if arg is not None:
                add(arg.arg, arg, "parameter")
    for param in getattr(scope, "type_params", ()):  # PEP 695, Python 3.12+
        add(param.name, param, "type parameter")
    for statement in getattr(scope, "body", ()):
        _visit(statement, add)
    for name in sites:
        sites[name].sort(key=lambda s: (s.line, s.column))
    return sites


def _visit(node: ast.AST, add: _Add) -> None:
    """Record the bindings *node* makes in the current scope, not crossing into nested ones."""
    if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
        add(node.name, node, "class" if isinstance(node, ast.ClassDef) else "def")
        return  # its body is its own scope
    if isinstance(node, ast.Lambda):
        return
    if isinstance(node, _COMPREHENSIONS):
        # Its targets are its own; a := inside binds in this scope.
        for inner in ast.walk(node):
            if isinstance(inner, ast.NamedExpr) and isinstance(inner.target, ast.Name):
                add(inner.target.id, inner.target, "walrus")
        return
    form = _form(node)
    if form is not None:
        for name, at in form[1]:
            add(name, at, form[0])
    for child in ast.iter_child_nodes(node):
        _visit(child, add)


def _form(node: ast.AST) -> tuple[str, list[tuple[str, ast.AST]]] | None:
    """``(form, [(name, node), ...])`` for a node that binds names itself, else ``None``."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return "assignment", [(node.id, node)]
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Del):
        return "del", [(node.id, node)]
    if isinstance(node, ast.Import):
        return "import", [((a.asname or a.name.split(".")[0]), node) for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return "import", [((a.asname or a.name), node) for a in node.names if a.name != "*"]
    if isinstance(node, ast.ExceptHandler) and node.name:
        return "except as", [(node.name, node)]
    if isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
        return "match capture", [(node.name, node)]
    if isinstance(node, ast.MatchMapping) and node.rest:
        return "match capture", [(node.rest, node)]
    return None
