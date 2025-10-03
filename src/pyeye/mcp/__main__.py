"""Entry point for running Pyeye MCP server.

Usage:
    python -m pyeye.mcp
"""

from .server import mcp

if __name__ == "__main__":
    mcp.run()
