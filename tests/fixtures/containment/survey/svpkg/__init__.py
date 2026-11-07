"""Survey-mode fixture root (#596): a package whose ``__init__`` defines members."""


def init_fn() -> int:
    """A member defined in the package ``__init__`` (not a submodule)."""
    return 1
