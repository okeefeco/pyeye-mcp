"""The one module-scope import walk (#360).

Leaf module: depends only on :mod:`ast`. It holds the module-scope import walk and
the import table built on it (moved here in #712). It sits below both the analyzers
(``analyzers.base_resolution``) and the MCP operations (``mcp.operations.edges``)
so every caller shares one walk without a lower layer importing ``pyeye.mcp``
(#630).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Iterator

#: AST nodes that open a NEW binding scope.  An ``import`` inside one of these
#: binds a local variable or a class attribute — NOT a module-scope name — so the
#: walk below must never descend into them.
SCOPE_BOUNDARY_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def iter_module_scope_imports(
    tree: ast.Module, *, include_guarded: bool = True
) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield every import statement that binds a MODULE-scope name, in source order.

    "Module scope" is a BINDING question, not a nesting question: an import
    nested in top-level control flow still binds its name in the module
    namespace.  So this walk descends through every statement-bearing construct
    (``if``/``elif``/``else``, ``try``/``except``/``else``/``finally``, ``with``,
    ``for``, ``while``, ``match``) and stops only at :data:`SCOPE_BOUNDARY_NODES`
    — the constructs that open a new namespace.

    Guard forms are therefore handled UNIFORMLY rather than case by case; the
    common ones this reaches are ``if TYPE_CHECKING:`` type-only imports, the
    ``try``/``except ImportError`` optional-dependency shim, and
    ``sys.version_info`` branches.  Both branches of a shim are yielded: each is
    a statically-present dependency, and which one runs is a runtime fact.

    Callers share this walk so they cannot drift apart (#360): ``members``
    SUBTRACTS these names, ``imports`` EMITS them, which is what keeps the two
    edges disjoint yet jointly complete over a module's bound names.

    Args:
        tree: Parsed module AST.
        include_guarded: ``False`` yields only the UNGUARDED imports, the
            statements directly in ``tree.body``. Use it when a caller commits
            to *which* object a name is bound to, not just *that* it is bound:
            under a guard the binding may never run, and in a shim either branch
            may win. ``analyzers.base_resolution`` needs this so it returns
            ``None`` (ask Jedi) instead of a possibly wrong definition.

    Yields:
        Each :class:`ast.Import` / :class:`ast.ImportFrom` node at module scope,
        in source order.
    """
    for node, _type_only in iter_module_scope_imports_guarded(
        tree, include_guarded=include_guarded
    ):
        yield node


#: Modules whose ``TYPE_CHECKING`` constant is the type-checking guard (#1081).
_TYPING_MODULES = ("typing", "typing_extensions")


def iter_module_scope_imports_guarded(
    tree: ast.Module, *, include_guarded: bool = True
) -> Iterator[tuple[ast.Import | ast.ImportFrom, bool]]:
    """THE module-scope import walk (#360), each import with whether it is type-only (#1081).

    :func:`iter_module_scope_imports` is this walk without the flag, so
    ``members`` and ``imports`` still share one walk; *include_guarded* is as
    documented there. An
    import is type-only when it sits in the BODY of an ``if`` whose test is the
    ``TYPE_CHECKING`` guard, at any depth below it (a nested ``if``, a ``try``).
    The ``else``/``elif`` branch runs at runtime; ``if not TYPE_CHECKING:``
    reverses the two. The guard is recognised as the bare name
    ``TYPE_CHECKING``, any alias of it imported from ``typing`` or
    ``typing_extensions`` (``from typing import TYPE_CHECKING as TC``), and
    ``<module>.TYPE_CHECKING`` for any name those modules are imported as
    (``import typing as t``). Not recognised: a module that defines its own
    ``TYPE_CHECKING = False``.

    Yields:
        ``(import node, type_only)`` in source order.
    """
    names, modules = _type_checking_spellings(tree)

    def guard(test: ast.expr) -> bool | None:
        """``True`` for the guard, ``False`` for ``not`` the guard, else ``None``."""
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            inner = guard(test.operand)
            return None if inner is None else not inner
        if isinstance(test, ast.Name) and test.id in names:
            return True
        if (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in modules
        ):
            return True
        return None

    def walk(
        nodes: Iterable[ast.AST], type_only: bool
    ) -> Iterator[tuple[ast.Import | ast.ImportFrom, bool]]:
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node, type_only
            elif isinstance(node, ast.If) and (kind := guard(node.test)) is not None:
                yield from walk(node.body, type_only or kind)
                yield from walk(node.orelse, type_only or not kind)
            elif not isinstance(node, SCOPE_BOUNDARY_NODES):
                yield from walk(ast.iter_child_nodes(node), type_only)

    if not include_guarded:  # only the statements directly in the module body
        yield from ((n, False) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))
        return
    yield from walk(tree.body, False)


def _type_checking_spellings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The names bound to ``TYPE_CHECKING``, and to a typing module, by *tree*'s imports."""
    names: set[str] = {"TYPE_CHECKING"}
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _TYPING_MODULES:
            names.update(a.asname or a.name for a in node.names if a.name == "TYPE_CHECKING")
        elif isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name in _TYPING_MODULES)
    return names, modules


def build_import_table(
    tree: ast.Module,
    module: str,
    resolve_relative: Callable[[str, str | None, int, bool], str | None],
    is_package: bool = False,
) -> dict[str, str]:
    """Build the surface-name → target-path table for one module's AST.

    Only **unguarded top-level** imports are considered (the scope a class base
    resolves in), via the shared walk with ``include_guarded=False`` (#360,
    #630): an import under ``if TYPE_CHECKING:`` or in a try/except shim may not
    be the binding that runs, so the resolver punts to Jedi for it. ``as``-aliases are captured under the alias; ``import a.b.c`` binds the
    head ``a``; relative imports are made absolute via *resolve_relative*; star
    imports are skipped (their names can't be resolved statically — the resolver
    will punt to Jedi for bases that rely on them).

    Args:
        tree: Parsed module AST.
        module: Dotted name of this module (for relative-import resolution).
        resolve_relative: ``(module, imported_module_or_None, level, is_package)
            -> abs path`` — typically ``import_analyzer.resolve_relative_import``.
        is_package: ``True`` when *module* is a package ``__init__`` — required
            for correct relative resolution of nested-package re-exports (#426).

    Returns:
        ``{surface name: target dotted path}``.
    """
    table: dict[str, str] = {}
    # Unguarded imports only: a guarded binding can't be committed to (#630).
    for node in iter_module_scope_imports(tree, include_guarded=False):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    table[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    table[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = (
                resolve_relative(module, node.module, node.level, is_package)
                if node.level > 0
                else node.module
            )
            for alias in node.names:
                if alias.name == "*":
                    continue
                surface = alias.asname or alias.name
                table[surface] = f"{base}.{alias.name}" if base else alias.name
    return table
