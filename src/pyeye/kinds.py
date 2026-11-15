"""The closed ``kind`` vocabulary every pyeye primitive reports (#623).

Every handle-bearing answer (``resolve``, ``resolve_at``, ``inspect`` and the
stubs in ``outline`` / ``expand`` / ``trace``) carries a ``kind`` drawn from
:data:`KINDS`, the set documented in ``docs/api-redesign.md``.

Jedi's ``Name.type`` maps onto it as follows:

    class      → "class"
    function   → "function"  (→ "method" when enclosed by a class)
    module     → "module"
    namespace  → "module"    (a PEP 420 namespace package is still a module)
    import     → "module"
    statement  → "variable"
    instance   → "variable"
    param      → "variable"
    keyword    → "variable"  (rare; included for completeness)
    property   → "property"

A ``statement`` bound directly in a class body is then refined (#695):
``attribute``, or ``enum_member`` when the class is a transitive
``enum.Enum`` subclass and the binding really is a member
(:func:`class_body_kind`).

Any other Jedi type (for example ``path``) becomes :data:`FALLBACK_KIND`
instead of leaking out as an undocumented kind.

This module sits below ``pyeye.mcp`` in the layering (#623) and must never
import it: ``tests/test_import_layers_fitness.py`` enforces that.
"""

from __future__ import annotations

from typing import Any

#: The closed kind vocabulary (``docs/api-redesign.md``, the ``kind`` row).
KINDS: frozenset[str] = frozenset(
    {
        "class",
        "function",
        "method",
        "module",
        "variable",
        "attribute",
        "property",
        "enum_member",  # #695
    }
)

#: The kind given to a missing or unrecognised Jedi type.
FALLBACK_KIND = "variable"

#: Jedi ``Name.type`` → API kind.
JEDI_TYPE_TO_KIND: dict[str, str] = {
    "class": "class",
    "function": "function",
    "module": "module",
    "namespace": "module",
    "import": "module",
    "instance": "variable",
    "statement": "variable",
    "param": "variable",
    "keyword": "variable",
    "property": "property",
}


def normalise_kind(jedi_type: str | None) -> str:
    """Map Jedi's ``Name.type`` to a kind in :data:`KINDS`.

    ``None`` and unrecognised types become :data:`FALLBACK_KIND`; nothing outside
    the vocabulary is ever returned.
    """
    if jedi_type is None:
        return FALLBACK_KIND
    return JEDI_TYPE_TO_KIND.get(jedi_type, FALLBACK_KIND)


def is_method(jedi_name: Any) -> bool:
    """Return True if *jedi_name* is a method (a function enclosed by a class).

    Reads the resolved Jedi ``Name``'s parent scope directly via
    ``Name.parent()`` instead of re-deriving the enclosing scope from the dotted
    handle. Dotted-name string arithmetic plus a filesystem module lookup
    cannot see class nesting: for ``module.Outer.Inner.method`` it treats
    ``Outer`` as a module, fails to find it, and misclassifies the nested-class
    method as a plain function (issue #337).

    Args:
        jedi_name: The resolved Jedi ``Name`` object for the symbol.

    Returns:
        ``True`` when the symbol is a function whose immediate enclosing scope
        is a class (at any nesting depth).
    """
    if getattr(jedi_name, "type", None) != "function":
        return False
    try:
        parent = jedi_name.parent()
    except Exception:
        return False
    return parent is not None and getattr(parent, "type", None) == "class"


def normalise_kind_from_name(jedi_name: Any) -> str:
    """Normalise a Jedi ``Name`` to its API kind, promoting methods.

    The single source of truth for kind normalisation across ``resolve``,
    ``inspect``, the stub builder and the edges: maps ``Name.type`` via
    :func:`normalise_kind`, then promotes a class-enclosed function from
    ``"function"`` to ``"method"`` via :func:`is_method` (#406).

    Args:
        jedi_name: The resolved Jedi ``Name`` object for the symbol.

    Returns:
        A kind in :data:`KINDS`.
    """
    raw_kind = normalise_kind(getattr(jedi_name, "type", None))
    if raw_kind == "function" and is_method(jedi_name):
        return "method"
    if raw_kind == "variable":
        return class_body_kind(jedi_name) or raw_kind
    return raw_kind


#: Calls whose result is never an enum member (a descriptor or an explicit opt-out).
_NON_MEMBER_CALLS = frozenset({"nonmember", "property", "staticmethod", "classmethod"})
#: Inferred value types that make a class-body binding a non-member.
_NON_MEMBER_TYPES = frozenset({"function", "class", "property"})


def class_body_kind(jedi_name: Any) -> str | None:
    """Kind of a ``statement`` bound directly in a class body, or ``None`` (#695).

    ``attribute`` for any class-body binding; ``enum_member`` only when the
    class is a transitive ``enum.Enum`` subclass (its own MRO, inferred by
    Jedi: no project-wide scan) AND the binding is a member by Python's rules.
    Anything that can't be decided statically is ``attribute``, never
    ``enum_member``: less specific, never wrong.  ``None`` when *jedi_name* is
    not a class-body statement (module- and function-level names stay
    ``variable``).
    """
    if getattr(jedi_name, "type", None) != "statement":
        return None
    try:
        parent = jedi_name.parent()
    except Exception:
        return None
    if parent is None or getattr(parent, "type", None) != "class":
        return None
    try:
        member = _is_enum_class(parent) and _is_enum_member(jedi_name)
    except Exception:  # never claim membership on an inference failure
        member = False
    return "enum_member" if member else "attribute"


def _is_enum_class(class_name: Any) -> bool:
    """Whether the class's own MRO, as Jedi infers it, reaches ``enum.Enum``.

    An unresolvable base truncates Jedi's MRO, so it never reaches ``Enum``.
    """
    for value in class_name._name.infer():
        for cls in value.py__mro__():
            if cls.py__name__() == "Enum" and cls.get_root_context().py__name__() == "enum":
                return True
    return False


def _is_enum_member(jedi_name: Any) -> bool:
    """Python's enum membership rules, decided statically from the class body."""
    name = jedi_name.name
    if name.startswith("_") and name.endswith("_"):
        return False  # _sunder_ and __dunder__ names are never members
    tree_name = jedi_name._name.tree_name
    classdef = tree_name.search_ancestor("classdef")
    ignored = _ignored_names(classdef)
    if ignored is None or name in ignored:
        return False  # listed in _ignore_, or _ignore_ can't be read statically
    value = _assigned_value(tree_name)
    if value is None:
        return False  # an annotation alone creates no member
    if value.type == "lambdef":
        return False
    call = _call_name(value)
    if call == "member":
        return True
    if call in _NON_MEMBER_CALLS:
        return False
    inferred = jedi_name.infer()
    if not inferred:
        return False  # unknown value: can't tell
    return not any(getattr(v, "type", None) in _NON_MEMBER_TYPES for v in inferred)


def _assigned_value(tree_name: Any) -> Any | None:
    """The value node assigned to *tree_name* (``x = v`` / ``x: T = v``), or ``None``."""
    stmt = tree_name.get_definition()
    if stmt is None or stmt.type != "expr_stmt":
        return None
    children = stmt.children
    if len(children) >= 3 and getattr(children[1], "value", None) == "=":
        return children[-1]
    if len(children) == 2 and children[1].type == "annassign":
        ann = children[1].children
        return ann[3] if len(ann) >= 4 else None
    return None


def _call_name(value: Any) -> str | None:
    """The last dotted part of the callee when *value* is a call, e.g. ``nonmember``."""
    if value.type not in ("power", "atom_expr"):
        return None
    children = value.children
    last = children[-1]
    if last.type != "trailer" or getattr(last.children[0], "value", None) != "(":
        return None
    callee = children[-2]
    if callee.type == "trailer":  # enum.nonmember(...)
        return getattr(callee.children[-1], "value", None)
    return getattr(callee, "value", None)


def _ignored_names(classdef: Any) -> frozenset[str] | None:
    """Names listed in the class's ``_ignore_``; ``None`` if it isn't a literal.

    ``_ignore_`` may be a space-separated string or a list/tuple of strings.
    """
    import ast as _ast

    suite = classdef.children[-1]
    for stmt in getattr(suite, "children", ()):
        expr = stmt.children[0] if stmt.type == "simple_stmt" else stmt
        if expr.type != "expr_stmt" or getattr(expr.children[0], "value", None) != "_ignore_":
            continue
        if len(expr.children) < 3:
            return None
        try:
            literal = _ast.literal_eval(expr.children[-1].get_code())
        except (ValueError, SyntaxError):
            return None
        if isinstance(literal, str):
            return frozenset(literal.split())
        if isinstance(literal, (list, tuple)) and all(isinstance(x, str) for x in literal):
            return frozenset(literal)
        return None
    return frozenset()
