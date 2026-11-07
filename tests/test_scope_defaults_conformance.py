"""Conformance: SMART_DEFAULTS must not name methods that no longer exist.

``SmartScopeResolver.SMART_DEFAULTS`` is a per-method scope table.  A key for a
removed method is silently dead config — it never fires, but it reads to a
maintainer as a live capability, which is exactly the drift that let entries for
``find_references`` / ``get_call_hierarchy`` / ``analyze_dependencies`` /
``get_module_info`` / ``list_project_structure`` outlive the methods themselves
(#505).

**What this does NOT guarantee.** It checks *existence*, not *liveness*: a key
naming a real-but-uncalled method (e.g. ``find_imports``, orphaned when
``lookup_builders`` was removed) still passes.  These keys are internal: they
are only consulted by ``JediAnalyzer.get_project_files(method_name=...)``, which
no 2.x tool reaches with ``scope=None``.  The user-facing defaults are the plugin
tools', which resolve by MCP tool name through
``SmartScopeResolver.plugin_tool_default`` and are not listed here (#559).
"""

import pytest

from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.scope_utils import SmartScopeResolver

_ANALYZER_KEYS = sorted(SmartScopeResolver.SMART_DEFAULTS)


class TestSmartDefaultsConformance:
    @pytest.mark.parametrize("method_name", _ANALYZER_KEYS)
    def test_key_names_a_real_analyzer_method(self, method_name: str) -> None:
        """No SMART_DEFAULTS key may reference a method that has been removed."""
        assert hasattr(JediAnalyzer, method_name), (
            f"SMART_DEFAULTS names '{method_name}', which is not a JediAnalyzer "
            "method. Remove the dead key, or fix the method name."
        )

    def test_removed_legacy_tools_are_absent(self) -> None:
        """Regression for #505 — the removed legacy tools must not reappear."""
        removed = {
            "find_references",
            "get_call_hierarchy",
            "analyze_dependencies",
            "get_module_info",
            "list_project_structure",
        }
        present = removed & set(SmartScopeResolver.SMART_DEFAULTS)

        assert not present, f"Removed legacy tools present in SMART_DEFAULTS: {sorted(present)}"
