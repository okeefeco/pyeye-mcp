"""Definition module — the canonical definition site for the re-exported classes."""


class ForeignObject:
    """Base relation field."""

    base_attr = 1

    def contribute(self) -> int:
        """Contribute to class."""
        return self.base_attr


class ForeignKey(ForeignObject):
    """A foreign-key field."""

    fk_attr = 2

    def get_attname(self) -> str:
        """Return the attribute name."""
        return "fk"


class OneToOneField(ForeignKey):
    """A one-to-one field — re-exported via a grouped import in ``sub/__init__``."""

    o2o_attr = 3

    def method_a(self) -> int:
        """Do thing a."""
        return 1

    def method_b(self) -> int:
        """Do thing b."""
        return 2
