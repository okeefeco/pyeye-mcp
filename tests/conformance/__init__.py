"""Conformance linter for PyEye resolve/resolve_at/inspect operation responses.

Enforces the two core invariants:
- Layering principle: no source content in responses
- Absence-vs-zero: edge_counts values and keys are strictly typed
"""
