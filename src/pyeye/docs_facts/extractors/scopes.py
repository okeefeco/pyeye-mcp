"""Scope facts: the scope grammar and the plugin-tool default policy (#827).

Read from :data:`pyeye.scope_utils.SCOPE_FORMS`, the one list of scope forms
:func:`pyeye.scope_utils.resolve_scope_paths` implements, and from
:data:`pyeye.scope_utils.PLUGIN_FALLBACK_SCOPE`. Each plugin tool's effective
default is its ``scope`` parameter fact (``tool.<name>.param.scope``, from the
``mcp_surface`` extractor); this extractor owns only the policy.

It imports nothing from :mod:`pyeye.mcp.server`, so tool descriptions can be
filled from it while the server module loads (:mod:`pyeye.docs_facts.describe`).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ...scope_utils import PLUGIN_FALLBACK_SCOPE, SCOPE_FORMS
from ..facts import Bindable, Fact, code, code_list, table, text, view

PREFIXES = ("scope", "scopes")

#: Where a plugin tool's default scope comes from, first match wins (#559).
DEFAULT_ORDER = ("scope_defaults.methods.<tool name>", "scope_defaults.global")


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - reads the live constants
    """Yield a fact per scope form and for the default policy, plus the views."""
    forms = [
        Fact(
            f"scope.option.{form.name}",
            {"syntax": form.syntax, "meaning": form.meaning},
            f"{code(form.syntax)}: {text(form.meaning)}",
        )
        for form in SCOPE_FORMS
    ]
    yield from forms
    yield view("scopes.options", forms, code_list(f.value["syntax"] for f in forms))
    yield view(
        "scopes.table",
        forms,
        table(
            ["Scope", "Searches"],
            [[code(f.value["syntax"]), text(f.value["meaning"])] for f in forms],
        ),
    )

    order = [*DEFAULT_ORDER, PLUGIN_FALLBACK_SCOPE]
    yield Fact(
        "scope.default.plugin",
        {"order": list(DEFAULT_ORDER), "fallback": PLUGIN_FALLBACK_SCOPE},
        ", else ".join(code(step) for step in order),
    )
