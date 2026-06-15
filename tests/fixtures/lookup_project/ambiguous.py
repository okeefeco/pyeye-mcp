"""Module with an ambiguous name that could confuse global search.

Contains a class called Status that is NOT the enum — it's a different
class used for rendering. A global search for 'Status' would find both
this and enums.Status. Contextual resolution should prefer the import.
"""

from __future__ import annotations


class Status:
    """Rendering status — NOT the enum."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
