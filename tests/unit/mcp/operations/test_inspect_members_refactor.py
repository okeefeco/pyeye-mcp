"""Phase 5 (Task 5.1) — pin the post-refactor module member count.

After routing inspect's member counting through edges.resolve_members, module
member counts EXCLUDE import-bound names (spec §3.3).  This file pins the
exact count for mypackage._core.widgets so any future regression is caught
immediately.

mypackage._core.widgets top-level members:
  - Imports:  ClassVar  (from typing import ClassVar)  → EXCLUDED post-refactor
  - Members:  DEFAULT_NAME, Widget, Config, make_widget, Premium, Deluxe → 6

Old (pre-refactor) count: 7  (Jedi counted ClassVar as a top-level name)
New (post-refactor) count: 6  (import-bound names excluded)

Class counts are UNCHANGED: Widget still has >= 5 direct members.
"""

from pathlib import Path

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer

_FIXTURE = Path(__file__).parent.parent.parent.parent / "fixtures" / "resolve_project"

_MODULE_HANDLE = "mypackage._core.widgets"
_WIDGET_HANDLE = "mypackage._core.widgets.Widget"


@pytest.fixture
def analyzer() -> JediAnalyzer:
    """JediAnalyzer pointed at the resolve_project fixture."""
    return JediAnalyzer(str(_FIXTURE))


class TestModuleMemberCountExcludesImports:
    """Pins the exact post-refactor module member count for mypackage._core.widgets."""

    @pytest.mark.asyncio
    async def test_module_member_count_excludes_imports(self, analyzer: JediAnalyzer) -> None:
        """After routing through edges.resolve_members, module count excludes imports.

        widgets.py has exactly 6 non-import top-level definitions:
          DEFAULT_NAME, Widget, Config, make_widget, Premium, Deluxe.

        ClassVar (from 'from typing import ClassVar') is import-bound and must
        NOT be counted.  The old flat Jedi get_names() count was 7; the new
        resolve_members-based count is 6.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_MODULE_HANDLE, analyzer)

        assert "members" in result["edge_counts"], (
            f"Module handle must have edge_counts['members']; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        assert result["edge_counts"]["members"] == 6, (
            f"widgets.py defines exactly 6 top-level members (ClassVar excluded as import); "
            f"got members={result['edge_counts']['members']}.  "
            f"If this is 7, the refactor to exclude imports has not landed yet."
        )

    @pytest.mark.asyncio
    async def test_class_member_count_unchanged(self, analyzer: JediAnalyzer) -> None:
        """Class member counts are unaffected by the import-exclusion refactor.

        Widget has color, name, visible, __init__, greet, slow_greet,
        display_name, default, normalize — at least 5 direct members.
        Class members are enumerated by prefix+exact-depth filtering (no import
        exclusion needed there), so the count should be identical pre/post refactor.
        """
        from pyeye.mcp.operations.inspect import inspect

        result = await inspect(_WIDGET_HANDLE, analyzer)

        assert "members" in result["edge_counts"], (
            f"Class handle must have edge_counts['members']; "
            f"got edge_counts={result['edge_counts']!r}"
        )
        assert result["edge_counts"]["members"] >= 5, (
            f"Widget has >= 5 direct members; " f"got members={result['edge_counts']['members']}"
        )
