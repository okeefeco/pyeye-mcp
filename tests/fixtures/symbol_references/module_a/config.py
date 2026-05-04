"""Module A config — defines a Config class for disambiguation testing."""


class Config:
    """Configuration for module A."""

    def __init__(self, host: str = "localhost", port: int = 8080) -> None:
        self.host = host
        self.port = port

    def get_url(self) -> str:
        """Return the full URL."""
        return f"http://{self.host}:{self.port}"


DEFAULT_CONFIG = Config()
