<!--
Audience: Claude Code
Purpose: Define cross-platform path handling requirements
When to update: When path handling patterns or utilities change
-->

# Cross-Platform Path Handling

## Key Learning from PR #121

When working with paths that will be displayed or compared as strings:

- **Always use `.as_posix()`** for consistent forward-slash format
- **Don't use raw `str(Path)`** for relative paths - it uses OS-native separators
- **Example**: Template names, config paths, display paths

## Quick Reference

```python
# ❌ WRONG - OS-dependent separators
template_name = str(template_file.relative_to(template_dir))
# Windows: "admin\\dashboard.html"
# Unix: "admin/dashboard.html"

# ✅ CORRECT - Always forward slashes
template_name = template_file.relative_to(template_dir).as_posix()
# All platforms: "admin/dashboard.html"
```

## Path Utilities Available

- `src/pycodemcp/path_utils.py` has helpers:
  - `path_to_key()` - For dictionary keys/comparison
  - `ensure_posix_path()` - Convert any path to forward slashes
  - `paths_equal()` - Platform-safe path comparison

## When to Use Each Method

| Use Case | Method | Example |
|----------|--------|---------|
| API responses | `.as_posix()` | `{"file": path.as_posix()}` |
| Display paths | `.as_posix()` | `print(f"File: {path.as_posix()}")` |
| Dictionary keys | `path_to_key()` | `cache[path_to_key(file_path)]` |
| Config values | `.as_posix()` | `config["template_dir"] = path.as_posix()` |
| Path comparison | `paths_equal()` | `if paths_equal(p1, p2):` |
| JSON/YAML storage | `.as_posix()` | `data["path"] = path.as_posix()` |
| Test assertions | `.as_posix()` | `assert result == expected.as_posix()` |
| OS operations | `str()` or `to_os_path()` | `subprocess.run([str(path)])` |

## Common Pitfalls to Avoid

```python
# ❌ WRONG - Direct string conversion for comparison
if str(path1) == str(path2):
    ...

# ✅ CORRECT - Use path utilities
from pycodemcp.path_utils import paths_equal
if paths_equal(path1, path2):
    ...

# ❌ WRONG - Using str() for paths in data structures
cache[str(file_path)] = data

# ✅ CORRECT - Use path_to_key
from pycodemcp.path_utils import path_to_key
cache[path_to_key(file_path)] = data
```

## Testing on Windows

- CI runs on Windows, macOS, and Linux
- Windows path issues typically show as:
  - `AssertionError: 'path/to/file' != 'path\\to\\file'`
  - Template/config file paths are common culprits

## Best Practices for Tests

```python
# Use pathlib for test fixtures
from pathlib import Path

test_file = Path("tests/fixtures/sample.py")

# Always use .as_posix() in assertions
assert result["file"] == test_file.as_posix()

# Use path utilities for comparisons
from pycodemcp.path_utils import paths_equal
assert paths_equal(result_path, expected_path)
```

## Using Cross-Platform Validator Agent

When user asks to validate cross-platform compatibility:

```bash
# IMMEDIATELY use:
Task tool with subagent_type="cross-platform-validator"

# NEVER manually check paths with grep
```

The agent will:

1. Analyze path usage patterns
2. Identify Windows-specific issues
3. Check for .as_posix() usage
4. Validate path utilities are used correctly

## Related Resources

- PR #121 - Flask plugin cross-platform fixes (reference implementation)
- Issue #110 - Original issue that discovered these problems
- `src/pycodemcp/path_utils.py` - Path utility functions
