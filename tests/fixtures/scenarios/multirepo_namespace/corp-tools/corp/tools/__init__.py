"""Repo B: the tools portion of the ``corp`` namespace.

Re-exports ``corp.core.models.Base`` so it is importable as ``corp.tools.Base``.
"""

from corp.core.models import Base

__all__ = ["Base"]
