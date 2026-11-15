"""One goto-disambiguation policy for the edges, inspect and typeref (#624).

Jedi's ``goto(follow_imports=True)`` can return several definitions for one
position: a ``bytes | str`` receiver's ``.endswith``, a name bound by a
``try``/``except ImportError`` fallback, a ``.clear()`` whose receiver Jedi
infers two ways. Before #624, four call sites picked among them with four
rules, and three of them guessed (the first match). The same ``.clear()``
then resolved to ``OrderedDict.clear`` in one file and ``MutableMapping.clear``
in another.

The rule, the only one: **exactly one distinct target, or no answer.**

- Results are de-duplicated by ``full_name``; results without one are ignored.
- ``prefer`` (e.g. ``"class"`` for a base class) breaks a tie only when it
  leaves exactly one distinct target.
- Anything else is ``None``, which every caller reports honestly as
  unresolved (``unresolved_call_sites``, ``unresolved_imports``,
  ``unresolved_superclasses``, or a typeref without a handle) — never a guess.

This is a lower layer: it must not import ``pyeye.mcp``
(``tests/test_import_layers_fitness.py``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def pick_target(defs: Iterable[Any], *, prefer: str | None = None) -> Any | None:
    """Return the one definition *defs* name, or ``None`` if they don't name exactly one.

    Args:
        defs: Jedi ``Name`` results of a ``goto``.
        prefer: A Jedi ``type`` (e.g. ``"class"``) to narrow a tie with. It is
            consulted only when there are several distinct targets.

    Returns:
        The first ``Name`` for the single distinct ``full_name``, or ``None``
        when there are none or several.
    """
    by_name: dict[str, Any] = {}
    for d in defs:
        full_name = getattr(d, "full_name", None)
        if full_name and full_name not in by_name:
            by_name[full_name] = d
    if len(by_name) == 1:
        return next(iter(by_name.values()))
    if prefer is not None and len(by_name) > 1:
        preferred = [d for d in by_name.values() if getattr(d, "type", None) == prefer]
        if len(preferred) == 1:
            return preferred[0]
    return None


def goto_target(script: Any, line: int, col: int, *, prefer: str | None = None) -> Any | None:
    """``goto(follow_imports=True)`` at (*line*, *col*), then :func:`pick_target`.

    Any error from Jedi (including a ``RecursionError`` on the large-stack
    worker, #650) is no answer, never an exception.

    Args:
        script: A ``jedi.Script``.
        line: 1-based line.
        col: 0-based column.
        prefer: Passed to :func:`pick_target`.

    Returns:
        The single target ``Name``, or ``None``.
    """
    try:
        defs = script.goto(line, col, follow_imports=True)
    except Exception:
        return None
    return pick_target(defs, prefer=prefer)
