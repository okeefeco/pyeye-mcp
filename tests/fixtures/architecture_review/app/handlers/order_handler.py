"""Order handler -- PLANT 1 MAJORITY (swallow)."""

from app.core import config
from app.core.database import DB


def handle_get_order(order_id):
    try:
        retries = config.get_retries()
        rows = DB.query("SELECT * FROM orders WHERE id = ?")
        return rows[0]
    except Exception:
        # SWALLOW: swallows everything, returns a sentinel default.
        return {}
