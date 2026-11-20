"""Classes whose bases come through a shim (#1057)."""

import threading

from .core import Widget
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
