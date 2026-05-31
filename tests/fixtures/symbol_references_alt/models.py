"""Alternate project models — for project_path forwarding tests."""


class AltModel:
    """A model that only exists in the alternate fixture project."""

    def __init__(self, value: int = 0) -> None:
        self.value = value

    def double(self) -> int:
        """Return double the value."""
        return self.value * 2


instance = AltModel(value=42)
result = instance.double()
