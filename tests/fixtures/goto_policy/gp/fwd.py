"""``x: Foo`` and ``x: "Foo"`` name the same class (#624; resolved by #623 slice 5)."""


class Foo:
    """The Foo this module means."""


def takes(direct: Foo, quoted: "Foo") -> None:  # noqa: UP037 - the quotes are the point
    """Both parameters are this module's ``Foo``."""
