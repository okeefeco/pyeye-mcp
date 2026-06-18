"""Unique symbols — only one of each, for single-match resolution tests."""


class UniqueWidget:
    """A widget class that only exists once in the fixture project."""

    def __init__(self, label: str) -> None:
        self.label = label

    def render(self) -> str:
        """Return a rendered representation."""
        return f"<widget>{self.label}</widget>"


def create_unique_widget(label: str) -> "UniqueWidget":
    """Factory function for UniqueWidget."""
    return UniqueWidget(label)
