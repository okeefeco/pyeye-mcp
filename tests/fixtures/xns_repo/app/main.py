"""Project module that uses a configured namespace repo outside the project root (#623)."""

from acme.tools import Tool, helper
from acme.widgets import Widget


class FancyWidget(Widget):
    """A project class whose base lives in the namespace repo."""


def run() -> int:
    """Call into the namespace repo."""
    return helper() + Tool().use()
