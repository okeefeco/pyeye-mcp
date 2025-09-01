<!--
Audience: Claude Code
Purpose: Define mandatory rules and validation requirements that must never be violated
When to update: When core safety or quality requirements change
-->

# Core Rules and Mandatory Requirements

## 🚨 CRITICAL: These Rules Are Non-Negotiable

### ⚠️ Worktree Safety Rules

#### NEVER force-delete worktrees without explicit permission

1. **Before ANY worktree removal**:

   ```bash
   # Check for uncommitted changes
   git -C <worktree-path> status --short

   # Or use our safety script
   python scripts/worktree_safety.py check <worktree-path>
   ```

2. **Worktree Ownership**:
   - Only remove worktrees YOU created in current session
   - Check `.worktree-ownership.json` if it exists
   - When in doubt, ASK the user

3. **Safe Cleanup Process**:

   ```bash
   # List all worktrees with safety status
   python scripts/worktree_safety.py list

   # Check specific worktree
   python scripts/worktree_safety.py check <path>

   # Safe removal (prompts if changes detected)
   python scripts/worktree_safety.py remove <path>

   # NEVER use --force without explicit user permission
   ```

4. **If you see "contains modified or untracked files"**:
   - STOP immediately
   - Report to user
   - Ask for explicit instructions
   - Do NOT proceed with --force

**Remember**: Worktrees can contain days of uncommitted work from other sessions!

### Critical Development Rules

**These are non-negotiable - violations will cause CI failures:**

1. **🖥️ Cross-Platform Paths**: ALWAYS use `path.as_posix()` for display/storage. NEVER use `str(path)` in string contexts.
2. **⏱️ Performance Tests**: ALWAYS use `PerformanceThresholds` framework. NEVER write naive `assert elapsed < 0.2` assertions.
3. **✅ Tests Required**: ALL code changes MUST include comprehensive tests.

### Validation Rules

#### NEVER bypass these without explicit user permission

1. **Pre-commit hooks** - If pre-commit fails, STOP and report the errors
2. **Test failures** - Never commit if tests are failing
3. **Linting errors** - Must pass ruff, black, mypy before committing
4. **Type checking** - All type errors must be resolved
5. **Security checks** - Must pass bandit and safety checks

#### Validation Workflow

- Run validations BEFORE marking any task as complete
- If validations fail, fix them or ask user for guidance
- NEVER use `--no-verify`, `--force`, or similar bypass flags unless user explicitly says "skip validation" or "bypass checks"
- Document validation status in todo list
- If pre-commit hooks fail during commit, STOP immediately and fix issues

#### Commit Rules

- Always run pre-commit hooks (they run automatically)
- If hooks modify files, review changes and re-commit
- Never commit with failing tests or linting errors
- User must explicitly say "commit anyway" or "bypass" to skip

### Test-Driven Development Requirements

**ALL code changes MUST include tests. This is enforced by CI.**

When implementing ANY feature or fix:

1. **Write tests FIRST** (TDD approach recommended)
2. **Implement the feature/fix**
3. **Run tests locally with coverage check**:

   ```bash
   # IMPORTANT: Run ALL tests, not just your new tests!
   uv run pytest --cov=src/pycodemcp --cov-fail-under=85
   ```

4. **Fix any failing tests or coverage issues**
5. **NEVER commit code without tests**

### Coverage Requirements

- **Minimum 85% total coverage** (CI will fail below this)
- **New code should have >90% coverage**
- **All bug fixes MUST include regression tests**
- **ALWAYS run full test suite before pushing** (learned from PR #77)

### Before Marking Tasks Complete

Always run these validation commands:

```bash
# MANDATORY: Run ALL tests with coverage (not just your new tests!)
uv run pytest --cov=src/pycodemcp --cov-fail-under=85

# Note: Linting/type checks are handled by pre-commit hooks automatically
```

### Permission Escalation Rules

You MUST get explicit user permission for:

- Using `--force` flag on any command
- Using `--no-verify` on commits
- Bypassing pre-commit hooks
- Skipping tests
- Removing worktrees with uncommitted changes
- Any operation that could lose data

The user must use explicit words like:

- "skip validation"
- "bypass checks"
- "force delete"
- "commit anyway"

Without these explicit permissions, you MUST refuse and explain why.
