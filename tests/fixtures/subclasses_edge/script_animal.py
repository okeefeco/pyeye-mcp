"""Non-importable, script-style subclass of ``pkg.base.Animal`` (issue #348).

This module lives at the PROJECT ROOT, outside any package, so it has no
importable dotted path — its class's path-derived handle is
``script_animal.Lizard``.  ``scope="main"`` still discovers it, and the
resolver must build its stub by enumerating THIS file (not by re-resolving the
handle, which would drop a non-package script).  This proves the file-based
Name-production breadth required by the plan.
"""

from pkg.base import Animal


class Lizard(Animal):
    """Direct subclass of Animal defined in a root-level script module."""

    cold_blooded: bool = True
