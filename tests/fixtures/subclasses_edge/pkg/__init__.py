"""Package init for the subclasses-edge fixture (issue #348).

Exposes nothing — the fixture's classes are addressed by their definition-site
FQNs (``pkg.base.Animal`` etc.) so the ``subclasses`` expand resolver can be
exercised against a known direct + indirect + non-importable-file topology.
"""
