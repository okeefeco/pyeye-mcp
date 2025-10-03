# Worktree Manager Agent - Learnings

## Issue #1: Shell Directory Reset After Git Worktree Add

**Date**: 2025-01-30
**Frequency**: Encountered on first use

### Problem

After running `git worktree add`, subsequent `cd` commands with relative paths fail because the shell resets to `CLAUDE_STARTUP_DIR` between commands.

### Root Cause

Each Bash tool invocation runs in an isolated shell session. The working directory doesn't persist between commands unless explicitly managed.

### Solution

```bash
# ❌ OLD (Problematic)
git worktree add ../pyeye-mcp-work/test-115-jedi-analyzer-coverage -b test/115  # pragma: allowlist secret
cd ../pyeye-mcp-work/test-115-jedi-analyzer-coverage  # FAILS!

# ✅ NEW (Reliable)
WORK_DIR="/home/mark/GitHub/pyeye-mcp-work/test-115-jedi-analyzer-coverage"  # pragma: allowlist secret
git worktree add "$WORK_DIR" -b test/115-jedi-analyzer-coverage main
cd "$WORK_DIR" && export CLAUDE_WORKING_DIR=$(pwd) && echo "Switched to: $CLAUDE_WORKING_DIR"
```

### Implementation Notes

- Always resolve to absolute paths before operations
- Chain directory changes with && to ensure they happen in the same shell
- Export CLAUDE_WORKING_DIR immediately after successful cd
- Add verification: `pwd` after cd to confirm location

---

## Issue #2: Context Preservation Across Commands

**Date**: 2025-01-30
**Frequency**: Will occur in every session

### Problem

`CLAUDE_WORKING_DIR` is not automatically updated when switching to new worktrees, causing subsequent commands to run in wrong directory.

### Root Cause

The agent doesn't maintain session context between different tool invocations.

### Solution

```bash
# Add to worktree creation workflow:
export CLAUDE_WORKING_DIR=$(pwd)
echo "Working directory updated to: $CLAUDE_WORKING_DIR"

# For all subsequent commands in that worktree:
cd "$CLAUDE_WORKING_DIR" && <command>
```

### Implementation Notes

- Make CLAUDE_WORKING_DIR export a mandatory step
- Add reminders in agent output about using the exported variable
- Consider adding a context check at the start of each command block

---

## Issue #3: Coverage Validation Discrepancies

**Date**: 2025-01-30
**Frequency**: First occurrence

### Problem

Agent reported 39% coverage for jedi_analyzer.py but issue title claims 77% coverage.

### Root Cause

Either the issue information is outdated or the coverage check was run incorrectly.

### Solution

- Always run coverage check to get current state
- Don't assume issue descriptions are current
- Report discrepancies to user for clarification

### Implementation Notes

```bash
# Always validate claims with actual measurement
uv run pytest tests/test_jedi_analyzer.py --cov=src/pyeye/analyzers/jedi_analyzer --cov-report=term
echo "Note: Actual coverage may differ from issue description"
```

---

## Universal Patterns Discovered

### Pattern 1: Absolute Paths Are Essential

**Applies to**: All directory operations
**Rule**: Never use relative paths after changing context

### Pattern 2: State Validation Before Operations

**Applies to**: All git and filesystem operations
**Rule**: Always verify current state before proceeding

### Pattern 3: Export Critical Variables

**Applies to**: Any variable needed across commands
**Rule**: Export and echo important variables for visibility

---

## Recommended Agent Updates

### Priority 1 (Immediate)

1. Update all `cd` commands to use absolute paths
2. Add `export CLAUDE_WORKING_DIR=$(pwd)` after every directory change
3. Chain commands with && when order matters

### Priority 2 (This Week)

1. Add error checking after critical operations
2. Implement state validation before operations
3. Add progress reporting to user

### Priority 3 (Future)

1. Create helper functions for common operations
2. Add automatic recovery strategies
3. Implement session state persistence

---

## Test Cases for Validation

### Test 1: Worktree Creation

```bash
# Should successfully create and switch to worktree
WORK_DIR="/absolute/path/to/new/worktree"
git worktree add "$WORK_DIR" -b test/branch main
cd "$WORK_DIR" && pwd  # Should output the work directory
```

### Test 2: Context Preservation

```bash
export CLAUDE_WORKING_DIR="/some/path"
echo $CLAUDE_WORKING_DIR  # Should maintain the value
cd "$CLAUDE_WORKING_DIR" && pwd  # Should be in correct directory
```

### Test 3: Error Recovery

```bash
cd /nonexistent/path || echo "Failed to change directory"
# Should see error message, not silent failure
```

---

## Metrics to Track

- Success rate of worktree operations
- Number of manual interventions required
- Time to complete worktree setup
- Frequency of path-related errors
- User satisfaction with agent performance
