"""A name bound two ways by an if/else: a class, or another value (#1057).

The condition is decided at runtime, so static analysis sees both bindings
(``sys.version_info`` would not do: Jedi evaluates it and drops a branch).
"""

import os

if os.environ.get("PYEYE_FIXTURE_FLAG"):

    class Cursor:
        """The if-branch class."""

else:
    Cursor = object
