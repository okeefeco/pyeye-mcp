"""Legacy compatibility module — re-exports Config under the old name.

This creates an aliased re-export path: package.legacy.LegacyConfig

Jedi's full_name for LegacyConfig here will resolve to:
  package._impl.config.Config  (the definition site, following the alias)
"""

from package import Config as LegacyConfig

__all__ = ["LegacyConfig"]
