"""Fixture for issue #337: method classification across class nesting.

- ``top_level_function`` is a module-level function -> kind "function".
- ``Outer.outer_method`` is a normal method -> kind "method".
- ``Outer.Inner.inner_method`` is a method of a NESTED class -> kind "method".
  This is the case ``_is_method`` previously misclassified as "function",
  because it re-derived the parent by dotted-name string arithmetic + a
  filesystem module lookup, which can't see that ``Outer`` is a class.
"""


def top_level_function() -> int:
    """A plain module-level function."""
    return 1


class Outer:
    """A top-level class."""

    def outer_method(self) -> int:
        """A method on a top-level class."""
        return 2

    class Inner:
        """A class nested inside Outer."""

        def inner_method(self) -> int:
            """A method on a nested class — the #337 misclassification case."""
            return 3
