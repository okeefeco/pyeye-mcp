"""Project-internal class referenced by TypeRef conformance annotations.

A leaf inside ``Dict[str, List[CustomModel]]`` (or its PEP 585 equivalent)
must canonicalize to ``models.CustomModel`` — the project's definition
site. This proves the recursive TypeRef resolver carries project context
all the way to the leaves, not just at the head of each generic.
"""


class CustomModel:
    """Project-local model used as a generic argument in compound annotations."""
