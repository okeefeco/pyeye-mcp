"""Package init that RE-EXPORTS ``Root`` from ``pkg.core`` (#405 guard).

This makes ``pkg.Root`` a valid importable path resolving to the definition
site ``pkg.core.Root`` — the re-export resolution path under test.
"""

from pkg.core import Root

__all__ = ["Root"]
