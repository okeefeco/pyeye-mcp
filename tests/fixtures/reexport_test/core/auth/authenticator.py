"""Authentication module."""


class Authenticator:
    """Main authenticator class."""

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate a user."""
        # Simple demo implementation
        return bool(username and password)


class TokenValidator:
    """Token validation class."""

    def validate(self, token: str) -> bool:
        """Validate a token."""
        return len(token) > 0
