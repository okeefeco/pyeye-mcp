"""Which un-annotated v1 attributes are fields, and a nested ``class Config`` (#984)."""

from pydantic.v1 import BaseModel


def default_name() -> str:
    """A function: assigning it to an attribute makes no field."""
    return "anon"


class Account(BaseModel):
    """A v1 model: un-annotated attributes can be fields."""

    name: str
    retries = 3
    make_name = default_name
    label = lambda self: self.name  # noqa: E731 - v1 ignores a lambda

    @property
    def shout(self) -> str:
        """A property: not a field."""
        return self.name.upper()

    class Config:
        """Read like model_config."""

        extra = "forbid"
        frozen = True
