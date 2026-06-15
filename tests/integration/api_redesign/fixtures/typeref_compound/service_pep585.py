"""Fixture B from acceptance criterion #14 — PEP 585 builtin generics.

Exercises the other half of the TypeRef head-canonicalisation rule:
``dict`` / ``list`` (lowercase, no ``typing`` import) must resolve to
``builtins.dict`` / ``builtins.list``. Together with ``service_typing_aliases``
this pins both halves of the rule and lets the conformance test assert
the two halves produce DISTINCT root handles. If both fixtures collapse
to the same handle, the implementation has silently normalised one form
to the other — a spec violation per criterion #14.

The shape is intentionally identical to Fixture A's ``process`` (same
parameter pattern, same project-class leaf) so the only varying axis is
the typing-vs-builtin head canonicalisation.

No linter overrides are required here: the lowercase builtins are the
form pyupgrade WANTS, so ruff leaves them alone.
"""

from models import CustomModel


def process(x: dict[str, list[CustomModel]]) -> list[CustomModel]:
    """Compound generic written with PEP 585 builtins — Fixture B scenario."""
    return list(x.values())[0] if x else []
