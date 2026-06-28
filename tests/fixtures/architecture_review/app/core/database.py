"""Database access.

PLANT 4 (dependency_acquisition): this module exposes its dependency as a
MODULE-GLOBAL SINGLETON. `DB` is constructed at import time and functions
mutate/read the global `_client`. Several handlers reach for this global
directly instead of receiving a connection by injection. Contrast with
app/services/report_service.py, which takes its db by parameter injection.
"""

from app.core import config


class Database:
    def __init__(self, url=None):
        self.url = url or config.retrieve_database_url()
        self.connected = False

    def connect(self):
        self.connected = True
        return self

    def query(self, sql):
        return []


# Module-global singleton: constructed at import time.
DB = Database().connect()

# Mutable module-global client handle.
_client = None


def get_client():
    global _client
    if _client is None:
        _client = Database().connect()
    return _client


def reset_client():
    global _client
    _client = None
