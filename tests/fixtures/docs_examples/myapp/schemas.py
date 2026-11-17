"""Request schemas."""

from pydantic import BaseModel, field_validator


class User(BaseModel):
    """A user as the API accepts it."""

    name: str
    email: str

    @field_validator("email")
    @classmethod
    def email_has_at(cls, value: str) -> str:
        """Reject an address without an @."""
        if "@" not in value:
            raise ValueError("not an email address")
        return value
