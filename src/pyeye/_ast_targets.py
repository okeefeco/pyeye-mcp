"""Pure-AST helpers for locating goto targets in cached source ASTs.

Leaf module: depends only on :mod:`ast` and :mod:`pyeye.file_artifact_cache`.
It exists so both ``inspect`` and ``edges`` can share the exact same target
positioning / def-locating logic WITHOUT importing each other (``edges`` must
not import ``inspect`` — that would be a circular import once ``inspect`` imports
``edges`` for ``edge_counts.members``).

Two helpers:

- :func:`find_function_def_at_line` — locate the ``FunctionDef`` /
  ``AsyncFunctionDef`` node whose ``lineno`` matches a given line, using the
  mtime-keyed cached AST.
- :func:`attr_target_position` — compute the ``(line, col)`` of the *rightmost*
  identifier in a ``Name`` / ``Attribute`` expression, so a per-call-site
  ``Script.goto`` lands on the actual symbol (the method / class) rather than its
  receiver (the package / module / object).
"""

from __future__ import annotations

import ast
from pathlib import Path

from pyeye import file_artifact_cache


def find_function_def_at_line(
    file_path: Path, line: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return the FunctionDef / AsyncFunctionDef whose ``lineno`` equals *line*.

    Uses the cached file AST. Returns ``None`` when no match is found or any
    error occurs (file missing, parse error, etc.).

    Args:
        file_path: Path to the source file.
        line: 1-indexed line number of the function definition.

    Returns:
        The matching def node, or ``None``.
    """
    try:
        tree = file_artifact_cache.get_ast(file_path)
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == line:
            return node
    return None


def attr_target_position(node: ast.expr) -> tuple[int, int]:
    """Return (line, col) of the rightmost identifier in a Name/Attribute expr.

    For ``ast.Name`` (e.g. ``Widget``): the position of the name itself.
    For ``ast.Attribute`` (e.g. ``pkg.sub.Widget``): the position of the
    rightmost attribute name (``Widget``), not the leftmost receiver (``pkg``).

    Using the rightmost position ensures ``jedi.Script.goto()`` resolves the
    actual class / method, not the package / module / object acting as receiver.

    Args:
        node: AST node representing the expression (typically a base class or a
            call target).

    Returns:
        ``(line, col)`` tuple suitable for passing to ``jedi.Script.goto()``.
    """
    if isinstance(node, ast.Attribute):
        # ast.Attribute stores end_lineno/end_col_offset for the entire chain.
        # The rightmost attr name ends there and starts len(attr) chars before.
        end_line = node.end_lineno or node.lineno
        end_col = node.end_col_offset or 0
        return end_line, max(0, end_col - len(node.attr))
    # ast.Name or any other node type — use the node's own start position.
    return node.lineno, node.col_offset
