"""Functions and a class whose annotations cover every TypeRef scenario.

Scenarios (a)–(h) from Task 8.1:
  (a) ``bare_name_leaf``      — bare name leaf (Path)
  (b) ``typing_alias_generic`` — typing.Dict / typing.List / project class
  (c) ``builtin_generic``     — PEP 585 dict / list / project class
  (d) ``pep604_union``        — str | None
  (e) ``unresolvable_forward`` — quoted forward ref to a non-existent symbol
  (f) ``callable_param``      — Callable[[int, str], bool] (degraded path)
  (g) ``returns_dict_model``  — Dict[str, CustomModel] used as return type
  (h) ``HasTypedField.field`` — class attribute with List[CustomModel]

Linter overrides
----------------
This fixture deliberately uses BOTH the deprecated ``typing.Dict`` /
``typing.List`` aliases AND the PEP 585 lowercase builtins because the spec's
TypeRef canonicalisation rule is verified against both halves (Fixtures A and
B in acceptance criterion #14). Inline ``# noqa: UP006`` / ``# noqa: UP035``
comments suppress pyupgrade auto-rewrites that would collapse the two forms.
``# noqa: F821`` covers the intentional unresolvable forward ref in scenario
(e). Do NOT remove these suppressions — they preserve the test contract.
"""

from pathlib import Path
from typing import Callable, Dict, List  # noqa: UP035

from mypackage.models import CustomModel


def bare_name_leaf(x: Path) -> None:
    """Scenario (a): bare-name leaf annotation."""


def typing_alias_generic(x: Dict[str, List[CustomModel]]) -> None:  # noqa: UP006
    """Scenario (b): typing aliases (Dict / List) at the generic head."""


def builtin_generic(x: dict[str, list[CustomModel]]) -> None:
    """Scenario (c): PEP 585 lowercase builtin generics."""


def pep604_union(x: str | None) -> None:
    """Scenario (d): PEP 604 union — no single canonical head symbol."""


def unresolvable_forward(x: "FutureType") -> None:  # noqa: F821
    """Scenario (e): forward-ref string for a symbol that does not exist."""


def callable_param(callback: Callable[[int, str], bool]) -> None:
    """Scenario (f): Callable — spec-permitted degraded path in v1."""


def returns_dict_model() -> Dict[str, CustomModel]:  # noqa: UP006
    """Scenario (g): annotated return type — symmetric with parameter types."""
    return {}


class HasTypedField:
    """Scenario (h): class-attribute annotation surfaces as TypeRef."""

    field: List[CustomModel] = []  # noqa: UP006
