"""Cross-fixture invariant (g) from acceptance criterion #14 — Callable.

Exercises the spec-permitted DEGRADED PATH: ``Callable[[A, B], C]`` has
an uneven bracket structure (``[args_list, return_type]``) that does not
fit the uniform TypeRef recursion. The spec explicitly allows this path
to omit ``handle`` and/or ``args`` so long as ``raw`` carries the full
expression as written. The conformance test asserts only that minimal
contract — populating ``args`` is allowed but not required, and any
``handle`` populated must be honest (no guessed value).

Import choice: ``collections.abc.Callable`` is the modern best practice
since PEP 585 and the planned removal of ``typing.Callable`` from
``typing.__all__``. This is what real codebases written today should
use, and the degraded-path contract is identical regardless of which
import is chosen.
"""

from collections.abc import Callable


def register(callback: Callable[[int, str], bool]) -> None:
    """Callable parameter — degraded TypeRef path conformant per spec."""
    _ = callback  # silence unused-arg without changing the annotation surface
