"""Python Code Intelligence MCP Server.

An extensible MCP server for Python code analysis and navigation.
"""

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    # Package not installed in development mode
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "+unknown", "")

from .server import mcp

__all__ = ["mcp", "__version__"]
