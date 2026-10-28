"""Fixture module for GUARDED module-scope imports (#360).

Every import below binds a name at MODULE scope even though it is nested inside
top-level control flow.  Such names must be excluded from the ``members`` edge
(they are not defined here) and included in the ``imports`` edge (they are real
static dependencies):

- ``if TYPE_CHECKING:`` → ``Widget``
- ``try:``/``except ImportError:`` shim → ``Premium`` (from ``Premium``, falling
  back to ``Deluxe``)
- ``if <flag>:`` conditional guard → ``Config``

The two imports that are NOT module-scope — and so must appear in NEITHER edge —
sit inside a function body and a class body.  Each targets a distinct symbol
(``DEFAULT_NAME`` / ``make_widget``) that is shadowed by a same-named module-level
definition, so a walker that wrongly descended into ``def``/``class`` bodies
would both drop a real member and emit a phantom import.

``guarded_function`` is a ``def`` under a top-level guard: guarded DEFINITIONS
stay members — only guarded IMPORTS are subtracted.

Canonical handle: ``mypackage._core.guarded_imports_fixture``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .widgets import Widget

try:
    from .widgets import Premium
except ImportError:  # pragma: no cover - optional-dependency shim pattern
    from .widgets import Deluxe as Premium

_FEATURE_FLAG = True

if _FEATURE_FLAG:
    from .widgets import Config

# Module-level definition shadowed by the FUNCTION-local import in load_default.
DEFAULT_NAME = "guarded"


def make_widget() -> str:
    """Module-level definition shadowed by the CLASS-body import in ``Holder``."""
    return DEFAULT_NAME


def guarded_consumer(widget: Widget, premium: Premium, config: Config) -> None:
    """Reference the guarded imports in annotations (keeps them used)."""


def load_default() -> str:
    """Function-local import — binds a LOCAL name, never a module member."""
    from .widgets import DEFAULT_NAME

    return DEFAULT_NAME


class Holder:
    """Class-body import — binds a CLASS attribute, never a module member."""

    from .widgets import make_widget

    factory = make_widget


if _FEATURE_FLAG:

    def guarded_function() -> None:
        """A ``def`` under a top-level guard — still a module member."""
