"""Definition site of the base class under test (#405 resolution guard).

``Root`` is subclassed from another module via four reference forms — direct,
aliased, dotted, and re-export — plus one indirect (grandchild) link, so the
``subclasses`` closure exercises every base-resolution path the cold-build
rewrite must preserve byte-for-byte.
"""


class Root:
    """Base whose project subclass closure is pinned by the guard test."""
