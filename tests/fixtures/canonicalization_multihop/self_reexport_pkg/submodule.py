"""Submodule that defines Foo and exports it via __all__.

Canonical handle: self_reexport_pkg.submodule.Foo

The __all__ here is an extra re-export signal for Foo alongside the
explicit import in self_reexport_pkg/__init__.py.
But because the __init__.py also has "from self_reexport_pkg.submodule import Foo",
Jedi's full_name for Foo in __init__.py will be self_reexport_pkg.submodule.Foo.
"""

__all__ = ["Foo"]


class Foo:
    """A simple class defined at the submodule level."""

    pass
