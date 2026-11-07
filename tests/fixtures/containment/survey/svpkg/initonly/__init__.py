"""Package with ``__init__`` members but NO submodules (the jaraco.context shape)."""


def initonly_fn() -> int:
    """A member of a submodule-less package."""
    return 1
