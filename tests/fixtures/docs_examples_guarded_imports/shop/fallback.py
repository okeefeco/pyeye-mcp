def slow_dumps(obj: object) -> str:
    """The fallback of the shim."""
    return repr(obj)
