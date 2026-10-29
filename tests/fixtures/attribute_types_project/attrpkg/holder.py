"""A class attribute annotated with a name two modules define.

``Slot.widget``'s annotation must resolve through this file's import to
``attrpkg.real.Widget``; a global name search could just as well return
``attrpkg.other.Widget``.
"""

from attrpkg.real import Widget


class Slot:
    """Holds a Widget as a class attribute."""

    widget: Widget = Widget()
