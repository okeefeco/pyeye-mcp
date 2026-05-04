"""Fixture demonstrating subclass-counter name-collision bug.

Defines a SECOND class named ``Widget`` (unrelated to mypackage._core.widgets.Widget)
and a subclass of THIS Widget. The subclass-counter currently lumps both
Widgets together because it disambiguates only by simple name.
"""


class Widget:
    """A completely different Widget — should NOT be confused with the real one."""

    pass


class UnrelatedSub(Widget):
    """Extends the LOCAL Widget, NOT mypackage._core.widgets.Widget."""

    pass
