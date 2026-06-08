<!--
Audience: Claude Code
Purpose: Define commit and PR workflow requirements
When to update: When commit standards or PR processes change
-->

# Commit and Pull Request Workflow

## Commit Message Format

Use conventional commits format:

```text
type(scope): description

[optional body]

[optional footer]
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks
- `perf`: Performance improvements

### Examples

```bash
git commit -m "feat(plugins): add FastAPI plugin support"
git commit -m "fix(cache): resolve file watcher memory leak"
git commit -m "docs: update installation instructions"
```

## Creating Pull Requests

### PR Requirements

- Clear title and description
- Link to related issue (if applicable)
- All CI checks passing
- **MANDATORY**: Security checks passing (secrets, SAST, dependencies)
- **MANDATORY**: Tests for ALL new functionality (coverage must not drop)
- **MANDATORY**: Tests for ALL bug fixes (include regression tests)
- Documentation updates (if needed)

### PR Creation via CLI

```bash
# Push your branch
git push -u origin feature/your-feature-name

# Create PR
gh pr create --title "feat: your feature" --body "Description of changes"
```

### PR Title Format

PR titles should follow the branch naming convention and reference the issue:

- `feat: add new validation system (#23)`
- `fix: resolve cache memory leak (#24)`
- `docs: update API documentation (#25)`

### Linking Issues

Always reference the related issue in PR body:

- Use "Fixes #<issue-number>" for bug fixes (auto-closes issue on merge)
- Use "Addresses #<issue-number>" for partial implementations
- Use "Related to #<issue-number>" for related work

## Test Requirements (MANDATORY)

**Every PR that adds or modifies code MUST include:**

1. **Unit tests** for new functions/methods
2. **Integration tests** for new features
3. **Regression tests** for bug fixes
4. **Coverage must not drop** - CI will fail if coverage drops

**Before marking any PR as ready:**

```bash
# MANDATORY: Run ALL tests with coverage
pytest --cov=src/pyeye --cov-fail-under=85
```

## Using Smart-Commit Agent

**When user says "commit" or similar**, ALWAYS use the smart-commit agent:

```bash
# Instead of manual commands, use:
Task tool with subagent_type="smart-commit"
```

The agent will:

1. Check git status and diff
2. Validate no sensitive information
3. Run pre-commit hooks
4. Create appropriate commit message
5. Handle pre-commit fixes if needed

## Creating PRs (raw commands)

The pr-workflow agent was deleted — see `04-agent-triggers.md` for rationale. Use raw commands; they're transparent and `gh` already provides the high-value pieces.

```bash
# 1. Verify untracked files (per post-commit-verification rule in smart-commit)
git status --short

# 2. Push (capture exit code; verify the remote actually has the commits)
git push -u origin "$(git branch --show-current)"
[ "$(git rev-parse HEAD)" = "$(git rev-parse @{u})" ] || { echo "ERROR: push did not sync"; exit 1; }

# 3. Create PR — issue link via "Fixes #N" syntax in body, NOT a flag
gh pr create --base <base-branch> --title "type(scope): summary (#N)" --body "$(cat <<'EOF'
## Summary
- <bullet>

## Test plan
- [ ] <step>

Fixes #<issue>
EOF
)"

# 4. Monitor CI (built-in; blocks until terminal state)
gh pr checks --watch
```

For updating an existing PR, just `git push` + (optionally) `gh pr edit <N> --body "..."`.

## Special Cases

### Claude Development Branch

For the persistent `claude/development` branch:

- PRs should NOT delete the branch after merge — use `gh pr merge <N> --merge` WITHOUT `--delete-branch`
- After merge, update the branch instead of removing worktree:

  ```bash
  cd "$CLAUDE_LEARNING_HUB"   # or the claude/development worktree path
  git checkout main && git pull origin main
  git checkout claude/development
  git merge main --no-edit -m "Merge main into claude/development after PR merge"
  git push origin claude/development
  ```

### Release Branches

For release branches:

- Create new worktree (don't reuse claude-development)
- Follow semantic versioning
- Include changelog updates
- Tag after merge
