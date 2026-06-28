"""User handler -- PLANT 1 MAJORITY (swallow). Wrong pattern, but common.

Acquires its db via the module-global singleton (also feeds PLANT 4).
"""

from app.core import config
from app.core.database import DB


def handle_get_user(user_id):
    try:
        timeout = config.fetch_timeout()
        rows = DB.query("SELECT * FROM users WHERE id = ?")
        return rows[0]
    except Exception:
        # SWALLOW: returns None on any failure, hiding the error.
        return None


def handle_list_users():
    try:
        return DB.query("SELECT * FROM users")
    except:
        # SWALLOW: bare except, returns empty default.
        return []
