"""Conformance guard for the static-surface ceiling caveat (#417).

pyeye's static structural edges (``members`` / ``outline`` / ``subclasses``) are
deterministic and complete over the *static surface* — what is literally written
in source — but Python's runtime-dynamic features (metaclass injection,
``setattr``, ``__getattr__``, ``type(...)``, ``__init_subclass__``) put real
relationships outside that surface.  ``imported_by`` already documents its
analogous ceiling; #417 is the consistency gap that the other static edges did
not.

This test converts that honesty contract from prose-that-can-rot into a CI
failure: every surface that presents a static structural edge MUST carry the
ceiling marker.  Mirrors the anti-drift posture of
``test_python_explore_skill_conformance`` (#374).

Dependency-free: stdlib ``ast`` + ``re`` + ``pathlib`` only.
"""

import ast
import re
from pathlib import Path

from pyeye.mcp.operations.edges import resolve_members, resolve_subclasses
from pyeye.mcp.operations.outline import outline as outline_operation

# The single canonical phrase every static-edge surface must carry.  Anchoring on
# one exact substring is what makes the contract mechanically checkable (and what
# stops a future edit from silently dropping it from one surface).
MARKER = "Static-surface ceiling"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SERVER = _REPO_ROOT / "src" / "pyeye" / "mcp" / "server.py"
_SKILL = _REPO_ROOT / "skills" / "python-explore" / "SKILL.md"


def _tool_docstring(func_name: str) -> str:
    """Return the docstring of a top-level ``async def`` in server.py via AST.

    Reading the docstring out of the source (rather than importing the decorated
    object) is robust to the ``@mcp.tool()`` decorator stack, which may wrap the
    function in a registration object that does not forward ``__doc__``.
    """
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == func_name:
            doc = ast.get_docstring(node)
            assert doc is not None, f"{func_name} in server.py has no docstring"
            return doc
    raise AssertionError(f"no top-level def named {func_name!r} in {_SERVER.as_posix()}")


# ---------------------------------------------------------------------------
# MCP tool docstrings — the JSON-consumer-facing surface.
# ---------------------------------------------------------------------------


def test_expand_docstring_carries_ceiling_for_members_and_subclasses() -> None:
    doc = _tool_docstring("expand")
    # The marker must appear for BOTH static structural edges, not just once.
    assert doc.count(MARKER) >= 2, (
        "expand() must carry the static-surface ceiling caveat for both the "
        "members and subclasses edges"
    )


def test_outline_tool_docstring_carries_ceiling() -> None:
    assert MARKER in _tool_docstring("outline")


# ---------------------------------------------------------------------------
# Operation-level docstrings — the internal contract (#417 cites these sites).
# ---------------------------------------------------------------------------


def test_resolve_members_docstring_carries_ceiling() -> None:
    assert resolve_members.__doc__ is not None and MARKER in resolve_members.__doc__


def test_resolve_subclasses_docstring_carries_ceiling() -> None:
    assert resolve_subclasses.__doc__ is not None and MARKER in resolve_subclasses.__doc__


def test_outline_operation_docstring_carries_ceiling() -> None:
    assert outline_operation.__doc__ is not None and MARKER in outline_operation.__doc__


# ---------------------------------------------------------------------------
# Shipped skill — single source of truth for tool mechanics (CLAUDE.md / #374).
# ---------------------------------------------------------------------------


def test_skill_documents_static_surface_ceiling() -> None:
    text = _SKILL.read_text(encoding="utf-8")
    assert MARKER in text, (
        "the python-explore skill must document the static-surface ceiling so the "
        "honesty contract stays consistent with the tool docstrings"
    )


def test_marker_phrasing_is_stable() -> None:
    # Guards the exact wording the other tests anchor on; a drift here is a signal
    # to update every surface deliberately, not silently.
    assert re.fullmatch(r"Static-surface ceiling", MARKER)
