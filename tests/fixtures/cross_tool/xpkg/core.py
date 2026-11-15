"""Definition site for the #614 cross-tool corpus.

Line numbers are load-bearing: ``tests/test_cross_tool_invariants.py`` passes
definition positions to ``resolve_at``.  Append, don't insert.
"""

import logging
from enum import Enum
from pathlib import Path

LOG = logging.getLogger(__name__)


class Widget:
    """A widget with a nested class, a class attribute and a method."""

    size: int = 3

    class Inner:
        """A nested class."""

        def ping(self) -> str:
            """Nested method."""
            return "pong"

    def greet(self) -> str:
        """Plain method."""
        return str(Path("x"))


class Color(Enum):
    """An enum: its members are class attributes."""

    RED = 1


def make_widget() -> Widget:
    """Function with project and stdlib callees."""
    LOG.info("making")
    return Widget()
