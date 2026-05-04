"""Fixture A from acceptance criterion #14 — typing-alias generics.

Exercises the half of the TypeRef head-canonicalisation rule that pins
``typing.Dict`` / ``typing.List`` as the resolved handles when the source
imports the deprecated typing aliases. ``inspect(process).parameters[0].type``
must produce a recursive TypeRef whose root ``handle`` is ``"typing.Dict"``
(NOT ``"builtins.dict"``) — the implementation is forbidden from silently
rewriting one canonicalisation half to the other.

The same module also exercises return-type symmetry: ``process`` returns
``List[CustomModel]``, so ``inspect(process).return_type`` follows the
identical recursive shape.

Linter overrides
----------------
``# noqa: UP006`` and ``# noqa: UP035`` keep ruff's pyupgrade rule from
auto-rewriting ``Dict``/``List`` → ``dict``/``list``. Such a rewrite would
collapse Fixtures A and B into the same canonicalisation half and silently
invalidate criterion #14 — which is precisely what the rule is meant to
detect. Do NOT remove these suppressions.
"""

from typing import Dict, List  # noqa: UP035

from models import CustomModel


def process(x: Dict[str, List[CustomModel]]) -> List[CustomModel]:  # noqa: UP006
    """Compound generic written with typing aliases — Fixture A scenario."""
    return list(x.values())[0] if x else []
