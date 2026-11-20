"""Classes whose bases come through a shim (#1057)."""

import threading

from .core import Widget
from .rebind import Cursor
from .shim import Local


class ThreadState(threading.local):
    """Subclasses the stdlib ``threading.local`` shim."""


class ShimChild(Local):
    """Subclasses the project shim's ``Local``."""


class Gadget(Widget):
    """Subclasses a plain project class (the stable case)."""


def make() -> tuple[ShimChild, ThreadState, Gadget]:
    """Build one of each."""
    return ShimChild(), ThreadState(), Gadget()


class CursorChild(Cursor):
    """Subclasses an if/else-rebound name through a module-level import."""


def make_local() -> type:
    """Define a class whose base is imported in the function, as django's tests do."""
    from .rebind import Cursor as LocalBase

    class LocalCursor(LocalBase):
        """Subclasses the rebound name through a function-local import."""

    return LocalCursor
