"""User service -- PLANT 5 cluster A: returns a plain dict result-shape."""

from app.core import config
from app.handlers import user_handler


def load_user(user_id):
    user = user_handler.handle_get_user(user_id)
    # Result-shape: plain dict.
    return {"ok": user is not None, "data": user, "error": None}


def load_all_users():
    users = user_handler.handle_list_users()
    return {"ok": True, "data": users, "error": None}
