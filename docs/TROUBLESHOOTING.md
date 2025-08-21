# Python Code Intelligence MCP - Troubleshooting Guide

This guide helps resolve common issues and optimize performance for the Python Code Intelligence MCP Server.

## Table of Contents

1. [Installation Issues](#installation-issues)
2. [Configuration Problems](#configuration-problems)
3. [Performance Issues](#performance-issues)
4. [Common Errors](#common-errors)
5. [Debugging Guide](#debugging-guide)
6. [FAQ](#frequently-asked-questions-faq)
7. [Performance Tuning](#performance-tuning)

---

## Installation Issues

### Python Version Compatibility

**Problem**: Server fails to start with Python version errors.

**Solution**:

- Ensure Python 3.10+ is installed: `python --version`
- Use `uv` for consistent Python management:

  ```bash
  uv venv
  source .venv/bin/activate  # On Windows: .venv\Scripts\activate
  uv pip install -e ".[dev]"
  ```

### Virtual Environment Setup

**Problem**: Import errors or missing dependencies.

**Solution**:

1. Always use a virtual environment:

   ```bash
   uv venv
   source .venv/bin/activate
   ```

2. Reinstall dependencies:

   ```bash
   uv pip install -e ".[dev]"
   ```

3. Verify installation:

   ```bash
   python -c "import pycodemcp; print(pycodemcp.__version__)"
   ```

### Dependency Conflicts

**Problem**: Package version conflicts during installation.

**Solution**:

1. Clean install in fresh environment:

   ```bash
   rm -rf .venv
   uv venv
   uv pip install -e ".[dev]"
   ```

2. Check for conflicting packages:

   ```bash
   uv pip list | grep -E "jedi|fastmcp|mcp"
   ```

### Platform-Specific Issues

#### Windows

**Problem**: Path separator issues or file access errors.

**Solution**:

- Use forward slashes in config files: `"packages": ["C:/Users/name/project"]`
- Run terminal as Administrator if permission errors occur
- Use WSL2 for better compatibility

#### macOS

**Problem**: SSL certificate errors or system Python conflicts.

**Solution**:

- Install certificates: `/Applications/Python 3.x/Install Certificates.command`
- Use `uv` or `pyenv` to avoid system Python
- Check Gatekeeper settings for unsigned binaries

#### Linux

**Problem**: Missing system dependencies.

**Solution**:

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install python3-dev python3-venv

# Fedora/RHEL
sudo dnf install python3-devel
```

### MCP Server Connection Problems

**Problem**: Claude Code can't connect to the server.

**Solution**:

1. Verify server is properly configured:

   ```bash
   claude mcp list
   ```

2. Check server logs:

   ```bash
   # Enable debug logging
   export PYCODEMCP_DEBUG=true
   uv run mcp dev src/pycodemcp/server.py
   ```

3. Reinstall MCP configuration:

   ```bash
   claude mcp remove python-intelligence
   claude mcp add /path/to/python-code-intelligence-mcp
   ```

---

## Configuration Problems

### Config File Not Found

**Problem**: Server doesn't load configuration.

**Solution**:

1. Check configuration locations (in order of precedence):
   - `.pycodemcp.json` in project root
   - `pyproject.toml` with `[tool.pycodemcp]` section
   - Environment variables (`PYCODEMCP_*`)
   - `~/.config/pycodemcp/config.json` (global)

2. Validate JSON syntax:

   ```bash
   python -m json.tool .pycodemcp.json
   ```

### Invalid Configuration

**Problem**: Configuration errors on startup.

**Solution**:

1. Check configuration format:

   ```json
   {
     "packages": ["../my-lib", "~/repos/utils"],
     "namespaces": {
       "company": ["~/repos/auth", "~/repos/api"]
     }
   }
   ```

2. Use absolute paths or paths relative to config file
3. Expand home directory: `~/` → `/home/username/`

### Environment Variable Issues

**Problem**: Environment variables not recognized.

**Solution**:

1. Set variables correctly:

   ```bash
   export PYCODEMCP_PACKAGES="../lib1,../lib2"
   export PYCODEMCP_NAMESPACE_company="~/repos/auth,~/repos/api"
   ```

2. Verify they're set:

   ```bash
   env | grep PYCODEMCP
   ```

### Multi-Project Setup Problems

**Problem**: Can't analyze multiple projects simultaneously.

**Solution**:

1. Use `configure_packages` tool:

   ```python
   configure_packages(
       packages=["../project1", "../project2"],
       save=True  # Persist configuration
   )
   ```

2. Check project limit (default: 10 cached projects)
3. Verify paths are accessible

### Namespace Package Configuration

**Problem**: Distributed packages not resolving correctly.

**Solution**:

1. Configure namespace properly:

   ```json
   {
     "namespaces": {
       "mycompany": [
         "~/repos/mycompany-auth",
         "~/repos/mycompany-api",
         "~/repos/mycompany-utils"
       ]
     }
   }
   ```

2. Ensure `__init__.py` files exist in namespace directories
3. Use `find_in_namespace` tool to test resolution

---

## Performance Issues

### Slow Analysis on Large Codebases

**Problem**: Analysis takes too long or times out.

**Solution**:

1. Exclude unnecessary directories:

   ```json
   {
     "exclude_patterns": ["**/node_modules", "**/.venv", "**/build"]
   }
   ```

2. Increase timeout (default: 30s):

   ```bash
   export PYCODEMCP_TIMEOUT=60
   ```

3. Limit project scope to relevant code

### High Memory Usage

**Problem**: Server consumes excessive memory.

**Solution**:

1. Reduce cached projects (default: 10):

   ```bash
   export PYCODEMCP_MAX_PROJECTS=5
   ```

2. Clear cache periodically:

   ```python
   # Cache auto-expires after 5 minutes
   # Or restart server to clear all cache
   ```

3. Monitor memory usage:

   ```bash
   ps aux | grep pycodemcp
   ```

### Cache Optimization

**Problem**: Stale cache causing incorrect results.

**Solution**:

1. File watchers auto-update on changes (using watchdog)
2. Force cache refresh by modifying a file
3. Disable caching for debugging:

   ```bash
   export PYCODEMCP_CACHE_ENABLED=false
   ```

### File Watcher Performance

**Problem**: Too many file change events slow down server.

**Solution**:

1. Exclude volatile directories:

   ```json
   {
     "watch_exclude": ["**/logs", "**/tmp", "**/__pycache__"]
   }
   ```

2. Increase debounce time (default: 1s):

   ```bash
   export PYCODEMCP_DEBOUNCE=2
   ```

### Timeout Configurations

**Problem**: Operations timing out prematurely.

**Solution**:

1. Increase analysis timeout:

   ```bash
   export PYCODEMCP_ANALYSIS_TIMEOUT=60
   ```

2. For specific operations, use tool-specific timeouts
3. Check system resources aren't constrained

---

## Common Errors

### "Project not found" Errors

**Problem**: `Error: Project path '/path/to/project' not found`

**Solution**:

1. Verify path exists: `ls -la /path/to/project`
2. Check permissions: `ls -la /path/to/project/*.py`
3. Use absolute paths in configuration
4. Ensure Python files exist in the project

### "Analysis timeout" Errors

**Problem**: `TimeoutError: Analysis took longer than 30 seconds`

**Solution**:

1. Increase timeout as shown above
2. Reduce project size with exclusions
3. Check for infinite loops in code being analyzed
4. Verify Jedi is properly installed: `python -c "import jedi; print(jedi.__version__)"`

### Import Resolution Failures

**Problem**: `Cannot resolve import 'module_name'`

**Solution**:

1. Add package locations to configuration
2. Ensure PYTHONPATH includes necessary directories:

   ```bash
   export PYTHONPATH="/path/to/lib:$PYTHONPATH"
   ```

3. Check virtual environment is activated
4. Verify `__init__.py` files exist for packages

### Plugin Activation Issues

**Problem**: Framework-specific tools not appearing.

**Solution**:

1. Plugins auto-activate based on detection:
   - Django: Presence of `manage.py` or `django` in requirements
   - Flask: `flask` in imports or requirements
   - Pydantic: `pydantic` in imports or requirements
2. Check plugin loaded in debug logs
3. Manually verify framework detection:

   ```python
   # In project root
   ls manage.py  # For Django
   grep -r "from flask" . # For Flask
   ```

### File Access Permissions

**Problem**: `PermissionError: [Errno 13] Permission denied`

**Solution**:

1. Check file permissions:

   ```bash
   ls -la /path/to/file
   chmod 644 /path/to/file  # If you own it
   ```

2. Run server with appropriate user
3. Avoid analyzing system directories
4. Use read-only analysis mode (default)

---

## Debugging Guide

### Enable Debug Logging

**Step 1**: Set debug environment variable:

```bash
export PYCODEMCP_DEBUG=true
export PYCODEMCP_LOG_LEVEL=DEBUG
```

**Step 2**: Run server in dev mode:

```bash
uv run mcp dev src/pycodemcp/server.py
```

**Step 3**: Check logs for detailed information about:

- Project loading
- Cache hits/misses
- Analysis operations
- Plugin activation
- File watcher events

### Check Server Logs

Log locations:

- Console output (when run in dev mode)
- `~/.local/share/pycodemcp/logs/` (if configured)
- Claude Code logs: Check Claude's debug output

Important log patterns to look for:

```text
[INFO] Loading project: /path/to/project
[DEBUG] Cache hit for find_symbol: MyClass
[WARNING] Plugin django not activated: manage.py not found
[ERROR] Analysis failed: TimeoutError
```

### Verify Jedi Installation

Test Jedi directly:

```python
import jedi

# Test basic completion
script = jedi.Script("import os\nos.")
completions = script.complete(2, 3)
print([c.name for c in completions])  # Should show os methods

# Test project analysis
project = jedi.Project("/path/to/your/project")
print(project.path)
```

### Test with Minimal Config

Create minimal test configuration:

```json
{
  "packages": ["/path/to/single/package"]
}
```

Test basic operations:

```python
# Using MCP tools
find_symbol("TestClass", project_path="/path/to/project")
```

### Isolate Problem Projects

1. Test each project individually
2. Remove projects one by one to find problematic code
3. Check for:
   - Circular imports
   - Syntax errors
   - Extremely large files (>10MB)
   - Binary files mistaken for Python

---

## Frequently Asked Questions (FAQ)

### How to analyze multiple projects?

**Answer**: Use the configuration system to add multiple projects:

```json
{
  "packages": [
    "../project1",
    "../project2",
    "~/repos/shared-lib"
  ]
}
```

Or use the `configure_packages` tool to add them dynamically.

### Why isn't my plugin activating?

**Answer**: Plugins activate automatically based on framework detection:

- **Django**: Needs `manage.py` or `django` in requirements
- **Flask**: Needs `flask` imports or in requirements
- **Pydantic**: Needs `pydantic` imports or in requirements

Check debug logs to see detection results.

### How to exclude certain files?

**Answer**: Add exclusion patterns to configuration:

```json
{
  "exclude_patterns": [
    "**/*.pyc",
    "**/test_*.py",
    "**/migrations/*",
    "**/__pycache__/*"
  ]
}
```

### Can I use with monorepos?

**Answer**: Yes! Monorepos work well with namespace configuration:

```json
{
  "namespaces": {
    "monorepo": [
      "./packages/auth",
      "./packages/api",
      "./packages/shared"
    ]
  }
}
```

### How to handle large codebases?

**Answer**:

1. Use exclusion patterns to skip non-essential code
2. Increase timeouts and memory limits
3. Split into multiple smaller projects
4. Use project-specific analysis instead of whole codebase
5. Enable caching (default) for faster subsequent operations

### Memory usage expectations

**Answer**: Typical memory usage:

- Small project (<1000 files): 100-200MB
- Medium project (1000-5000 files): 200-500MB
- Large project (5000+ files): 500MB-1GB
- With 10 cached projects: Multiply by cache size

### Supported Python versions

**Answer**:

- **Server requires**: Python 3.10+
- **Analyzed code**: Python 2.7+ (Jedi supports legacy code)
- **Recommended**: Python 3.11+ for best performance

### Framework detection logic

**Answer**: Detection order:

1. Check for framework-specific files (`manage.py`, `app.py`)
2. Parse imports in Python files
3. Check requirements files (`requirements.txt`, `pyproject.toml`)
4. Check installed packages in environment

Detection is automatic and happens when project loads.

---

## Performance Tuning

### Optimal Cache Settings

**Default settings** (usually optimal):

```python
CACHE_TTL = 300  # 5 minutes
MAX_CACHED_PROJECTS = 10
DEBOUNCE_DELAY = 1.0  # 1 second
```

**For large codebases**:

```bash
export PYCODEMCP_CACHE_TTL=600  # 10 minutes
export PYCODEMCP_MAX_PROJECTS=5  # Fewer but larger projects
export PYCODEMCP_DEBOUNCE=2.0   # Reduce file watch overhead
```

**For rapid development**:

```bash
export PYCODEMCP_CACHE_TTL=60   # 1 minute
export PYCODEMCP_DEBOUNCE=0.5   # Faster updates
```

### Worker Configuration

The server uses asynchronous processing. Tune based on CPU cores:

```bash
# For 4-core system (default)
export PYCODEMCP_WORKERS=4

# For intensive analysis on 8-core system
export PYCODEMCP_WORKERS=6  # Leave some for system
```

### File Size Limits

Prevent analysis of huge files:

```json
{
  "max_file_size": 1048576,  // 1MB default
  "skip_large_files": true
}
```

### Debounce Settings

Control how quickly the server responds to file changes:

```bash
# Default: 1 second
export PYCODEMCP_DEBOUNCE=1.0

# For slower systems or network drives
export PYCODEMCP_DEBOUNCE=3.0

# For local SSDs with small projects
export PYCODEMCP_DEBOUNCE=0.2
```

### Project Limit Tuning

Balance memory usage vs cache effectiveness:

```python
# Small memory system (<8GB RAM)
MAX_CACHED_PROJECTS = 3

# Standard system (16GB RAM)
MAX_CACHED_PROJECTS = 10  # Default

# High memory system (32GB+ RAM)
MAX_CACHED_PROJECTS = 20
```

### Optimization Checklist

1. ✅ Exclude unnecessary directories (node_modules, venv, etc.)
2. ✅ Set appropriate timeouts for your codebase size
3. ✅ Tune cache TTL based on development patterns
4. ✅ Adjust worker count for your CPU
5. ✅ Configure debounce for your file system speed
6. ✅ Limit cached projects based on available RAM
7. ✅ Use namespace packages for related projects
8. ✅ Enable debug logging only when troubleshooting

---

## Getting Additional Help

If you're still experiencing issues:

1. **Check existing issues**: [GitHub Issues](https://github.com/okeefeco/python-code-intelligence-mcp/issues)
2. **Enable debug mode** and collect logs
3. **Create a minimal reproduction** of the problem
4. **Open a new issue** with:
   - Python version
   - OS and version
   - Configuration file
   - Debug logs
   - Steps to reproduce

## Quick Diagnostics Script

Save and run this script to collect diagnostic information:

```python
#!/usr/bin/env python3
"""Diagnostic script for Python Code Intelligence MCP"""

import sys
import os
import json
import subprocess
from pathlib import Path

print("Python Code Intelligence MCP - Diagnostics")
print("=" * 50)

# Python version
print(f"Python version: {sys.version}")

# Check required packages
packages = ["jedi", "fastmcp", "mcp", "watchdog", "pydantic"]
for pkg in packages:
    try:
        module = __import__(pkg)
        version = getattr(module, "__version__", "unknown")
        print(f"✅ {pkg}: {version}")
    except ImportError:
        print(f"❌ {pkg}: not installed")

# Check configuration
config_locations = [
    Path.cwd() / ".pycodemcp.json",
    Path.home() / ".config/pycodemcp/config.json",
]

print("\nConfiguration files:")
for config_path in config_locations:
    if config_path.exists():
        print(f"✅ Found: {config_path}")
        try:
            with open(config_path) as f:
                json.load(f)
            print("  Valid JSON")
        except json.JSONDecodeError as e:
            print(f"  ❌ Invalid JSON: {e}")
    else:
        print(f"  Not found: {config_path}")

# Environment variables
print("\nEnvironment variables:")
for key, value in os.environ.items():
    if key.startswith("PYCODEMCP"):
        print(f"  {key}={value}")

# MCP server status
print("\nMCP server status:")
try:
    result = subprocess.run(
        ["claude", "mcp", "list"],
        capture_output=True,
        text=True,
        timeout=5
    )
    if "python-intelligence" in result.stdout:
        print("✅ Server configured in Claude Code")
    else:
        print("❌ Server not found in Claude Code")
except Exception as e:
    print(f"❌ Could not check MCP status: {e}")

print("\n" + "=" * 50)
print("Include this output when reporting issues")
```

---

Last updated: August 2025
