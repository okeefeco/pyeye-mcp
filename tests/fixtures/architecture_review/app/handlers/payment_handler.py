"""Payment handler -- PLANT 1 MAJORITY (swallow)."""

from app.core import config
from app.core.database import get_client


def handle_charge(payment_id):
    client = get_client()
    try:
        url = config.retrieve_database_url()
        result = client.query("UPDATE payments SET charged = 1")
        return True
    except Exception:
        # SWALLOW: returns False instead of surfacing the failure.
        return False
