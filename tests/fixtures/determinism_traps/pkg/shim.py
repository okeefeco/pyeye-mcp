"""A project try/except import shim: ``Local`` is one of two classes."""

try:
    from ._fast import Local
except ImportError:
    from ._slow import Local

__all__ = ["Local"]
