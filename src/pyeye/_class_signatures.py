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
- **A TypedDict's constructor (#1129).** Jedi gives a TypedDict class ``dict``'s
  overloads, renamed, so its first signature was ``Movie()``.
  :func:`typeddict_signature` renders the keyword-only constructor its keys
  imply, ``Movie(*, title: str, year: int=...)``: an optional key (``total=False``
  or ``NotRequired``) is marked ``...``, since it has no real default;
  ``Required`` / ``NotRequired`` override the totality per key; ``ReadOnly``
  doesn't appear. Inherited keys come first, from each base in order, but only
  when every base resolves statically to one TypedDict class; otherwise there is
  no signature, never a partial one. The functional form
  (``TypedDict("M", {...})``) is a variable Jedi gives no signature.
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
#: Key qualifiers (PEP 655, PEP 705), stripped from the shown type.
_REQUIRED, _NOT_REQUIRED, _READ_ONLY = "Required", "NotRequired", "ReadOnly"
_QUALIFIERS = frozenset({_REQUIRED, _NOT_REQUIRED, _READ_ONLY})
_TYPEDDICT = "TypedDict"
_TYPING_MODULES = frozenset({"typing", "typing_extensions"})


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


def typeddict_class(jedi_name: Any) -> Any | None:
    """The class value *jedi_name* infers to, if it's a TypedDict class; else None."""
    if getattr(jedi_name, "type", None) != "class":
        return None
    try:
        inferred = jedi_name.infer()
    except Exception:
        return None
    if len(inferred) != 1:
        return None
    value = getattr(getattr(inferred[0], "_name", None), "_value", None)
    return value if _is_typeddict_class(value) else None


def typeddict_signature(value: Any, name: str) -> str | None:
    """The keyword-only constructor a TypedDict class's keys imply (#1129).

    *value* is from :func:`typeddict_class`. ``None`` (no signature, never a
    partial one) when its keys can't all be known: a base or a ``total=`` that
    doesn't resolve statically, or a class not found in source.
    """
    keys = _keys(value, depth=0)
    if keys is None:
        return None
    kwonly = [ast.arg(arg=key, annotation=annotation) for key, (annotation, _) in keys.items()]
    defaults: list[ast.expr | None] = [
        None if required else ast.Constant(value=Ellipsis) for _, required in keys.values()
    ]
    arguments = ast.arguments(
        posonlyargs=[],
        args=[],
        vararg=None,
        kwonlyargs=kwonly,
        kw_defaults=defaults,
        kwarg=None,
        defaults=[],
    )
    try:
        return f"{name}({ast.unparse(arguments)})"
    except Exception:
        return None


#: Deeper than any real TypedDict hierarchy: a cycle Jedi reports is cut here.
_MAX_DEPTH = 32


def _is_typeddict_class(value: Any) -> bool:
    try:
        return bool(value.is_typeddict()) and not _is_root(value)
    except Exception:
        return False


def _is_root(value: Any) -> bool:
    """``typing.TypedDict`` (or ``typing_extensions``'s) itself: the base with no keys."""
    if type(value).__name__ == "TypedDictClass":
        return True
    try:
        name = value.name.string_name
        module = value.get_root_context().py__name__()
    except Exception:
        return False
    return name == _TYPEDDICT and module in _TYPING_MODULES


def _keys(value: Any, depth: int) -> dict[str, tuple[ast.expr, bool]] | None:
    """Key -> (shown annotation, required), inherited first; None if any is unknown."""
    if depth > _MAX_DEPTH:
        return None
    node = _class_def(value)
    if node is None:
        return None
    total = _totality(node)
    if total is None:
        return None
    keys: dict[str, tuple[ast.expr, bool]] = {}
    try:
        bases = list(value.py__bases__())
    except Exception:
        return None
    for lazy in bases:
        try:
            candidates = list(lazy.infer())
        except Exception:
            return None
        if len(candidates) != 1:
            return None  # a base that doesn't resolve to exactly one class
        base = candidates[0]
        if _is_root(base):
            continue
        if not _is_typeddict_class(base):
            return None
        inherited = _keys(base, depth + 1)
        if inherited is None:
            return None
        keys.update(inherited)
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            keys[stmt.target.id] = _qualified(stmt.annotation, total)
    return keys


def _class_def(value: Any) -> ast.ClassDef | None:
    try:
        path = value.get_root_context().py__file__()
        line = value.tree_node.start_pos[0]
    except Exception:
        return None
    if path is None:
        return None
    return find_class_def_at_line(Path(path), line)


def _totality(node: ast.ClassDef) -> bool | None:
    """The class's ``total=``: True by default, None when it isn't a literal bool."""
    for keyword in node.keywords:
        if keyword.arg == "total":
            literal = keyword.value
            if isinstance(literal, ast.Constant) and isinstance(literal.value, bool):
                return literal.value
            return None
    return True


def _qualified(annotation: ast.expr, total: bool) -> tuple[ast.expr, bool]:
    """The annotation without its key qualifiers, and whether the key is required."""
    required = total
    while isinstance(annotation, ast.Subscript) and _qualifier(annotation.value) in _QUALIFIERS:
        qualifier = _qualifier(annotation.value)
        if qualifier == _REQUIRED:
            required = True
        elif qualifier == _NOT_REQUIRED:
            required = False
        annotation = annotation.slice
    return annotation, required


def _qualifier(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None
