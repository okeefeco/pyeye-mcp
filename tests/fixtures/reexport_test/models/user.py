"""User model definition."""


class User:
    """A user class for testing re-exports."""

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def get_display_name(self) -> str:
        """Get display name."""
        return self.name


class UserProfile:
    """User profile class."""

    def __init__(self, user: User, bio: str):
        self.user = user
        self.bio = bio


def create_user(name: str, email: str) -> User:
    """Factory function to create a user."""
    return User(name, email)
