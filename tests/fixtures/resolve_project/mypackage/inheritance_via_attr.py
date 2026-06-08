"""Fixture for the dotted-base inheritance bug repro.

Triggers the case where a class extends ``package.SubClass`` via
attribute access — base_node.col_offset points at the package name,
so naive script.goto() at that position returns the package, not the class.
"""

from mypackage import _core


class ViaAttr(_core.widgets.Widget):
    """Inherits via attribute access on a subpackage."""

    pass
