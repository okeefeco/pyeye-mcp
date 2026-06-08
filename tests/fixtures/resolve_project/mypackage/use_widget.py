"""Use-site fixture for resolve_at use-site test (case e).

Contains a usage of Widget (imported from the package) so that
pointing resolve_at at the use site still returns the canonical handle.
"""

from mypackage import Widget

# Use site: pointing at 'Widget' on the line below (line 11) should
# resolve to the canonical handle mypackage._core.widgets.Widget
w = Widget()
