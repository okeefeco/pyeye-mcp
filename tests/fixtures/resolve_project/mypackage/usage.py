"""Usage fixture — provides callers and references counts for Phase 4 edge_counts tests.

This module imports and uses symbols from _core.widgets so that the
inspect edge_counts measurements have non-zero caller/reference counts.

Symbols exercised
-----------------
- ``make_widget``: called twice → callers count >= 2
- ``DEFAULT_NAME``: read once → references count >= 1
- ``Widget.greet``: called twice → callers count >= 2
"""

from mypackage._core.widgets import DEFAULT_NAME, Widget, make_widget


def use_widgets() -> None:
    """Exercise widget symbols to create non-zero caller/reference counts."""
    name = DEFAULT_NAME  # reference to DEFAULT_NAME (read)
    w1 = make_widget(name)  # caller of make_widget (1)
    w2 = make_widget("custom")  # caller of make_widget (2)
    print(w1.greet())  # caller of Widget.greet (1)
    print(w2.greet())  # caller of Widget.greet (2)
    _ = Widget  # additional reference to Widget class
