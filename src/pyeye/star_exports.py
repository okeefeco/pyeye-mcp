"""Which names a ``from module import *`` brings in, read statically (#1007, #1010).

The one place this rule lives, so every consumer reads a star import the same
way: ``resolve`` (#1007) uses it now, and the class graph's base resolution
and the re-export binding index can switch to it (#1010).

Python's rule: a module's ``__all__``, when it has one, else every name that
doesn't start with ``_``. Here ``__all__`` counts only when it can be read
without running the module: assignments (``=``, ``:``-annotated, ``+=``) of a
list or tuple of string literals at module scope. A ``__all__`` built any
other way can't be known statically, so the default rule applies to it.
"""

from __future__ import annotations

import ast


def static_all(tree: ast.Module) -> frozenset[str] | None:
    """The names *tree*'s module-scope ``__all__`` lists, or ``None`` if it has no static one.

    ``None`` both when there is no ``__all__`` and when one assignment to it
    isn't a literal list or tuple of strings: neither can be read without
    running the module. An empty literal ``__all__`` is ``frozenset()``.
    """
    names: set[str] = set()
    found = False
    for node in tree.body:
        value: ast.expr | None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        literal = _literal_names(value)
        if literal is None:
            return None  # a dynamic __all__: unknown without running the module
        names.update(literal)
        found = True
    return frozenset(names) if found else None


def star_exported(tree: ast.Module, name: str) -> bool:
    """Whether ``from <tree's module> import *`` binds *name*."""
    listed = static_all(tree)
    if listed is not None:
        return name in listed
    return not name.startswith("_")


def _literal_names(value: ast.expr | None) -> list[str] | None:
    """The strings of a literal list or tuple, or ``None`` for anything else."""
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    names = []
    for element in value.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        names.append(element.value)
    return names
