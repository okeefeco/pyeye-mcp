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
      "signature":  str,               # PRESENT whenever Jedi yields a real
                                       # signature (always for class/function/
                                       # method; also for any other name whose
                                       # inferred type is callable, e.g. a
                                       # variable bound to None → "NoneType()")
      "line_start": int,
      "line_end":   int,
    }

Design notes
------------
- ``signature`` is present whenever ``_build_signature`` returns a real Jedi
  signature, and the key is OMITTED (NOT an empty string) otherwise.  For a stub
  built from a real Jedi ``Name`` this is the case for ``class`` / ``function``
  / ``method`` (and ALSO any non-callable kind whose inferred type is callable —
  e.g. a ``variable`` bound to ``None`` yields ``"NoneType()"``).  It is
  DELIBERATELY ABSENT, however, for stubs built from a lightweight *sentinel*
  that carries no Jedi inference: the ``subclasses`` edge's ``ClassSentinel`` and
  the ``imported_by`` edge's ``ModuleSentinel`` are pointers (handle + location +
  kind), so their stubs never carry ``signature`` even though their kind is
  ``class`` / ``module`` (#445).  A subclass's constructor signature is an
  ``inspect`` drill detail, not a one-hop ``expand`` field — and deriving it here
  faithfully would need an MRO walk per subclass (a child often inherits its
  constructor), reintroducing the multi-file inference whose non-determinism
  #445 removed.  The conformance linter (S.2) matches this: ``signature`` is
  optional and, when present, must be a single-line str — it is NOT gated on
  kind.
- ``line_start`` / ``line_end`` are the flattened span: ``line_start`` is the
  symbol's own line; ``line_end`` is ``get_end_line(jedi_name)``.  For a
  class/function this is the end of the definition block.  It is NOT guaranteed
  to equal ``line_start`` for other kinds — a class-body attribute, for
  instance, can report the enclosing class's end line.  The only invariant the
  linter enforces is ``line_end >= line_start``.
- No source content anywhere — no ``body``, ``source``, ``code``, ``snippet``,
  or ``text`` fields.
- ``build_stub`` is a **pure synchronous** function.  It does not call
  ``get_references``.

Reuse policy (#330)
-------------------
All helpers come from existing modules — no second implementation:

- Kind + method:      ``pyeye.mcp.operations.resolve._normalise_kind_from_name``
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
from pyeye.mcp.operations.inspect import _build_signature
from pyeye.mcp.operations.resolve import _normalise_kind_from_name
from pyeye.scope import classify_scope

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_stub(jedi_name: Any, handle: str, analyzer: JediAnalyzer) -> dict[str, Any]:
    """Build a spec §4.1 Stub from a Jedi Name and a pre-computed canonical handle.

    The caller is responsible for canonicalising the handle (Phase-2 resolvers
    or Phase-4 expand supply it).  ``build_stub`` does NOT canonicalize.

    Args:
        jedi_name: A Jedi ``Name`` object (or ``ModuleSentinel``-compatible
            object) for the symbol.
        handle: The already-canonical dotted-name handle for the symbol.
        analyzer: Active analyzer for scope classification.

    Returns:
        A Stub dict conforming to spec §4.1.
    """
    # ------------------------------------------------------------------
    # 1. Kind — normalise, promoting function → method when applicable (#406)
    # ------------------------------------------------------------------
    kind = _normalise_kind_from_name(jedi_name)

    # ------------------------------------------------------------------
    # 2. Scope — pure path comparison via classify_scope
    # ------------------------------------------------------------------
    module_path = getattr(jedi_name, "module_path", None)
    if module_path is not None:
        file_str = module_path.as_posix()
        scope = classify_scope(file_str, analyzer)
        # #454: reconcile an externally-resolved edge target back to the project
        # definition site.  A forward-goto edge (imports / callees) can land on an
        # INSTALLED copy of a package that is ALSO registered as a project /
        # namespace module — Jedi's follow_imports honours the environment
        # sys.path, which outranks the namespace ``added_sys_path``.  ``resolve`` /
        # ``inspect`` instead anchor via ``find_module_file`` (the project
        # boundary) and call the same handle ``project``.  Keep the two consistent:
        # if the canonical handle names a project module, the symbol IS a project
        # symbol regardless of which on-disk copy Jedi happened to follow.  (Only
        # ``scope`` is reconciled — the stub carries no file; line spans stay as
        # Jedi reported them, which match for the common same-version case.)
        #
        # Perf short-circuit: the split this rescues needs the SAME package to be
        # importable from BOTH a registered sibling root AND an installed copy
        # that wins Jedi's precedence — only possible when sibling roots are
        # registered (``additional_paths``).  With none, skip the per-stub
        # ``find_module_file`` filesystem probe entirely, keeping the common
        # single-project ``callees`` / ``imports`` expansion (every stdlib target
        # is external) free of I/O.  (Theoretical gap: a NON-editable duplicate
        # install of a project's own ``source_roots`` / ``project_path`` package —
        # pathological; editable installs resolve to the real path via
        # ``classify_scope``'s symlink-first rule, #338.)
        if (
            scope == "external"
            and getattr(analyzer, "additional_paths", None)
            and _names_project_module(handle, kind, analyzer)
        ):
            scope = "project"
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
    # 4. Signature — PRESENT only when a REAL Jedi signature exists
    # ------------------------------------------------------------------
    stub: dict[str, Any] = {
        "handle": handle,
        "kind": kind,
        "scope": scope,
        "line_start": line_start,
        "line_end": line_end,
    }

    sig = _build_signature(jedi_name)
    if sig is not None:
        stub["signature"] = sig

    return stub


def _names_project_module(handle: str, kind: str, analyzer: JediAnalyzer) -> bool:
    """Whether *handle*'s module portion resolves to a project-boundary file.

    Used by :func:`build_stub` to reconcile a #454 scope split: an edge target
    that Jedi followed to an installed copy is still a project symbol if its
    canonical handle names a project module.  ``find_module_file`` searches the
    SAME boundary (``source_roots`` + ``project_path`` + ``additional_paths``)
    that ``classify_scope`` treats as ``project`` — and excludes
    ``added_sys_path`` / the environment — so a stdlib / pure-external handle
    yields ``None`` and is NOT reconciled.

    The module portion is the whole handle for a ``module`` kind, else the handle
    minus its trailing symbol component.
    """
    from pyeye.canonicalization import find_module_file

    if kind == "module":
        module_dotted = handle
    else:
        parts = handle.split(".")
        if len(parts) < 2:
            return False
        module_dotted = ".".join(parts[:-1])

    return find_module_file(module_dotted, analyzer) is not None
