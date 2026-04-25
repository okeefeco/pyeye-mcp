"""Module B config — defines a different Config class for disambiguation testing."""


class Config:
    """Configuration for module B (database settings)."""

    def __init__(self, dsn: str = "sqlite:///:memory:") -> None:
        self.dsn = dsn

    def is_valid(self) -> bool:
        """Return True if the DSN looks valid."""
        return bool(self.dsn)


DB_CONFIG = Config()
