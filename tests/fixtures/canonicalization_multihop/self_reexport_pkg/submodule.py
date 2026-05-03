"""Submodule that defines Foo and exports it via __all__.

Canonical handle: self_reexport_pkg.submodule.Foo

The __all__ here causes _check_symbol_in_init's __all__ fallback to fire
when checking whether self_reexport_pkg/__init__.py re-exports Foo.
But because the __init__.py also has "from self_reexport_pkg.submodule import Foo",
Jedi's full_name for Foo in __init__.py will be self_reexport_pkg.submodule.Foo.
"""

__all__ = ["Foo"]


class Foo:
    """A simple class defined at the submodule level."""

    pass
