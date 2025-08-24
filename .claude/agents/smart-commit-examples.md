# Smart Commit Agent - Usage Examples

This document shows how the `smart-commit` agent handles the complete git commit workflow efficiently.

## Example 1: Clean Validation (Success Case)

**User**: "Run pre-commit validation"

**Agent Response**:

```bash
echo "🔍 Running pre-commit validation..." && \
pre-commit run --all-files --show-diff-on-failure 2>&1 | \
grep -E "(FAILED|ERROR|WARNING|✓|✗)" || echo "All hooks passed"
```

**Output**:

```text
✅ **Pre-commit Validation Complete**
- All hooks passed
- 0 files modified by hooks
- Tests passing
- Ready to commit
```

## Example 2: Auto-fixable Issues

**User**: "Check if ready to commit"

**Agent discovers auto-fixable issues and handles them**:

```bash
# Initial check reveals fixable issues
echo "🔧 Auto-fixing issues..." && \
pre-commit run --all-files 2>&1 >/dev/null && \
echo "✅ All hooks now passing" || \
echo "❌ Manual intervention required"
```

**Agent Response**:

```text
🔧 **Auto-fixed Issues**
- black: Reformatted 3 files
- ruff: Fixed 5 import/style issues
- end-of-file-fixer: Added newlines to 2 files

✅ **Validation Complete** - Ready to commit
```

## Example 3: Manual Intervention Required

**User**: "Validate all hooks and tests"

**Agent finds issues requiring human fix**:

```bash
# Check what needs manual fixing
pre-commit run --all-files 2>&1 | \
awk '/FAILED|ERROR/ {print "❌ " $0} /Passed|Skipped/ {count++} END {if(count>0) print "✅ " count " hooks passed"}'
```

**Agent Response**:

```text
❌ **Manual Intervention Required**

**Type Checking (mypy)**:
- `src/server.py:45` - Missing return type annotation
- `src/cache.py:120` - Incompatible types in assignment

**Security (bandit)**:
- `src/config.py:33` - Hardcoded password found

**Action Required**: Fix these 3 issues, then run `pre-commit run --all-files`
```

## Example 4: Complete Workflow

**User**: "Fix and commit changes"

**Agent runs complete validation workflow**:

```bash
# Multi-step efficient workflow
echo "📊 Current Status:" && \
echo "Pre-commit: $(pre-commit run --all-files >/dev/null 2>&1 && echo '✅' || echo '❌')" && \
echo "Tests: $(pytest -q >/dev/null 2>&1 && echo '✅' || echo '❌')" && \
echo "Uncommitted: $(git status --porcelain | wc -l) files"
```

**Agent Response** (if everything passes):

```text
✅ **Complete Validation Successful**

**Pre-commit**: All hooks passed
**Tests**: All 47 tests passing
**Git Status**: 3 files staged, 0 modified

**Ready to commit!** 🚀
```

## Example 5: Hook Retry Cycle

**User**: "Auto-fix code issues"

**Agent handles the hook-modified-files retry automatically**:

```bash
# Detect if hooks modified files
git status --porcelain | wc -l | xargs -I {} echo "{} files modified by hooks"
```

If hooks modified files, agent automatically re-runs validation:

**Agent Response**:

```text
🔄 **Hook Retry Cycle**
- Initial run: Fixed formatting in 4 files
- Files modified by hooks, re-running validation
- Second run: All hooks passed

✅ **Validation Complete** - Ready to commit
```

## Example 6: Test Failures

**User**: "Check if ready to commit"

**Agent finds test failures**:

```bash
# Quick test failure summary
pytest --tb=line -q 2>&1 | grep -E "FAILED|ERROR" | head -5 | \
sed 's/^/❌ /' || echo "✅ All tests passing"
```

**Agent Response**:

```text
⚠️ **Tests Failing**

❌ tests/test_server.py::test_find_symbol - AssertionError
❌ tests/test_cache.py::test_invalidation - KeyError: 'missing_key'

**Pre-commit**: All hooks passed ✅
**Tests**: 2 failures, 45 passed ❌

**Action Required**: Fix test failures before committing
```

## Efficiency Principles in Action

### Batched Commands

Instead of 5 separate tool calls:

```bash
pre-commit run --all-files
git status
pytest
git diff --name-only
echo "Status complete"
```

Agent uses one batched command:

```bash
echo "📊 Status:" && \
pre-commit run --all-files >/dev/null 2>&1 && echo "Pre-commit: ✅" || echo "Pre-commit: ❌" && \
pytest -q >/dev/null 2>&1 && echo "Tests: ✅" || echo "Tests: ❌" && \
echo "Modified: $(git status --porcelain | wc -l) files"
```

### Smart Filtering

Instead of showing 200 lines of verbose pre-commit output, agent filters to essentials:

```bash
pre-commit run --all-files 2>&1 | grep -E "(FAILED|ERROR|WARNING)" | head -10
```

### Progressive Disclosure

- **Success**: Minimal output, just confirmation
- **Auto-fixes**: Brief summary of what was fixed
- **Manual issues**: Detailed file:line references
- **Failures**: Specific actions required

This approach minimizes context usage while providing maximum actionable information.
