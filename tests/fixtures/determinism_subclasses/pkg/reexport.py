"""Re-export of Base, so a conditional import crosses a re-export boundary."""

from .base import Base

__all__ = ["Base"]
