"""Signatures Jedi renders wrongly for a class, or for a value that isn't callable (#1126).

Leaf module: depends only on :mod:`ast` and :mod:`pyeye._ast_targets`, so the
signature builder in :mod:`pyeye.mcp.operations.inspect` can use it without an
import cycle.

- **None isn't callable.** Jedi renders the ``None`` instance as a callable,
  ``NoneType()``, so anything that can be ``None`` (``x: int | None``,
  ``Optional[X]``, ``= None``) got that signature. :func:`is_none_signature`
  marks it, so it's dropped. Only ``None`` is dropped: a variable that aliases a
  real callable (``alias = f``, ``kls = SomeClass``) keeps its signature.
- **A typed NamedTuple's constructor.** Jedi gives every class-form NamedTuple
  ``typing.NamedTuple``'s functional-form signature, ``(typename, fields, /)``.
  :func:`namedtuple_signature` renders the constructor the class's annotated
  fields generate instead, in order, with their defaults. A class that doesn't
  list ``NamedTuple`` as a base (a subclass of a NamedTuple class, whose fields
  are inherited) gets ``None``: no signature, never the factory's.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from pyeye._ast_targets import find_class_def_at_line, unsubscripted

#: The full name Jedi gives the ``None`` instance's (non-)signature.
_NONE_TYPE = "builtins.NoneType"
#: ``typing.NamedTuple``'s functional-form parameters, which Jedi shows for a typed NamedTuple.
_FACTORY_PARAMS = ("typename", "fields")
_NAMEDTUPLE = "NamedTuple"


def is_none_signature(signature: Any) -> bool:
    """Whether *signature* is the one Jedi renders for the ``None`` instance."""
    return getattr(signature, "full_name", None) == _NONE_TYPE


def is_namedtuple_factory(signature: Any) -> bool:
    """Whether *signature* is ``typing.NamedTuple``'s functional form, shown for a class."""
    try:
        params = signature.params
    except Exception:
        return False
    names = tuple(getattr(p, "name", None) for p in params[: len(_FACTORY_PARAMS)])
    return names == _FACTORY_PARAMS and all(
        getattr(p, "module_name", None) == "typing" for p in params
    )


def namedtuple_signature(jedi_name: Any) -> str | None:
    """The constructor a class-form NamedTuple's fields generate, e.g. ``P(x: int, y: int=0)``.

    ``None`` when the class can't be found in source, or doesn't list
    ``NamedTuple`` as a base itself (its fields are inherited, so they aren't
    in its body).
    """
    module_path = getattr(jedi_name, "module_path", None)
    line = getattr(jedi_name, "line", None)
    name = getattr(jedi_name, "name", None)
    if module_path is None or not line or not name:
        return None
    node = find_class_def_at_line(Path(module_path), line)
    if node is None or not any(_names_namedtuple(base) for base in node.bases):
        return None
    fields = [
        stmt
        for stmt in node.body
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
    ]
    arguments = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg=f.target.id, annotation=f.annotation) for f in fields],  # type: ignore[union-attr]
        vararg=None,
        kwonlyargs=[],
        kw_defaults=[],
        kwarg=None,
        defaults=[f.value for f in fields if f.value is not None],
    )
    try:
        return f"{name}({ast.unparse(arguments)})"
    except Exception:
        return None


def _names_namedtuple(base: ast.expr) -> bool:
    """``NamedTuple``, ``typing.NamedTuple`` or ``<alias>.NamedTuple``."""
    base = unsubscripted(base)
    if isinstance(base, ast.Name):
        return base.id == _NAMEDTUPLE
    return isinstance(base, ast.Attribute) and base.attr == _NAMEDTUPLE
