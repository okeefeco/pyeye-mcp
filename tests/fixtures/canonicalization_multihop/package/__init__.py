"""Public package surface — re-exports Config via the subpkg intermediary.

This is hop 2 of the re-export chain:
  package._impl.config.Config  (definition)
    -> package.subpkg.Config   (hop 1)
    -> package.Config           (hop 2)

Both package.Config and package.subpkg.Config should appear in the
re-export list for the canonical handle package._impl.config.Config.
"""

from package.subpkg import Config

__all__ = ["Config"]
