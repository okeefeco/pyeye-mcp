"""Widgets: a subclass of a class from another repo."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from corp.core.models import Base

if TYPE_CHECKING:
    from corp.web.views import Page


class Widget(Base):
    """Subclasses corp.core.models.Base across repos."""

    def to_json(self) -> str:
        """Serialise this widget."""
        return json.dumps({"name": self.name})

    def render_on(self, page: Page) -> str:
        """Render onto a page (type-only import)."""
        return page.title + self.describe()


class Shared:
    """Same name as corp.core.models.Shared: a cross-repo name collision."""
