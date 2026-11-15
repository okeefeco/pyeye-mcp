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

Any other Jedi type (for example ``path``) becomes :data:`FALLBACK_KIND`
instead of leaking out as an undocumented kind.

This module sits below ``pyeye.mcp`` in the layering (#623) and must never
import it: ``tests/test_import_layers_fitness.py`` enforces that.
"""

from __future__ import annotations

from typing import Any

#: The closed kind vocabulary (``docs/api-redesign.md``, the ``kind`` row).
KINDS: frozenset[str] = frozenset(
    {"class", "function", "method", "module", "variable", "attribute", "property"}
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
    return "method" if raw_kind == "function" and is_method(jedi_name) else raw_kind
