"""Fixture exercising the ``callees`` forward-resolution edge (Task 3.1).

Canonical handle of the source function under test:
``mypackage._core.callees_fixture.orchestrate``.

``orchestrate``'s body deliberately covers every path the resolver must handle:

- a project call (``make_widget`` from ``mypackage._core.widgets``) — resolves to
  a ``project``-scope canonical handle,
- a stdlib call (``math.sqrt``) — resolves to an ``external``-scope handle (its
  attribute target must goto the rightmost identifier, not the ``math`` module),
- the SAME project call twice (dedup must collapse it to one callee),
- a dynamic call through an un-inferable parameter (``cb()``) — Jedi cannot
  resolve this, so it must increment ``unresolved_call_sites`` (count only, never
  an invented handle),
- a NESTED function (``_inner``) whose own call (``len``) must NOT be attributed
  to ``orchestrate`` — a nested scope's callees are its own.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from mypackage._core.widgets import make_widget


def orchestrate(cb: Callable[[], object]) -> float:
    """Drive several calls of different resolvability for the callees test.

    Args:
        cb: An un-inferable callable parameter; calling it is a dynamic call
            site that ``goto`` cannot statically resolve.

    Returns:
        A float, so the function body type-checks; the value is incidental.
    """
    # Project call (resolvable) — appears twice to exercise dedup.
    first = make_widget("alpha")
    second = make_widget("beta")  # noqa: F841 — second binding exercises dedup

    # Stdlib call (external-scope, attribute target on rightmost identifier).
    root = math.sqrt(2)

    # Dynamic call through an un-inferable parameter — unresolvable.
    cb()

    def _inner() -> int:
        # Nested-scope call: ``len`` is a callee of _inner, NOT of orchestrate.
        return len(first.name)

    return root + float(_inner())
