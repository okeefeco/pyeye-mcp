"""Subclass whose base falls back to Jedi ``goto`` (the non-deterministic path).

The base is imported inside an ``if TYPE_CHECKING:`` guard — a conditional
import, so it is NOT a top-level import node. ``build_import_table`` cannot see
it and ``resolve_base`` punts to ``None``. ``find_subclasses`` then resolves the
base via ``script.goto(follow_imports=True)``, crossing the ``reexport``
boundary to ``pkg.base.Base``. This is exactly the resolution path #419 is
about; the determinism test asserts its result is stable across processes.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .reexport import Base


class ChildGoto(Base):  # noqa: F821 - resolved statically (TYPE_CHECKING-only import)
    """Direct subclass resolved via the Jedi ``goto`` fallback."""
