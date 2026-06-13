"""Fixture for issue #337: method classification across class nesting.

- ``top_level_function`` is a module-level function -> kind "function".
- ``Outer.outer_method`` is a normal method -> kind "method".
- ``Outer.Inner.inner_method`` is a method of a NESTED class -> kind "method".
  This is the case ``_is_method`` previously misclassified as "function",
  because it re-derived the parent by dotted-name string arithmetic + a
  filesystem module lookup, which can't see that ``Outer`` is a class.
- ``Empty`` is a class with no members; used to test the max_depth frontier
  peek branch (outline.py §5.3): at the frontier, a genuine empty container
  must receive ``children: []``, not ``truncated: "max_depth"``.
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


class Empty:
    """A class with no members.

    Used to drive the genuine-empty-container peek branch in outline (spec
    §5.3): when ``Empty`` is at the ``max_depth`` frontier, ``resolve_members``
    returns [] → the node receives ``children: []`` (NOT ``truncated``).
    """
