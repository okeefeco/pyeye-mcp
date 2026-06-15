"""Real Vehicle hierarchy (issue #335 Bug B — indirect-traversal identity).

Vehicle is the unique base under test.  Car is a direct subclass; RaceCar is
a genuine *indirect* subclass (grandchild) of Vehicle via the real Car.

The simple name ``Car`` is intentionally shared with an unrelated class in
``vehicles_b`` to expose the simple-name conflation in the grandchild walk.
"""


class Vehicle:
    """Unique base class — only Car extends it."""


class Car(Vehicle):
    """Direct subclass of Vehicle (the *real* Car)."""


class RaceCar(Car):
    """Genuine grandchild of Vehicle via the real Car."""
