"""Call sites and imports whose goto has more than one target (#624)."""

from gp import VALUE, helper


def union_receiver(data: bytes | str) -> bool:
    """``endswith`` on a ``bytes | str`` receiver: two distinct targets."""
    return data.endswith(data[:1])


def fallback_call() -> int:
    """``helper`` is bound by a try/except fallback: two distinct targets."""
    return helper() + VALUE


def unique_call() -> int:
    """``len`` has exactly one target: always resolved."""
    return len("x")
