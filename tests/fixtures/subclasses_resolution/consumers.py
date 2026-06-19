"""Subclasses of ``pkg.core.Root`` via every base-resolution form (#405 guard).

The full project subclass closure of ``pkg.core.Root`` is exactly:
    {Direct, Aliased, Dotted, ViaReexport, GrandChild}

- ``Direct``      — `from pkg.core import Root` then `class Direct(Root)`
- ``Aliased``     — `from pkg.core import Root as R` then `class Aliased(R)`
- ``Dotted``      — `from pkg import core` then `class Dotted(core.Root)`
- ``ViaReexport`` — `from pkg import Root as ReRoot` (re-export) then `class ViaReexport(ReRoot)`
- ``GrandChild``  — `class GrandChild(Direct)` (indirect, through a resolved child)
"""

from pkg import (
    Root as ReRoot,
    core,
)
from pkg.core import (
    Root,
    Root as R,
)


class Direct(Root):
    """Direct-name base via a direct import."""


class Aliased(R):
    """Aliased base name (`as R`)."""


class Dotted(core.Root):
    """Dotted base reference through a module import."""


class ViaReexport(ReRoot):
    """Base imported through a package re-export (`pkg.Root` → `pkg.core.Root`)."""


class GrandChild(Direct):
    """Indirect (grandchild) subclass, through the resolved ``Direct`` child."""
