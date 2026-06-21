"""Regular package fixture for the ``submodules`` containment edge (#423).

Re-exports ``A`` from the ``alpha`` submodule so that the package handle and a
member name coexist (exercising the package-vs-module distinction).
"""

from .alpha import A

__all__ = ["A"]
