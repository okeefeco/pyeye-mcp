"""The names Claude Code gives pyeye's MCP tools, for the monitoring hooks (#965).

A server added with ``claude mcp add`` names its tools ``mcp__pyeye__<tool>``.
The Claude Code plugin names them ``mcp__plugin_pyeye_pyeye__<tool>``. The hooks
must count both, or a plugin install records no MCP calls at all.
"""

#: Every prefix a pyeye tool name can have, longest first.
PYEYE_TOOL_PREFIXES = ("mcp__plugin_pyeye_pyeye__", "mcp__pyeye__")

#: The hook ``matcher`` (a regex) for every pyeye tool, in either install form.
HOOK_MATCHER = "mcp__pyeye__.*|mcp__plugin_pyeye_pyeye__.*"


def short_name(tool_name: str) -> str:
    """The pyeye tool's own name (``resolve``), or *tool_name* unchanged if it isn't pyeye's."""
    for prefix in PYEYE_TOOL_PREFIXES:
        if tool_name.startswith(prefix):
            return tool_name[len(prefix) :]
    return tool_name
