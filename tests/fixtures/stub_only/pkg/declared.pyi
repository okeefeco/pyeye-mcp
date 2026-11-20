"""Declared only, and importing a project module (#933).

A stub's imports are declarations, not runtime imports: ``imported_by(pkg.base)``
doesn't count this module, while its own ``imports`` lists ``pkg.base`` and
``pkg.base.Base``.
"""

from pkg import base
from pkg.base import Base

class Sub(Base):
    def run(self) -> None: ...
