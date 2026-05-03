"""Implementation module for Config — lives at the definition site."""


class Config:
    """Application configuration object."""

    debug: bool = False
    host: str = "localhost"
    port: int = 8080
