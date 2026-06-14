"""Package init for the superclasses-edge fixture (issue #361).

Exposes nothing — the fixture's classes are addressed by their definition-site
FQNs (``pkg.bases.Base``, ``pkg.derived.Child`` etc.) so the ``superclasses``
expand resolver can be exercised against a known topology.
"""
