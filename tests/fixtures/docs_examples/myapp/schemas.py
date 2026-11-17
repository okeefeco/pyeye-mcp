"""Request schemas."""

from pydantic import BaseModel, ConfigDict, computed_field, field_validator


class User(BaseModel):
    """A user as the API accepts it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    email: str

    @field_validator("email")
    @classmethod
    def email_has_at(cls, value: str) -> str:
        """Reject an address without an @."""
        if "@" not in value:
            raise ValueError("not an email address")
        return value

    @computed_field
    @property
    def domain(self) -> str:
        """The part of the address after the @."""
        return self.email.split("@", 1)[1]
