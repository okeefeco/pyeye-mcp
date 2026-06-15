"""Unique-name multi-level hierarchy (issue #335 macOS-regression guard).

Every class here has a simple name that is unique within the project, so the
subclass relationships are unambiguous from the AST alone.  Resolving them must
NOT depend on Jedi goto()/canonicalisation — that machinery is fragile on
symlinked temp dirs (macOS ``/var`` -> ``/private/var``) where it silently
returns degraded results.  The regression test patches the Jedi layer to fail
and asserts the whole chain is still discovered via the path-independent AST
fast path.
"""


class Root:
    """Top of a unique-name inheritance chain."""


class Mid(Root):
    """Direct subclass of Root."""


class Leaf(Mid):
    """Indirect (grandchild) subclass of Root via Mid."""
