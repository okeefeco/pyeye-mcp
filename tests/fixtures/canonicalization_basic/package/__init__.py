"""Public package surface — re-exports Config from its private implementation."""

from package._impl.config import Config

__all__ = ["Config"]
