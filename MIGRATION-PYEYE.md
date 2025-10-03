# Migration Guide: Rebranding to PyEye

## Overview

The project has been rebranded from `python-code-intelligence-mcp` to **PyEye** 👁️ for better memorability and discoverability.

## What Changed

### Package & Module Names

- **PyPI Package**: `python-code-intelligence-mcp` → `pyeye-mcp`
- **Python Module**: `pycodemcp` → `pyeye`
- **MCP Server Entry Point**: `python -m pycodemcp.server` → `python -m pyeye.mcp`
- **Brand Name**: "Python Code Intelligence" → "PyEye 👁️"

### GitHub Repository

- **Repository**: `okeefeco/python-code-intelligence-mcp` → `okeefeco/pyeye-mcp`
- **Old URLs automatically redirect** - no broken links!

### Environment Variables

All environment variables have been renamed:

- `PYCODEMCP_*` → `PYEYE_*`

Examples:

- `PYCODEMCP_MAX_PROJECTS` → `PYEYE_MAX_PROJECTS`
- `PYCODEMCP_CACHE_TTL` → `PYEYE_CACHE_TTL`
- `PYCODEMCP_PACKAGES` → `PYEYE_PACKAGES`

### Configuration Files

- `.pycodemcp.json` → `.pyeye.json`
- `.pycodemcp.override.json` → `.pyeye.override.json`
- `~/.config/pycodemcp/` → `~/.config/pyeye/`
- `[tool.pycodemcp]` in pyproject.toml → `[tool.pyeye]`

## Migration Steps

### For End Users

#### 1. Uninstall Old Package

```bash
pip uninstall python-code-intelligence-mcp
# or
pipx uninstall python-code-intelligence-mcp
```

#### 2. Install New Package

```bash
pip install pyeye-mcp
# or
pipx install pyeye-mcp
```

#### 3. Update MCP Registration

**Claude Code:**

```bash
# Remove old registration
claude mcp remove python-intelligence

# Add new registration
claude mcp add pyeye -- python -m pyeye.mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "pyeye": {
      "command": "python",
      "args": ["-m", "pyeye.mcp"],
      "env": {}
    }
  }
}
```

**GitHub Copilot** (VS Code `settings.json`):

```json
{
  "github.copilot.chat.mcpServers": {
    "pyeye": {
      "command": "python",
      "args": ["-m", "pyeye.mcp"],
      "env": {}
    }
  }
}
```

#### 4. Update Configuration Files

Rename your config files:

```bash
# Project config
mv .pycodemcp.json .pyeye.json

# Override file (if you have one)
mv .pycodemcp.override.json .pyeye.override.json

# Global config directory
mv ~/.config/pycodemcp ~/.config/pyeye
```

Update `pyproject.toml` if using:

```toml
# Old
[tool.pycodemcp]
packages = ["../my-lib"]

# New
[tool.pyeye]
packages = ["../my-lib"]
```

#### 5. Update Environment Variables

Update any scripts or shell configs:

```bash
# Old
export PYCODEMCP_MAX_PROJECTS=20
export PYCODEMCP_CACHE_TTL=600

# New
export PYEYE_MAX_PROJECTS=20
export PYEYE_CACHE_TTL=600
```

### For Developers/Contributors

If you have a local development setup:

#### 1. Update Git Remote

```bash
# The old URL will redirect, but update for clarity
git remote set-url origin git@github.com:okeefeco/pyeye-mcp.git
```

#### 2. Reinstall in Development Mode

```bash
# Uninstall old
pip uninstall python-code-intelligence-mcp

# Reinstall new
uv pip install -e ".[dev]"
```

#### 3. Update Code References

If you have any code importing the old module:

```python
# Old
from pycodemcp.config import ProjectConfig
import pycodemcp.server

# New
from pyeye.config import ProjectConfig
import pyeye.mcp.server
```

#### 4. Update Tests

Test coverage paths have changed:

```bash
# Old
pytest --cov=src/pycodemcp

# New
pytest --cov=src/pyeye
```

## What Stays the Same

- **All functionality** - No breaking changes to the API
- **Configuration format** - Same JSON/TOML structure
- **Tool names** - MCP tools like `find_symbol` unchanged
- **File watching** - All features work exactly the same

## Benefits of the Rebrand

- **Easier to remember**: "PyEye" vs "python-code-intelligence-mcp"
- **Faster to type**: `pip install pyeye-mcp` vs `pip install python-code-intelligence-mcp`
- **Better for recommendations**: "Check out PyEye!" vs "Check out python-code-intelligence-mcp"
- **Consistent with Python ecosystem**: PyPI, PyTorch, NumPy pattern

## Need Help?

- **Issues**: <https://github.com/okeefeco/pyeye-mcp/issues>
- **Documentation**: <https://github.com/okeefeco/pyeye-mcp#readme>
- **Old URLs**: All old github.com links automatically redirect!

## Timeline

- **Current Release**: Rebrand complete as of v0.3.x
- **Old Package Name**: Will remain available for 6 months as a transitional package pointing to pyeye-mcp
- **Support**: Please migrate at your earliest convenience

---

Welcome to **PyEye** 👁️ - the same great Python Code Intelligence, now with a name you can actually remember!
