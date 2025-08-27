"""Python Code Intelligence MCP Server.

An extensible MCP server for Python code analysis and navigation.
"""

# Version handling: setuptools_scm generates different tuple formats
# - Release versions (e.g., 0.3.0): 3-tuple (major, minor, patch)
# - Dev versions (e.g., 0.3.1.dev1+...): 5-tuple (major, minor, patch, 'devN', 'ghash')
# We explicitly support both formats with proper typing

__version__: str
__version_tuple__: tuple[int, int, int] | tuple[int, int, int, str, str]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    # Package not installed or _version.py not generated yet
    # Use 3-tuple for consistency with release format
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0)

from .server import mcp

__all__ = ["mcp", "__version__"]
