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
from .. import static
from ..facts import Bindable, Fact, code, code_list, table, text, view

PREFIXES = ("scope", "scopes")

#: Where a plugin tool's default scope comes from, first match wins (#559).
DEFAULT_ORDER = ("scope_defaults.methods.<tool name>", "scope_defaults.global")


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per scope form and for the default policy, plus the views.

    The ``ScopeForm(name, syntax, meaning)`` calls and the fallback are read
    from the source, never imported (#1098, C19).
    """
    forms = static.call_args(root, "pyeye.scope_utils", "SCOPE_FORMS", 3)
    fallback = static.constant(root, "pyeye.scope_utils", "PLUGIN_FALLBACK_SCOPE")
    return _facts([(n, s, m) for n, s, m in forms], fallback)


def _extract_imported(_root: Path) -> Iterator[Bindable]:
    """The live path the server's descriptions read, until #1098 Q1 decides."""
    return extract_code()


def extract_code() -> Iterator[Bindable]:
    """The scope facts, from the installed code alone; reads no file (#851).

    The server fills its tool descriptions from these while it loads
    (:mod:`pyeye.docs_facts.describe`); whether that stays live or reads the
    installed source too is #1098's Q1.
    """
    return _facts([(f.name, f.syntax, f.meaning) for f in SCOPE_FORMS], PLUGIN_FALLBACK_SCOPE)


def _facts(scope_forms: list[tuple[str, str, str]], fallback: str) -> Iterator[Bindable]:
    forms = [
        Fact(
            f"scope.option.{name}",
            {"syntax": syntax, "meaning": meaning},
            f"{code(syntax)}: {text(meaning)}",
        )
        for name, syntax, meaning in scope_forms
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

    order = [*DEFAULT_ORDER, fallback]
    yield Fact(
        "scope.default.plugin",
        {"order": list(DEFAULT_ORDER), "fallback": fallback},
        ", else ".join(code(step) for step in order),
    )
