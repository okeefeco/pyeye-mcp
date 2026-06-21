"""Shared leaf module: lightweight stand-ins for Jedi Name objects.

Hosts :class:`ModuleSentinel` (module stand-in) and :class:`ClassSentinel`
(class stand-in). Exists so both :mod:`pyeye.mcp.operations.inspect` and
:mod:`pyeye.mcp.operations.edges` can reference them WITHOUT either importing
the other (``edges`` must not import ``inspect`` — circular import once
``inspect`` imports ``edges`` for edge-count helpers).

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


class ClassSentinel:
    """Lightweight stand-in for a Jedi Name when the handle *is* a class.

    Built from the AST-derived facts ``find_subclasses`` already returns
    (``full_name`` + file + line span) so the ``subclasses`` edge never has to
    re-derive a Jedi ``Name`` per subclass — a re-derivation whose
    ``full_name`` match is warm-state-dependent and silently dropped ~half the
    results across cache rebuilds (#445). Mirrors :class:`ModuleSentinel`.

    Exposes exactly what its two consumers read: the stub builder
    (``type`` / ``module_path`` / ``line`` / ``end_line`` / ``get_signatures``)
    AND ``resolve_subclasses`` itself, which receives this object as its input
    at hop 2+ of ``trace(follow=["subclasses"])`` and reads ``type`` /
    ``full_name`` to recurse — so the sentinel must round-trip as a resolver
    input, not merely as a stub source.
    """

    def __init__(
        self,
        class_file: Path,
        handle: str,
        line: int,
        end_line: int,
        column: int = 0,
    ) -> None:
        """Initialise the sentinel from the subclass's AST-derived facts.

        Args:
            class_file: Absolute path to the file declaring the class.
            handle: Canonical dotted handle for the class (its AST ``full_name``).
            line: 1-indexed start line of the ``class`` statement.
            end_line: 1-indexed end line of the class body (``ClassDef.end_lineno``).
            column: 0-indexed start column (carried for Name parity; default 0).
        """
        self.module_path: Path | None = class_file
        self.type = "class"
        self.full_name: str = handle
        self.name: str = handle.split(".")[-1]
        self.line: int = line
        self.end_line: int = end_line
        self.column: int = column

    def docstring(self, **kwargs: object) -> str:
        """Return an empty string (pointer-only; the body is the inspect layer).

        Args:
            **kwargs: Accepted and ignored for Jedi ``Name.docstring()`` compat.

        Returns:
            An empty string — a subclass stub carries no docstring (drill with
            ``inspect`` for that).
        """
        _ = kwargs
        return ""

    def get_signatures(self) -> list:
        """Return an empty list (a stub is a pointer, not a signature).

        Returns:
            An empty list, matching the Jedi ``Name.get_signatures()`` shape.
            The constructor signature is an ``inspect`` detail, not a one-hop
            ``expand`` stub field (#445).
        """
        return []

    def infer(self) -> list:
        """Return an empty list (no Jedi inference for class sentinels).

        Returns:
            An empty list, matching the Jedi ``Name.infer()`` shape.
        """
        return []
