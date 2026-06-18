"""Sibling alias collision fixture.

This module imports the same symbol twice — once under its original name and
once under an alias. Both names in THIS module's namespace must resolve to the
canonical handle alias_pkg.source_mod.definitions.foo.

  alias_pkg.sibling.foo   -> alias_pkg.source_mod.definitions.foo
  alias_pkg.sibling.f     -> alias_pkg.source_mod.definitions.foo  (alias)
"""

from alias_pkg.source_mod.definitions import (
    foo,
    foo as f,
)

__all__ = ["foo", "f"]
