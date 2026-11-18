#!/bin/bash
# Wrapper script to track MCP usage during development

# Track that we're using MCP instead of grep
echo "MCP tool used: $1" >> ~/.pyeye/metrics/mcp_usage.log

# Log to our metrics system
# Its imports live only in the project's uv environment (#879)
PROJECT_ROOT="$(dirname "$0")/.."
uv run --frozen --project "$PROJECT_ROOT" python "$PROJECT_ROOT/scripts/dogfooding_metrics.py" mcp "$1" 2>/dev/null || true

# Note: Actual MCP calls happen through Claude Code's integration
echo "Logged MCP usage: $1"
