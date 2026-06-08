"""build_stub — construct a spec §4.1 Stub from a Jedi Name object.

A Stub is the lightweight pointer returned by every traversal primitive
(members, callees, expand).  It carries just enough to identify and locate
a symbol without any source content.

Spec §4.1 Stub shape
---------------------
::

    {
      "handle":     str,               # canonical definition-site handle
      "kind":       str,               # class|function|method|module|attribute|
                                       # property|variable
      "scope":      "project"|"external",
      "signature":  str,               # PRESENT for callable kinds only
                                       # (class/function/method)
      "line_start": int,
      "line_end":   int,
    }

Design notes
------------
- ``signature`` is ABSENT (key omitted, NOT an empty string) for non-callable
  kinds (module, attribute, property, variable).
- ``line_start`` / ``line_end`` are the flattened span: the full definition
  block for classes and functions, otherwise equal (single-line for variables,
  attributes, properties).
- No source content anywhere — no ``body``, ``source``, ``code``, ``snippet``,
  or ``text`` fields.
- ``build_stub`` is a **pure synchronous** function.  It does not call
  ``get_references``.

Reuse policy (#330)
-------------------
All helpers come from existing modules — no second implementation:

- Kind normalisation: ``pyeye.mcp.operations.resolve._normalise_kind``
- Method detection:   ``pyeye.mcp.operations.inspect._is_method``
- Signature:          ``pyeye.mcp.operations.inspect._build_signature``
- Scope:              ``pyeye.scope.classify_scope``
- Span:               ``pyeye._jedi_location.get_end_line``

Public API
----------
.. code-block:: python

    from pyeye.mcp.operations.stubs import build_stub

    stub = build_stub(jedi_name, "mypackage._core.widgets.Widget", analyzer)
    # → {handle, kind, scope, signature, line_start, line_end}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyeye._jedi_location import get_end_line
from pyeye.mcp.operations.inspect import _build_signature, _is_method
from pyeye.mcp.operations.resolve import _normalise_kind
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer

# ---------------------------------------------------------------------------
# Callable kinds that carry a ``signature`` field
# ---------------------------------------------------------------------------

_CALLABLE_KINDS: frozenset[str] = frozenset({"class", "function", "method"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_stub(jedi_name: Any, handle: str, analyzer: JediAnalyzer) -> dict[str, Any]:
    """Build a spec §4.1 Stub from a Jedi Name and a pre-computed canonical handle.

    The caller is responsible for canonicalising the handle (Phase-2 resolvers
    or Phase-4 expand supply it).  ``build_stub`` does NOT canonicalize.

    Args:
        jedi_name: A Jedi ``Name`` object (or ``_ModuleSentinel``-compatible
            object) for the symbol.
        handle: The already-canonical dotted-name handle for the symbol.
        analyzer: Active analyzer for scope classification.

    Returns:
        A Stub dict conforming to spec §4.1.
    """
    # ------------------------------------------------------------------
    # 1. Kind — normalise then promote function → method when applicable
    # ------------------------------------------------------------------
    raw_kind = _normalise_kind(getattr(jedi_name, "type", None))
    kind = "method" if raw_kind == "function" and _is_method(jedi_name) else raw_kind

    # ------------------------------------------------------------------
    # 2. Scope — pure path comparison via classify_scope
    # ------------------------------------------------------------------
    module_path = getattr(jedi_name, "module_path", None)
    if module_path is not None:
        file_str = module_path.as_posix()
        scope = classify_scope(file_str, analyzer)
    else:
        # No file (built-ins, dynamic objects) → external by default
        scope = "external"
        file_str = ""

    # ------------------------------------------------------------------
    # 3. Location span — flattened line_start / line_end only
    # ------------------------------------------------------------------
    line_start: int = getattr(jedi_name, "line", None) or 1
    line_end: int = get_end_line(jedi_name)

    # ------------------------------------------------------------------
    # 4. Signature — PRESENT for callable kinds, ABSENT otherwise
    # ------------------------------------------------------------------
    stub: dict[str, Any] = {
        "handle": handle,
        "kind": kind,
        "scope": scope,
        "line_start": line_start,
        "line_end": line_end,
    }

    if kind in _CALLABLE_KINDS:
        sig = _build_signature(jedi_name)
        if sig is not None:
            stub["signature"] = sig
        else:
            # _build_signature returned None (e.g. class with no __init__
            # signatures available) — still include the key with the class
            # name as a minimal fallback so the contract always holds for
            # callable kinds.
            stub["signature"] = handle.split(".")[-1]

    return stub
