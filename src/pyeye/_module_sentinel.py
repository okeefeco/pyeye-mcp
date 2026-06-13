"""Shared leaf module: lightweight module stand-in for Jedi Name objects.

Exists so both :mod:`pyeye.mcp.operations.inspect` and
:mod:`pyeye.mcp.operations.edges` can reference :class:`ModuleSentinel`
WITHOUT either importing the other (``edges`` must not import ``inspect`` —
circular import once ``inspect`` imports ``edges`` for edge-count helpers).

This mirrors the extraction precedent in :mod:`pyeye._ast_targets`, which was
created for the same reason: a shared AST helper needed by both ``inspect``
and ``edges``.

Runtime dependencies: :mod:`ast` and :mod:`pathlib` only.  ``JediAnalyzer``
is imported under ``TYPE_CHECKING`` — it is *not* needed at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class ModuleSentinel:
    """Lightweight stand-in for a Jedi Name when the handle *is* a module.

    Stores the module file path and enough info for ``inspect`` to build the
    location and docstring without a real ``Name`` object.
    """

    def __init__(self, mod_file: Path, handle: str, analyzer: JediAnalyzer) -> None:
        """Initialise the sentinel from the module file and resolved handle.

        Args:
            mod_file: Absolute path to the module's source file.
            handle: Canonical dotted handle for the module (e.g.
                ``"pyeye.cache"``).
            analyzer: The project's ``JediAnalyzer`` instance (stored but not
                called at construction time; kept for future-use parity with
                real Jedi ``Name`` objects).
        """
        self.mod_file = mod_file
        self.handle = handle
        self._analyzer = analyzer

        # Populate Jedi-Name-like attributes from the module file
        self.module_path: Path | None = mod_file
        self.type = "module"
        self.full_name: str = handle
        self.name: str = handle.split(".")[-1]
        self.line: int = 1
        self.column: int = 0

        # Read docstring from module-level AST
        self.docstring_text: str = ""
        try:
            source = mod_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
            ds = ast.get_docstring(tree)
            if ds:
                self.docstring_text = ds
        except Exception:
            pass

    def docstring(self, **kwargs: object) -> str:
        """Return the module-level docstring.

        Args:
            **kwargs: Accepted and ignored for Jedi ``Name.docstring()``
                signature compatibility.

        Returns:
            The module docstring, or an empty string if none was found.
        """
        _ = kwargs  # accepted-and-ignored for Jedi Name.docstring() signature compat
        return self.docstring_text

    def get_signatures(self) -> list:
        """Return an empty list (modules have no call signatures).

        Returns:
            An empty list, matching the Jedi ``Name.get_signatures()`` shape.
        """
        return []

    def infer(self) -> list:
        """Return an empty list (no Jedi inference for module sentinels).

        Returns:
            An empty list, matching the Jedi ``Name.infer()`` shape.
        """
        return []
