"""Where Jedi's parser lost a definition that Python's parser sees (#1074).

parso 0.8.7, Jedi's parser, doesn't know some syntax Python accepts. In a
definition's HEADER (PEP 646 ``*args: *Ts`` or ``Generic[*Ts]``, PEP 695
``[*Ts, **P]`` or ``type Pair[T] = ...``) it error-recovers by dropping the
``def`` or ``class`` and leaving its body's statements in the enclosing scope.
Jedi then reports the body's names (``loop``) as definitions of that scope, and
doesn't see the definition at all.

These helpers answer, from ``ast`` alone, the two questions a caller asks about
a file Jedi parsed with errors (``file_artifact_cache.has_syntax_errors``):

- is a name Jedi lists really bound in the scope Jedi puts it in
  (:func:`bound_in`, :func:`scope_path_at`)?
- does a dotted path name a binding that only ``ast`` sees
  (:func:`binding_line`)?

Bindings are counted by :func:`pyeye._bindings.binding_sites`, the one count
behind local-name uniqueness (#1049). This is a lower layer: it must not import
``jedi`` or ``pyeye.mcp``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from pyeye._bindings import binding_sites

#: Statements that open a scope of their own: a binding inside one is not the
#: enclosing scope's.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def bound_in(scope: ast.AST) -> frozenset[tuple[str, int]]:
    """``(name, line)`` for every binding *scope* makes, by the Python reference (#1049)."""
    return frozenset(
        (name, site.line) for name, sites in binding_sites(scope).items() for site in sites
    )


def own_scopes(scope: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """The functions and classes *scope* defines directly, guarded ones included.

    A definition under ``if``/``try``/``with``/``for`` is still the scope's own;
    one inside another function or class is not.
    """
    stack = list(reversed(getattr(scope, "body", [])))
    while stack:
        node = stack.pop()
        if isinstance(node, _SCOPES):
            yield node
            continue
        children = [child for child in ast.iter_child_nodes(node) if isinstance(child, ast.stmt)]
        stack.extend(reversed(children))
        for handler in getattr(node, "handlers", ()):  # try / except bodies
            stack.extend(reversed(handler.body))
        for case in getattr(node, "cases", ()):  # match / case bodies
            stack.extend(reversed(case.body))


def _contains(scope: ast.AST, line: int) -> bool:
    """Whether *line* is in *scope*'s body, not its header."""
    body = getattr(scope, "body", None)
    end = getattr(scope, "end_lineno", None)
    if not body or end is None:
        return False
    return bool(body[0].lineno <= line <= end)


def scope_path_at(tree: ast.Module, line: int) -> list[ast.AST]:
    """The scopes a binding at *line* is in, outermost first; ``[]`` at module level."""
    path: list[ast.AST] = []
    scope: ast.AST = tree
    while True:
        inner = next((s for s in own_scopes(scope) if _contains(s, line)), None)
        if inner is None:
            return path
        path.append(inner)
        scope = inner


def scope_named(tree: ast.AST, parts: list[str]) -> ast.AST | None:
    """The scope a qualname names, *parts* after the module (``["K", "m"]``), or ``None``.

    Each part must be a function or class the scope before it defines. A name
    defined twice in one scope names the first; the guards that use this only
    narrow Jedi's answers, never add one.
    """
    scope: ast.AST = tree
    for part in parts:
        found = next((s for s in own_scopes(scope) if s.name == part), None)
        if found is None:
            return None
        scope = found
    return scope


def binding_line(tree: ast.Module, parts: list[str]) -> int | None:
    """The line where ``ast`` binds a qualname (*parts* after the module), or ``None``.

    The last part may be any binding (a ``def``, a ``class``, an assignment, a
    ``type`` statement); the parts before it must be functions or classes.
    """
    if not parts:
        return None
    scope = scope_named(tree, parts[:-1])
    if scope is None:
        return None
    sites = binding_sites(scope).get(parts[-1])
    return sites[0].line if sites else None


#: The binding forms that make a definition (``_bindings`` names them): a
#: ``def``, a ``class``, and an assignment, annotated assignment or ``type``
#: statement target.
_DEFINITION_FORMS = {"def": "function", "class": "class", "assignment": "variable"}

#: Why an entry of ``unreadable_definitions`` is there: pyeye's parser (Jedi's
#: parso) doesn't support the syntax of its header (#1074). Python parses the
#: file, so the code isn't broken: this names pyeye's limit.
PARSER_UNSUPPORTED_SYNTAX = "parser_unsupported_syntax"


def unreadable_definitions(scope: ast.AST, seen: set[tuple[str, int]]) -> list[dict[str, object]]:
    """The definitions *scope* makes that Jedi didn't list, sorted by line (#1074).

    *seen* is ``(name, line)`` for each name Jedi lists in that scope. Each
    entry is ``{name, kind, line, reason}``: ``kind`` is ``function`` (``method``
    in a class), ``class`` or ``variable``, and ``reason`` is
    :data:`PARSER_UNSUPPORTED_SYNTAX`.
    """
    entries: dict[tuple[str, int], dict[str, object]] = {}
    for name, sites in binding_sites(scope).items():
        for site in sites:
            kind = _DEFINITION_FORMS.get(site.form)
            if kind is None or (name, site.line) in seen:
                continue
            if kind == "function" and isinstance(scope, ast.ClassDef):
                kind = "method"
            entries.setdefault(
                (name, site.line),
                {
                    "name": name,
                    "kind": kind,
                    "line": site.line,
                    "reason": PARSER_UNSUPPORTED_SYNTAX,
                },
            )
    return [entries[key] for key in sorted(entries, key=lambda k: (k[1], k[0]))]
