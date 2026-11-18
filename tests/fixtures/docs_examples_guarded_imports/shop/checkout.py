"""Module-scope imports under guards are followed; a function-local one is not (#984)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shop.orders import Order

try:
    from shop.speedups import fast_dumps as dumps
except ImportError:
    from shop.fallback import slow_dumps as dumps


def summarise(order: "Order") -> str:
    """Builds a report lazily."""
    from shop.reports import Report

    return dumps((order, Report))
