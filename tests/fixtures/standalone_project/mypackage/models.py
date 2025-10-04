"""Models module for testing."""


class MyClass:
    """A test class used in standalone scripts."""

    def __init__(self, name: str):
        """Initialize with a name."""
        self.name = name

    def greet(self) -> str:
        """Return a greeting."""
        return f"Hello, {self.name}!"


def helper_function(value: int) -> int:
    """A helper function used in scripts."""
    return value * 2
