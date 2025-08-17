# Python Code Intelligence MCP Server

An extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis, navigation, and understanding capabilities for AI assistants like Claude.

## Features

- **Semantic Code Navigation**: Find symbols, go to definitions, find references
- **Framework Detection**: Automatically detects and understands Django, FastAPI, Flask patterns
- **Extensible Plugin System**: Add custom analyzers for your project's specific patterns
- **Fast & Cached**: Efficient caching layer for large codebases
- **Type-Aware**: Full understanding of Python type hints and annotations
- **Cross-File Intelligence**: Import graphs, dependency analysis, dead code detection

## Quick Start

### Installation

```bash
# Using uv (recommended)
uv add python-code-intelligence-mcp

# Or using pip
pip install python-code-intelligence-mcp
```

### Basic Usage

```bash
# Run in development mode
uv run mcp dev src/pycodemcp/server.py

# Test with MCP Inspector
uv run mcp inspector
```

### Configure with Claude Desktop

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "python-intelligence": {
      "command": "uv",
      "args": ["run", "mcp", "server", "/path/to/python-code-intelligence-mcp/src/pycodemcp/server.py"]
    }
  }
}
```

## Core Tools

- `find_symbol(name)` - Find all definitions of a symbol
- `goto_definition(file, line, column)` - Jump to symbol definition
- `find_references(file, line, column)` - Find all usages of a symbol
- `get_type_info(file, line, column)` - Get type information at position
- `find_imports(module)` - Find all imports of a module
- `get_call_hierarchy(function)` - Get call graph for a function

## Architecture

The server is built with a layered, plugin-based architecture:

1. **Core MCP Interface** - FastMCP server implementation
2. **Analysis Engines** - Jedi for semantic analysis, Tree-sitter for pattern matching
3. **Framework Plugins** - Auto-detects and loads Django, FastAPI, Flask plugins
4. **Project Extensions** - Add your own custom patterns and tools

## Extending

Create custom plugins for your project patterns:

```python
from pycodemcp.plugins.base import AnalyzerPlugin

class MyProjectPlugin(AnalyzerPlugin):
    def find_api_endpoints(self):
        """Find all API endpoints in your project"""
        # Your custom logic here
```

## Development

```bash
# Install development dependencies
uv add --dev pytest black ruff mypy

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Acknowledgments

Built on top of:
- [Jedi](https://github.com/davidhalter/jedi) - Python static analysis
- [Tree-sitter](https://tree-sitter.github.io/) - Incremental parsing
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework