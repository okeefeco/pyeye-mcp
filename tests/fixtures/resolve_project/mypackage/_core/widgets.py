"""Widget implementation — the definition site.

Canonical handle: mypackage._core.widgets.Widget
"""


class Widget:
    """A UI widget component."""

    name: str = "default"
    visible: bool = True


class Config:
    """Configuration for resolve_project — single definition, not re-exported elsewhere.

    Used for bare-name single-match test (test case a, unique result).
    """

    debug: bool = False
    host: str = "localhost"
