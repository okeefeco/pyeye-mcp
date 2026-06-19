"""Subclass whose aliased base is imported under try/except (#420 review #1).

The base ``Root`` is imported with ``as`` **inside a try/except** — so it is NOT
a top-level import that ``build_import_table`` can see. ``resolve_base`` therefore
punts, and the Jedi ``goto`` fallback must still resolve it to ``Root``'s
definition site. Regression guard for the FQN-path aliased-base drop (the
fallback gated on ``gr.name == alias`` instead of taking the resolved target).
"""

try:
    from pkg.core import Root as AliasedRoot
except ImportError:  # pragma: no cover
    from pkg.core import Root as AliasedRoot


class ConditionalAlias(AliasedRoot):
    """Subclass via a non-top-level (try/except) aliased base."""
