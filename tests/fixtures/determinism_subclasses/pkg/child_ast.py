"""Subclass whose base is resolvable by the AST resolver (deterministic path).

``from .base import Base`` is a top-level import, so ``resolve_base`` commits to
``pkg.base.Base`` without ever consulting Jedi ``goto``.
"""

from .base import Base


class ChildAst(Base):
    """Direct subclass resolved via the AST import table."""
