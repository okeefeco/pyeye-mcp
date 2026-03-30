"""Enums for the lookup project fixture — tests contextual type resolution."""

from __future__ import annotations

import enum


class Status(enum.Enum):
    """Service status enum."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
