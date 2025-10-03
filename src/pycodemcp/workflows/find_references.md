# Find All References Workflow

## Goal

Find **ALL** places where a class/function is used, including:

- Python packages (importable code with `__init__.py`)
- Notebooks and standalone scripts (files without package structure)

This workflow addresses the limitation that `find_references` only works with Python packages (issue #236) by combining it with `Grep` to ensure complete coverage.

## When to Use This Workflow

- "Find all usages of this class/function"
- "Where is this symbol used?"
- "Show me all references before refactoring"
- "Which notebooks/scripts use this code?"

## Steps

### Step 1: Get Fully Qualified Name

Use `get_type_info` to obtain the fully qualified name of the symbol:

**Input**: File path, line number, and column number of the symbol
**Extract**: `full_name` from the response
**Example**: `"mypackage.module.ClassName"`

```python
# Example call
get_type_info(
    file="/project/mypackage/models.py",
    line=10,
    column=6
)

# Response includes:
# {
#     "full_name": "mypackage.models.User",
#     "type": "class",
#     ...
# }
```

### Step 2: Find References in Packages

Use `find_references` to find all usage in Python packages (directories with `__init__.py`):

**Input**: Same file, line, and column as Step 1
**Returns**: All references found in importable packages

```python
# Example call
find_references(
    file="/project/mypackage/models.py",
    line=10,
    column=6
)

# Returns package references:
# [
#     {"file": "/project/mypackage/services.py", "line": 45, ...},
#     {"file": "/project/tests/test_models.py", "line": 12, ...}
# ]
```

### Step 3: Find References in Standalone Scripts

Use `Grep` to find usage in standalone Python files (notebooks, scripts, examples):

**Input**: The fully qualified name from Step 1
**Parameters**:

- `pattern`: The fully qualified class/function name
- `path`: Directory containing standalone scripts (e.g., "notebooks", "scripts", "examples")
- `output_mode`: "content" (to see the actual usage)
- `-n`: true (to show line numbers)

```python
# Example call
Grep(
    pattern="mypackage.models.User",
    path="notebooks",
    output_mode="content",
    -n=True
)

# Returns notebook/script references:
# notebooks/analysis.py:23: from mypackage.models import User
# notebooks/data_load.py:56: user = User(...)
```

### Step 4: Combine Results

Merge results from Steps 2 and 3 to present complete coverage:

**Package References** (from `find_references`):

- `/project/mypackage/services.py:45`
- `/project/tests/test_models.py:12`

**Notebook/Script References** (from `Grep`):

- `/project/notebooks/analysis.py:23`
- `/project/notebooks/data_load.py:56`

## Complete Example

For a class at `/project/mypackage/models.py` line 10, column 6:

```text
Step 1: get_type_info(file="/project/mypackage/models.py", line=10, column=6)
→ full_name: "mypackage.models.User"

Step 2: find_references(file="/project/mypackage/models.py", line=10, column=6)
→ Package references:
  - /project/mypackage/services.py:45
  - /project/tests/test_models.py:12

Step 3: Grep(pattern="mypackage.models.User", path="notebooks", output_mode="content", -n=True)
→ Notebook references:
  - /project/notebooks/analysis.py:23
  - /project/notebooks/data_load.py:56

Step 4: Combined Results:
  All References Found: 4 total
  - 2 in packages (services.py, test_models.py)
  - 2 in notebooks (analysis.py, data_load.py)
```

## Limitations and Considerations

**Known Limitations**:

- `find_references` only works with Python packages (directories with `__init__.py`)
- `Grep` is literal string search - may miss dynamic imports or string-based references
- Case sensitivity matters - use `-i` flag for case-insensitive search if needed

**Workarounds**:

- For multiple script directories, run Step 3 multiple times (notebooks/, scripts/, examples/)
- For case-insensitive search, add `-i=True` to Grep parameters
- Consider variations of the import (e.g., "from X import Y" vs "import X; X.Y")

**Performance Tips**:

- Use specific `path` parameter in Grep to limit search scope
- Consider using file type filters if searching large directories
- Results are cached for 5 minutes - repeated queries are instant

## Success Indicators

✅ **Complete coverage**: Found references in both packages AND scripts/notebooks
✅ **Accurate locations**: Line numbers and file paths are correct
✅ **No false positives**: Grep pattern is specific enough to avoid unrelated matches
✅ **Context provided**: Actual usage code shown from Grep results

## Related Issues

- Issue #236: Support analyzing standalone Python scripts (this workflow provides temporary workaround)
- Issue #234: find_subclasses missing direct subclasses (may affect inheritance analysis)
