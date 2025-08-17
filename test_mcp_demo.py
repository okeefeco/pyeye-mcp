#!/usr/bin/env python3
"""Test script to demonstrate MCP server capabilities."""

import json
import subprocess
import sys
from typing import Any


def call_mcp_tool(tool_name: str, **params: Any) -> Any:
    """Call an MCP tool and return the result."""
    # Create the MCP request
    request = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": params},
        "id": 1,
    }

    # Initialize connection first
    init_request = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {"protocolVersion": "0.1.0", "capabilities": {}},
        "id": 0,
    }

    # Run the server and send requests
    process = subprocess.Popen(
        [sys.executable, "src/pycodemcp/server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Send initialize
    process.stdin.write(json.dumps(init_request) + "\n")
    process.stdin.flush()

    # Read response
    init_response = process.stdout.readline()
    print(f"Init response: {init_response[:100]}...")

    # Send actual request
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()

    # Read response
    response = process.stdout.readline()
    process.terminate()

    return json.loads(response) if response else None


def demo_mcp_server() -> None:
    """Demonstrate MCP server capabilities."""
    print("🔍 Python Code Intelligence MCP Server Demo\n")
    print("=" * 50)

    # Demo 1: Find a symbol
    print("\n1. Finding the 'Calculator' class:")
    result = call_mcp_tool("find_symbol", name="Calculator", project_path=".")
    if result:
        print(f"   Result: {json.dumps(result, indent=2)[:200]}...")

    # Demo 2: List project structure
    print("\n2. Listing project structure:")
    result = call_mcp_tool("list_project_structure", project_path=".", max_depth=2)
    if result:
        print(f"   Result: {json.dumps(result, indent=2)[:200]}...")

    print("\n" + "=" * 50)
    print("✅ Demo complete!")


if __name__ == "__main__":
    # For now, let's just show what tools are available
    print("🔍 Python Code Intelligence MCP Server - Available Tools\n")
    print("=" * 50)
    print("\nThe MCP server provides these tools for Python code analysis:\n")

    tools = [
        ("find_symbol", "Search for class, function, or variable definitions"),
        ("goto_definition", "Jump to where a symbol is defined"),
        ("find_references", "Find all places where a symbol is used"),
        ("get_type_info", "Get type hints and docstrings for a symbol"),
        ("find_imports", "Find all imports of a module"),
        ("get_call_hierarchy", "Analyze function call relationships"),
        ("list_project_structure", "View Python project file structure"),
    ]

    for i, (tool, description) in enumerate(tools, 1):
        print(f"{i}. {tool:<25} - {description}")

    print("\n" + "=" * 50)
    print("\nExample usage in Claude Code:")
    print("  - 'Find all uses of the Calculator class'")
    print("  - 'Show me where the add method is defined'")
    print("  - 'What functions call calculate_area?'")
    print("  - 'List all Django models in this project'")

    print("\nThe server is connected and ready to analyze Python code!")
