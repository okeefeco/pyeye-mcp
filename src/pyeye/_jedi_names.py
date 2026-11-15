"""Predicates over Jedi ``Name`` objects that ``full_name`` alone can't answer.

This module is underscore-private (internal use only).  Do NOT export from
``pyeye/__init__.py``.
"""

from __future__ import annotations

from typing import Any


def is_attribute_target(name: Any) -> bool:
    """Whether *name* is the target of an attribute assignment (#567).

    Jedi's ``get_names(definitions=True)`` reports the ``x`` of ``self.x = …``
    (or ``self.x: T = …``, ``self.a.x = …``, ``for self.x in …``) with the
    ``full_name`` of a local of the enclosing function, and the ``attr`` of a
    module-level ``obj.attr = …`` with the ``full_name`` of a module member.
    Neither is a binding in that scope: it sets an attribute on another object.
    In parso the target name then sits inside a ``trailer`` (the ``.x`` part of
    ``obj.x``), which a genuine binding never does.

    Objects without a parso tree (sentinels, or a ``Name`` Jedi built without
    one) are never attribute targets.
    """
    internal = getattr(name, "_name", None)
    tree_name = getattr(internal, "tree_name", None)
    parent = getattr(tree_name, "parent", None)
    return getattr(parent, "type", None) == "trailer"
