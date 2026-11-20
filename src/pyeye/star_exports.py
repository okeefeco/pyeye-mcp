"""Which names a ``from module import *`` brings in, read statically (#1007, #1010).

The one place this rule lives, so every consumer reads a star import the same
way: ``resolve`` (#1007), the class graph's base resolution and the re-export
binding index behind ``re_exports`` (#1010).

Python's rule: a module's ``__all__``, when it has one, else every name that
doesn't start with ``_``. Here ``__all__`` counts only when it can be read
without running the module: assignments (``=``, ``:``-annotated, ``+=``) of a
list or tuple of string literals at module scope. A ``__all__`` built any
other way can't be known statically, so the default rule applies to it.
"""

from __future__ import annotations

import ast
from collections.abc import Callable

from pyeye._module_scope import iter_module_scope_imports


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
    return star_exported_from(static_all(tree), name)


def star_exported_from(listed: frozenset[str] | None, name: str) -> bool:
    """:func:`star_exported` for a module whose :func:`static_all` is already *listed*."""
    if listed is not None:
        return name in listed
    return not name.startswith("_")


def build_star_sources(
    tree: ast.Module,
    module: str,
    resolve_relative: Callable[[str, str | None, int, bool], str | None],
    is_package: bool = False,
) -> list[str]:
    """Return the modules this module star-imports (``from X import *``), in source order.

    ``build_import_table`` deliberately skips star imports (the names they bring
    in can't be known from this module's AST alone). This records the star
    *source modules* instead, so re-export following can look a name up in the
    source. Only unguarded module-scope stars count, as for the import table
    (#630). Relative sources are made absolute via *resolve_relative*.

    Args:
        tree: Parsed module AST.
        module: Dotted name of this module (for relative-import resolution).
        resolve_relative: ``(module, imported_module_or_None, level, is_package)
            -> abs path``.
        is_package: ``True`` when *module* is a package ``__init__`` — required
            for correct relative resolution of nested-package re-exports (#426).

    Returns:
        Absolute dotted names of the star-imported source modules.
    """
    sources: list[str] = []
    for node in iter_module_scope_imports(tree, include_guarded=False):
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
            base = (
                resolve_relative(module, node.module, node.level, is_package)
                if node.level > 0
                else node.module
            )
            if base:
                sources.append(base)
    return sources


def bound_names(tree: ast.Module) -> set[str]:
    """The names *tree*'s module binds at module scope, other than through a star.

    Top-level ``class``/``def`` and assignment targets (unpacking included; a
    bare annotation binds nothing), and
    every module-scope import (guarded ones too: Python binds them). Without a
    static ``__all__``, these plus what the module's own stars bring in are the
    candidates :func:`star_exported_from` filters.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_target_names(target))
        elif isinstance(node, ast.AugAssign) or (
            isinstance(node, ast.AnnAssign) and node.value is not None
        ):
            names.update(_target_names(node.target))  # a bare ``x: int`` binds nothing
    for imp in iter_module_scope_imports(tree):
        for alias in imp.names:
            if alias.name == "*":
                continue
            if alias.asname:
                names.add(alias.asname)
            elif isinstance(imp, ast.Import):
                names.add(alias.name.split(".")[0])
            else:
                names.add(alias.name)
    return names


def _target_names(target: ast.expr) -> list[str]:
    """The names an assignment target binds (``a``, ``a, (b, *c)``); none for ``a.b``/``a[0]``."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return [name for element in target.elts for name in _target_names(element)]
    return []


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
