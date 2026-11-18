#!/usr/bin/env python3
"""Deprecated: the unified metrics store this reported on was removed (#943).

The MCP server no longer records sessions to ``~/.pyeye/metrics/``. For MCP
usage, use the Claude Code hooks in ``scripts/claude_hooks/`` (``mcp-report``,
``mcp-logs``). This script will be deleted with the stub module (#749).
"""

import sys


def main() -> int:
    """Print the deprecation and exit successfully, whatever the arguments."""
    print(
        "scripts/unified_metrics.py is deprecated: the unified metrics store was removed "
        "(#943), so there is nothing to report. For MCP usage, run `mcp-report` "
        "(scripts/claude_hooks/).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
