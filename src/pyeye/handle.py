"""Canonical Handle type for the PyEye resolve/inspect API.

A Handle is a plain Python dotted-name string that uniquely identifies a
symbol within a project's scope.  Examples::

    Handle("mypackage.mymodule")
    Handle("a.b.c.MyClass")
    Handle("a.b.c.MyClass.__init__")

Handles are str subclasses so they work transparently in string contexts
(comparisons, dict keys, f-strings) while carrying validated semantics.

Serialization shape (round-trip)::

    {"handle": "a.b.c.MyClass"}
"""

from __future__ import annotations

from typing import Any

from pyeye.symbol_parser import parse_compound_symbol


class Handle(str):
    """A validated, canonical Python dotted-name identifying one symbol.

    Equality and hashing are identical to the underlying ``str`` value so
    that ``Handle("a.b") == "a.b"`` and both can be used as equivalent dict
    keys.

    Raises:
        ValueError: If *value* is not a valid Python dotted name.
    """

    def __new__(cls, value: str) -> Handle:
        """Create a Handle, raising ValueError for invalid dotted names."""
        _, valid = parse_compound_symbol(value)
        if not valid:
            raise ValueError(
                f"Invalid handle {value!r}: must be a non-empty dotted Python name "
                "with no leading/trailing/double dots and each component a valid "
                "Python identifier."
            )
        return super().__new__(cls, value)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Serialise to ``{"handle": "<dotted-name>"}``.

        The dict form is stable and can be stored in JSON or passed over the
        wire; use :meth:`from_dict` to reconstruct.
        """
        return {"handle": str(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Handle:
        """Reconstruct from a dict produced by :meth:`to_dict`.

        Args:
            data: A mapping that must contain a ``"handle"`` key whose value
                is a valid dotted name.

        Raises:
            KeyError: If ``"handle"`` is absent.
            ValueError: If the value is not a valid dotted name.
        """
        return cls(data["handle"])

    # ------------------------------------------------------------------
    # Factory from path components
    # ------------------------------------------------------------------

    @classmethod
    def from_parts(cls, parts: list[str]) -> Handle:
        """Build a Handle by joining *parts* with dots.

        Args:
            parts: Non-empty sequence of Python identifier strings, e.g.
                ``["mypackage", "mymodule", "MyClass"]``.

        Raises:
            ValueError: If *parts* is empty or any component is invalid.
        """
        if not parts:
            raise ValueError("from_parts requires at least one component.")
        return cls(".".join(parts))
