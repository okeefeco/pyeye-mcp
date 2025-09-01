<!--
Audience: Claude Code
Purpose: Define GitHub issue-based workflow requirements
When to update: When workflow processes change
-->

# GitHub Issue-Based Workflow

## 🚨 CRITICAL: All Work MUST Follow This Process

### BEFORE ANY WORK BEGINS

```bash
# Check for existing issues
gh issue list --state open

# If no issue exists for the work, CREATE ONE or ask user to create it
gh issue create --title "Brief description" --body "Details"
```

### BRANCH STRATEGY (REQUIRED)

```bash
# Format: type/issue-number-brief-description
# Examples:
git checkout -b fix/22-merge-strategy-docs
git checkout -b feat/23-add-validation
git checkout -b docs/24-update-readme
```

### DISCOVERED PROBLEMS

If you find ANY bug, issue, or improvement opportunity:

1. STOP current work
2. Create or request issue creation
3. Only proceed with fix after issue exists

Example response: "I found a bug in the validation logic. Let me create issue #25 to track this before fixing it."

### VALIDATION BEFORE STARTING

```bash
# ALWAYS run these checks before starting work:
gh issue view <issue-number>  # Verify issue exists and understand requirements
git status                     # Ensure clean working directory
git checkout main              # Start from main
git pull origin main           # Get latest changes
git checkout -b <branch-name>  # Create feature branch
```

### PR CREATION

- Always reference issue: "Fixes #<issue-number>" or "Addresses #<issue-number>"
- PR title should match branch naming convention
- Never merge without issue reference

## Examples of Required Workflow

❌ **WRONG**: "I'll fix this typo real quick"
✅ **RIGHT**: "I found a typo. Let me create issue #26 for this, then fix it on branch `docs/26-fix-typo`"

❌ **WRONG**: Starting work immediately when user mentions a problem
✅ **RIGHT**: "I understand the issue. Let's create a GitHub issue to track this properly, then I'll work on it"

❌ **WRONG**: Making changes on main branch
✅ **RIGHT**: Always create issue-specific feature branch

## Merge Strategy

### Our Approach

This project uses **regular merge commits** (not squash merges) to preserve development history and maintain full traceability.

### Why We Don't Use Squash Merge

- **Preserves development history**: Each commit tells part of the story
- **Better debugging**: `git bisect` works more effectively with granular commits
- **Proper attribution**: Individual commits show the evolution of the solution
- **No tracking issues**: Git properly recognizes merged branches (no confusing warnings)

### Guidelines

1. **Keep commits clean and logical** - Since we preserve history, make each commit meaningful
2. **Use descriptive commit messages** - Follow our conventional commit format
3. **It's OK to have "fix" commits** - They show the review process and iterations
4. **Never force push to shared branches** - Especially after others have reviewed or pulled

### Merging Process

When your PR is approved:

```bash
# Regular merge (preserves all commits)
gh pr merge <PR-NUMBER> --merge

# NOT recommended:
# gh pr merge <PR-NUMBER> --squash  ❌
# gh pr merge <PR-NUMBER> --rebase  ❌ (especially after push)
```
