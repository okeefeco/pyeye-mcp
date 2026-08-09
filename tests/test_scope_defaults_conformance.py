"""Conformance: SMART_DEFAULTS must not name methods that no longer exist.

``SmartScopeResolver.SMART_DEFAULTS`` is a per-method scope table.  A key for a
removed method is silently dead config — it never fires, but it reads to a
maintainer as a live capability, which is exactly the drift that let entries for
``find_references`` / ``get_call_hierarchy`` / ``analyze_dependencies`` /
``get_module_info`` / ``list_project_structure`` outlive the methods themselves
(#505).

This guards the analyzer half of the table.  Plugin-provided keys (``find_routes``,
``find_models``, …) are resolved dynamically from whichever plugins activate for a
project, so they are excluded rather than asserted against a static list.
"""

import ast
from pathlib import Path

from pyeye.scope_utils import SmartScopeResolver

_ANALYZER_SOURCE = Path(__file__).parent.parent / "src" / "pyeye" / "analyzers" / "jedi_analyzer.py"

# Keys supplied by framework plugins rather than JediAnalyzer.  These are
# registered at plugin-activation time, so they cannot be checked statically.
_PLUGIN_PROVIDED = {
    "find_routes",
    "find_models",
    "find_views",
    "find_blueprints",
    "find_templates",
    "find_validators",
    "find_field_validators",
    "find_model_config",
    "find_computed_fields",
    "find_extensions",
    "find_config",
    "find_error_handlers",
    "find_cli_commands",
}


def _analyzer_method_names() -> set[str]:
    """Every method defined on any class in jedi_analyzer.py."""
    tree = ast.parse(_ANALYZER_SOURCE.read_text(encoding="utf-8"))
    return {
        member.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


class TestSmartDefaultsConformance:
    def test_every_key_names_a_real_analyzer_method(self) -> None:
        """No SMART_DEFAULTS key may reference a method that has been removed."""
        analyzer_methods = _analyzer_method_names()
        checked = set(SmartScopeResolver.SMART_DEFAULTS) - _PLUGIN_PROVIDED

        stale = sorted(name for name in checked if name not in analyzer_methods)

        assert not stale, (
            "SMART_DEFAULTS names methods that do not exist on JediAnalyzer: "
            f"{stale}. Remove the dead keys, or fix the method name."
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
