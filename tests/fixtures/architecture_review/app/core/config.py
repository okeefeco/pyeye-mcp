"""HUB module: configuration accessors.

PLANT 3 (naming_api_shape, LOW stakes / HIGH blast): the same kind of
read-only config accessor is spelled three different ways here -- get_*,
fetch_*, retrieve_* -- a cosmetic naming inconsistency. This module is the
HUB: it is imported by nearly every handler and service, so the blast radius
is high, but the divergence itself is purely cosmetic.
"""

_SETTINGS = {
    "timeout": 30,
    "database_url": "sqlite:///app.db",
    "retries": 3,
    "feature_flag": True,
}


def get_setting(name):
    # accessor spelling #1: get_*
    return _SETTINGS.get(name)


def fetch_timeout():
    # accessor spelling #2: fetch_* -- same conceptual operation as get_setting
    return _SETTINGS.get("timeout")


def retrieve_database_url():
    # accessor spelling #3: retrieve_* -- same conceptual operation again
    return _SETTINGS.get("database_url")


def get_retries():
    # back to get_* -- inconsistent with the two above
    return _SETTINGS.get("retries")
