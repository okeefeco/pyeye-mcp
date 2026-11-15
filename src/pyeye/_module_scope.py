"""The one module-scope import walk (#360).

Leaf module: depends only on :mod:`ast`. It sits below both the analyzers
(``analyzers.base_resolution``) and the MCP operations (``mcp.operations.edges``)
so every caller shares one walk without a lower layer importing ``pyeye.mcp``
(#630).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator

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

    def _walk(nodes: Iterable[ast.AST]) -> Iterator[ast.Import | ast.ImportFrom]:
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield node
            elif include_guarded and not isinstance(node, SCOPE_BOUNDARY_NODES):
                yield from _walk(ast.iter_child_nodes(node))

    yield from _walk(tree.body)
