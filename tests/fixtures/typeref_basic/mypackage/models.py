"""Project-internal class referenced by TypeRef-test annotations.

A leaf inside a generic annotation (``Dict[str, List[CustomModel]]``) must
resolve to ``mypackage.models.CustomModel`` — proving the recursive resolver
threads project context per-leaf, not just at the head.
"""


class CustomModel:
    """Project-local model used as a generic argument in scenario fixtures."""
