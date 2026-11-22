"""Scope facts: the scope grammar and the plugin-tool default policy (#827).

Read from :data:`pyeye.scope_utils.SCOPE_FORMS`, the one list of scope forms
:func:`pyeye.scope_utils.resolve_scope_paths` implements, and from
:data:`pyeye.scope_utils.PLUGIN_FALLBACK_SCOPE`. Each plugin tool's effective
default is its ``scope`` parameter fact (``tool.<name>.param.scope``, from the
``mcp_surface`` extractor); this extractor owns only the policy.

It imports nothing from pyeye: it reads the source (#1098, C19). The server's
tool descriptions render the same facts from the live constants through
:func:`scope_facts` (:func:`pyeye.docs_facts.describe.live_facts`).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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
    return scope_facts([(n, s, m) for n, s, m in forms], fallback)


def scope_facts(scope_forms: list[tuple[str, str, str]], fallback: str) -> Iterator[Bindable]:
    """The scope facts from ``(name, syntax, meaning)`` forms and the plugin fallback.

    ``extract`` passes what it reads from the source; the server's tool
    descriptions pass the imported constants (:func:`..describe.live_facts`, #1098 Q1).
    """
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
