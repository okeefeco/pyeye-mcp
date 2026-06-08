"""Helper utilities for resolve_project.

Defines a second Widget class to create an ambiguous bare-name scenario.
Both mypackage._core.widgets.Widget and mypackage.helpers.Widget are
distinct classes — searching for the bare name 'Widget' should return
an ambiguous result with two candidates.
"""


class Widget:
    """An alternative Widget in the helpers module — intentionally same name."""

    label: str = "helper"
