"""A module inside the ``acme`` PEP 420 namespace package (no ``__init__.py``)."""


def helper() -> int:
    """Return one."""
    return 1


class Tool:
    """A tool."""

    def use(self) -> int:
        """Use the tool."""
        return 2
