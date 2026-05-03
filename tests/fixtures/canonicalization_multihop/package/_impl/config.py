"""Implementation module for Config — this is the definition site.

Canonical handle: package._impl.config.Config
"""


class Config:
    """Application configuration object — defined here, re-exported elsewhere."""

    debug: bool = False
    host: str = "localhost"
    port: int = 8080
