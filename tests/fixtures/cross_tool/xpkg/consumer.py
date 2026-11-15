"""Imports a PEP 420 namespace package and the re-exported alias."""

import xns
import xns.portion

from xpkg import Widget


def use() -> str:
    """Call into the namespace package."""
    return xns.portion.thing() + str(Widget)
