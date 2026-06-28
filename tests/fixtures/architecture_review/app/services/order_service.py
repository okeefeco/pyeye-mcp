"""Order service -- PLANT 5 cluster B: returns a @dataclass result-shape."""

from dataclasses import dataclass

from app.core import config
from app.handlers import order_handler


@dataclass
class OrderResult:
    ok: bool
    data: dict
    error: str | None = None


def load_order(order_id):
    order = order_handler.handle_get_order(order_id)
    # Result-shape: dataclass instance -- same concept as user_service's dict.
    return OrderResult(ok=bool(order), data=order)
