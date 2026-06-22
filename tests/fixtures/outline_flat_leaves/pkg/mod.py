"""Fixture for issue #358: a module of all-leaf members.

The worst case for the mid-expansion truncation bug: when a node-budget cutoff
lands while enumerating a container whose dropped siblings are ALL leaves, the
old code produced ZERO truncation markers anywhere in the tree while silently
shortening the parent's ``children`` list.  Five module-level functions (no
nested containers) make every direct member a leaf.
"""


def alpha() -> int:
    """Leaf 1."""
    return 1


def beta() -> int:
    """Leaf 2."""
    return 2


def gamma() -> int:
    """Leaf 3."""
    return 3


def delta() -> int:
    """Leaf 4."""
    return 4


def epsilon() -> int:
    """Leaf 5."""
    return 5
