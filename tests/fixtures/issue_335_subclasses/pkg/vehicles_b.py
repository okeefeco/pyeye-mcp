"""Unrelated Car hierarchy (issue #335 Bug B — simple-name collision).

This Car is NOT a Vehicle.  SportsCar extends THIS Car.  Neither should ever
appear in the subclass list/count for ``pkg.vehicles_a.Vehicle``; the
grandchild walk must carry FQN identity rather than re-keying on the simple
name ``Car``.
"""


class Car:
    """A completely unrelated Car — shares only the simple name."""


class SportsCar(Car):
    """Child of the UNRELATED Car — must never be counted as a Vehicle subclass."""
