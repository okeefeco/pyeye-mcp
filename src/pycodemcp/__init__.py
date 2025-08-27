"""Python Code Intelligence MCP Server.

An extensible MCP server for Python code analysis and navigation.
"""

try:
    from ._version import __version__, __version_tuple__

    # Type annotation to handle both release and dev version tuples
    # setuptools_scm generates 3-tuple for releases, 5-tuple for dev versions
    __version_tuple__: tuple[int, int, int] | tuple[int, int, int, str, str] = __version_tuple__
except ImportError:
    # Package not installed or _version.py not generated yet
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "unknown", "")

from .server import mcp

__all__ = ["mcp", "__version__"]
