"""Plain project code: members, callees, imports, enclosing_scope."""

import os.path


class Widget:
    """A class with a method that calls project and stdlib code."""

    size = 1

    def grow(self, step: int) -> int:
        """Grow by *step*."""
        return helper(self.size + step)


def helper(value: int) -> int:
    """Return *value* as an absolute path length, via the stdlib."""
    return len(os.path.join("x", str(value)))
