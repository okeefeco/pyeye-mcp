"""#697 fixture: a class defined in a package ``__init__`` whose package has submodules."""


class Widget:
    """A class whose module file is the package ``__init__.py``."""

    size: int = 1

    def grow(self) -> int:
        """A method: the class's members are these, never the submodules."""
        return self.size + 1

    class Part:
        """A nested class, so the class has a container member too."""


def helper() -> int:
    """A function defined in the package ``__init__``."""
    return 2
