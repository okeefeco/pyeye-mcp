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
  Of several results with one ``full_name`` (a name bound twice), the one of
  the ``prefer`` type stands for it, else the earliest by position, never the
  first returned: Jedi's order differs between processes (#1057).
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
from pathlib import PurePath
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
    grouped: dict[str, list[Any]] = {}
    for d in defs:
        full_name = getattr(d, "full_name", None)
        if full_name:
            grouped.setdefault(full_name, []).append(d)
    by_name = {name: _representative(group, prefer) for name, group in grouped.items()}
    if len(by_name) == 1:
        return next(iter(by_name.values()))
    if prefer is not None and len(by_name) > 1:
        preferred = [d for d in by_name.values() if getattr(d, "type", None) == prefer]
        if len(preferred) == 1:
            return preferred[0]
    return None


def _representative(group: list[Any], prefer: str | None) -> Any:
    """The one ``Name`` to stand for several results that share a ``full_name``.

    A name bound twice (``if X: class C`` / ``else: C = other``) comes back as
    two results in an order that differs between processes, so the choice is
    never the first one (#1057): a result of the *prefer* type wins, then the
    earliest by file and position.
    """

    def key(d: Any) -> tuple[bool, str, int, int]:
        module_path = getattr(d, "module_path", None)
        return (
            prefer is not None and getattr(d, "type", None) != prefer,
            PurePath(module_path).as_posix() if module_path else "",
            getattr(d, "line", None) or 0,
            getattr(d, "column", None) or 0,
        )

    return min(group, key=key)


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


def binding_target(script: Any, line: int, col: int) -> Any | None:
    """``goto`` WITHOUT following imports at (*line*, *col*), then :func:`pick_target`.

    Lands on the binding a name refers to, such as the ``from collections.abc
    import Mapping`` that bound ``Mapping``, whose ``full_name`` is the imported
    path. Used where the imported path, not typeshed's view of its target,
    decides the handle (#544). Any error from Jedi is no answer.
    """
    try:
        defs = script.goto(line, col, follow_imports=False)
    except Exception:
        return None
    return pick_target(defs)
