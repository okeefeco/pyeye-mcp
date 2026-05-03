"""Implementation module for Config — lives at the definition site."""


class Config:
    """Application configuration object."""

    debug: bool = False
    host: str = "localhost"
    port: int = 8080


class _PrivateConfig:
    """Not re-exported from package/__init__.py — used to test empty re-exports."""

    pass
