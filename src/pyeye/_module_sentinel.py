"""Shared leaf module: lightweight stand-ins for Jedi Name objects.

Hosts a shared :class:`NameSentinel` base and three thin subclasses:
:class:`ModuleSentinel` (module stand-in), :class:`ClassSentinel` (class
stand-in), and :class:`DefinitionSentinel` (any definition site found by the
pure-AST name index, #457). Factoring the shared Jedi-``Name`` method surface
into one base keeps the interface defined once rather than copy-pasted per kind
(#450).

Exists so that :mod:`pyeye.mcp.operations.inspect`,
:mod:`pyeye.mcp.operations.edges`, and the name-index extractor in
:mod:`pyeye.analyzers.base_resolution` can reference these stand-ins WITHOUT
import cycles (``edges`` must not import ``inspect``; ``base_resolution`` must
stay Jedi-free).

This mirrors the extraction precedent in :mod:`pyeye._ast_targets`, created for
the same reason: a shared AST helper needed by multiple operations.

Runtime dependencies: :mod:`ast` and :mod:`pathlib` only.  ``JediAnalyzer`` is
imported under ``TYPE_CHECKING`` — it is *not* needed at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyeye.analyzers.jedi_analyzer import JediAnalyzer


class NameSentinel:
    """Shared lightweight stand-in for a Jedi ``Name`` built from AST facts.

    Subclasses set the data attributes in their own ``__init__``; this base
    supplies the common Jedi-``Name`` method surface (``docstring`` /
    ``get_signatures`` / ``infer``) so the interface is defined once, not
    copy-pasted per kind (#450). Built from AST-derived facts only — never a
    re-derived Jedi ``Name`` (the determinism pattern, #449).
    """

    # Subclasses populate these in __init__; declared here for the shared surface.
    module_path: Path | None
    type: str
    full_name: str
    name: str
    line: int
    column: int
    # Default docstring; module/definition subclasses set an instance value.
    docstring_text: str = ""

    def docstring(self, **kwargs: object) -> str:
        """Return the stored doc text, or an empty string when none.

        Args:
            **kwargs: Accepted and ignored for Jedi ``Name.docstring()`` compat.

        Returns:
            The docstring text, or ``""``.
        """
        _ = kwargs  # accepted-and-ignored for Jedi Name.docstring() signature compat
        return self.docstring_text

    def get_signatures(self) -> list:
        """Return an empty list (stand-ins carry no call signatures).

        Returns:
            An empty list, matching the Jedi ``Name.get_signatures()`` shape.
        """
        return []

    def infer(self) -> list:
        """Return an empty list (no Jedi inference for stand-ins).

        Returns:
            An empty list, matching the Jedi ``Name.infer()`` shape.
        """
        return []


class ModuleSentinel(NameSentinel):
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

        # Read docstring from module-level AST.  A sentinel may be anchored on a
        # PEP 420 namespace-subpackage DIRECTORY (the submodules edge, #423) — a
        # directory has no module-level docstring AND must never be byte-read
        # (the §3.6 dir-anchored stub contract).  Guard the read on is_file() so
        # a directory anchor yields docstring "" WITHOUT touching the filesystem
        # content; never raises.
        self.docstring_text: str = ""
        try:
            if mod_file.is_file():
                source = mod_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                ds = ast.get_docstring(tree)
                if ds:
                    self.docstring_text = ds
        except Exception:
            pass


class ClassSentinel(NameSentinel):
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


class DefinitionSentinel(NameSentinel):
    """Stand-in for a Jedi ``Name`` at a definition site found by pure-AST scan.

    Produced by :func:`pyeye.analyzers.base_resolution.extract_definitions` for
    every class / function / module-or-class-level statement, replacing the
    truncating ``jedi.Project.search`` in ``_search_all_scopes`` (#457). Carries
    exactly the attributes that method's four callers read, all AST-derived.
    """

    def __init__(
        self,
        module_path: Path | None,
        full_name: str,
        kind: str,
        line: int,
        column: int,
        docstring_text: str = "",
        description: str = "",
    ) -> None:
        """Initialise from the AST-derived facts of one definition site.

        Args:
            module_path: Absolute path to the file declaring the definition.
            full_name: Canonical dotted handle (module name + lexical nesting).
            kind: ``"class"`` / ``"function"`` / ``"statement"`` / ``"module"``
                (stored as ``.type`` for Jedi-``Name`` parity).
            line: 1-indexed line of the name token (Jedi convention).
            column: 0-indexed column of the name token (Jedi convention).
            docstring_text: The definition's docstring, or ``""``.
            description: Short Jedi-``Name``-style description (e.g.
                ``"class Field"``).
        """
        self.module_path: Path | None = module_path
        self.full_name: str = full_name
        self.name: str = full_name.split(".")[-1]
        self.type = kind
        self.line: int = line
        self.column: int = column
        self.docstring_text: str = docstring_text
        self.description: str = description
