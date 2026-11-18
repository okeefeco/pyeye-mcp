"""Uses the stub-only module, so the edges emit its handles (#933)."""

from pkg.stubonly import S, f


def use() -> S:
    return f(1)
