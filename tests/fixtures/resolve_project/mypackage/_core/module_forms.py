"""Fixture module for testing module-member enumeration edge cases (spec §3.3).

Covers definition forms that the legacy Jedi ``get_names(all_scopes=False)``
counter includes but the old AST hand-walk MISSED:
- tuple-unpacking assignment (``ALPHA, BETA = 1, 2``)
- plain annotated assignment (``GAMMA: Final[int] = 3``)

The import (``from typing import Final``) is present intentionally — it
exists to verify that import-exclusion is preserved (the imported name MUST
NOT appear in ``resolve_members`` output).  ``Final`` is referenced in the
type annotation of ``GAMMA`` so ruff's F401 unused-import check is satisfied.
``Final`` is valid at module scope (unlike ``ClassVar``, which is only valid
inside a class body).
"""

from typing import Final


def some_function() -> None:
    """A plain top-level function — must appear in members."""


class SomeClass:
    """A plain top-level class — must appear in members."""


# Tuple-unpacking: the legacy counter sees ALPHA and BETA via get_names;
# the old AST walk missed these because ast.Assign.targets[0] is a Tuple,
# not a Name.
ALPHA, BETA = 1, 2

# Annotated assignment: must appear in members.
GAMMA: Final[int] = 3
