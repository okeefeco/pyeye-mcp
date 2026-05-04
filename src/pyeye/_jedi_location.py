"""Internal helpers for deriving Location spans from Jedi Name objects.

Used by resolve and inspect to produce consistent location pointers.

This module is underscore-private (internal use only).  Do NOT export from
``pyeye/__init__.py``.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Location(TypedDict, total=False):
    """Pointer to a source range (NOT source content).

    line_start/line_end span the full definition block (class body for classes,
    function body for functions; equal to line_start for other kinds).
    column_start/column_end span the name identifier itself.
    """

    file: str
    line_start: int
    line_end: int
    column_start: int
    column_end: int


_DEFINITION_TYPES: frozenset[str] = frozenset(
    ("funcdef", "classdef", "async_funcdef", "async_stmt", "decorated")
)


def get_end_line(jedi_name: Any) -> int:
    """Walk a Jedi Name's tree to find the end line of the enclosing definition.

    Returns the start line if no enclosing classdef/funcdef is found
    (correct for variables/attributes/modules — they "end" where they start).

    Args:
        jedi_name: A Jedi ``Name`` object.

    Returns:
        The 1-indexed end line number.
    """
    start_line: int = jedi_name.line or 1
    try:
        internal = getattr(jedi_name, "_name", None)
        if internal is None:
            return start_line
        tree_name = getattr(internal, "tree_name", None)
        if tree_name is None:
            return start_line
        node = tree_name.parent
        while node is not None:
            if getattr(node, "type", None) in _DEFINITION_TYPES:
                end_pos = getattr(node, "end_pos", None)
                if end_pos is not None:
                    return int(end_pos[0])
                break
            node = getattr(node, "parent", None)
    except Exception:
        pass
    return start_line


def location_from_name(file_str: str, jedi_name: Any) -> Location:
    """Build a span Location from a Jedi Name.

    Spans:
    - column_start..column_end = the NAME identifier (name[column] to
      name[column + len(name)])
    - line_start..line_end = full definition block (class/function body), or
      single-line for kinds without an enclosing block.

    Args:
        file_str: POSIX file path string.
        jedi_name: A Jedi ``Name`` object.

    Returns:
        A :class:`Location` dict.
    """
    line_start: int = jedi_name.line or 1
    column_start: int = jedi_name.column or 0
    name_str: str = getattr(jedi_name, "name", "") or ""
    return Location(
        file=file_str,
        line_start=line_start,
        line_end=get_end_line(jedi_name),
        column_start=column_start,
        column_end=column_start + len(name_str),
    )
