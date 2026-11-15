"""Views that call into the other two repos."""

import pathlib

import corp.tools.sub.helper as helper_alias
from corp.core.models import Base, make
from corp.tools.widgets import Widget


class Page:
    """A page to render onto."""

    title = "page"


def render(item: Base) -> str:
    """Call into repo A (make) and repo B (Widget)."""
    widget = Widget(make(item.name).name)
    return helper_alias.shout(widget.describe())


def lazy_shout(text: str) -> str:
    """Import lazily, inside the function."""
    from corp.tools.sub import helper

    return helper.shout(text) + pathlib.Path(text).suffix
