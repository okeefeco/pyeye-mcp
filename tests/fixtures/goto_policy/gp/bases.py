"""Superclasses in a non-sorted declaration order, plus an unresolvable base (#624)."""

import importlib

_dynamic = importlib.import_module("gp._fast")


class Zeta:
    """Declared first."""


class Alpha:
    """Declared second."""


class Ordered(Zeta, Alpha):
    """Bases in declaration order: Zeta, then Alpha (not sorted)."""


class Mixed(Zeta, _dynamic.Missing):  # type: ignore[name-defined,misc]
    """One resolvable base, then one goto can't name (a dynamically imported module's attribute)."""
