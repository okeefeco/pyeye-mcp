"""Widget implementation — the definition site.

Canonical handle: mypackage._core.widgets.Widget

Extended for inspect tests (Task 3.1) to cover all Python kinds:
- class: Widget
- function: make_widget
- method: Widget.greet
- module: mypackage._core.widgets (this module itself)
- attribute: Widget.color (ClassVar)
- property: Widget.display_name
- variable: DEFAULT_NAME (module-level)
"""

from typing import ClassVar

# Module-level variable — for TestInspectVariable
DEFAULT_NAME: str = "widget"


class Widget:
    """A UI widget component.

    Has a constructor signature, docstring, methods, properties, and
    class attributes — covers most kind-dependent fixture needs.
    """

    # Class attribute — for TestInspectAttribute
    color: ClassVar[str] = "blue"

    name: str = "default"
    visible: bool = True

    def __init__(self, name: str = "anon") -> None:
        self.name = name

    def greet(self) -> str:
        """Greet the world."""
        return f"hello from {self.name}"

    async def slow_greet(self) -> str:
        """Async variant — for is_async test."""
        return self.greet()

    @property
    def display_name(self) -> str:
        """Display-friendly name."""
        return self.name.title()

    @classmethod
    def default(cls) -> "Widget":
        """Class method — for is_classmethod test."""
        return cls()

    @staticmethod
    def normalize(name: str) -> str:
        """Static method — for is_staticmethod test."""
        return name.strip().lower()


class Config:
    """Configuration for resolve_project — single definition, not re-exported elsewhere.

    Used for bare-name single-match test (test case a, unique result).
    """

    debug: bool = False
    host: str = "localhost"


def make_widget(widget_name: str) -> "Widget":
    """Factory function to verify resolve returns kind='function'."""
    w = Widget()
    w.name = widget_name
    return w


# ---------------------------------------------------------------------------
# Subclasses added for Phase 4 edge_counts tests (Task 4.1)
# Added at END to avoid shifting line numbers of existing symbols.
# Widget is at line 21, make_widget at line 71 — both unchanged.
# ---------------------------------------------------------------------------


class Premium(Widget):
    """Premium widget — extends Widget explicitly.

    Used by TestInspectEdgeCounts to verify:
    - superclasses count > 0 (Widget is an explicit base)
    - Widget.subclasses count > 0 (Premium and Deluxe are project subclasses)
    """

    tier: str = "premium"


class Deluxe(Widget):
    """Deluxe widget — second explicit subclass of Widget.

    Used together with Premium to give Widget a subclasses count of >= 2.
    """

    tier: str = "deluxe"
