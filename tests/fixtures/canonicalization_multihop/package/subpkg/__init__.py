"""Intermediate sub-package — hop 1 of the re-export chain.

Re-exports Config from the private implementation module.
This creates the re-export path: package.subpkg.Config

Jedi's full_name for Config here will resolve to:
  package._impl.config.Config  (the definition site)

Note: package/subpkg/ is NOT an ancestor directory of the definition site
(package/_impl/config.py), so the old single-hop parent-walker could not
discover this path. Task 1.3 adds a full-tree scan using Jedi's full_name
to find all re-export paths.
"""

from package._impl.config import Config

__all__ = ["Config"]
