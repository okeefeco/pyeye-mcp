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

This project uses **squash merge only** (#607). Each PR lands on `main` as ONE commit whose subject is the PR title. The repo enforces it: merge commits and rebase merges are disabled, the squash title is always the PR title, and merged head branches are deleted automatically.

### Consequences You MUST Account For

- **The PR title IS the commit subject on `main`.** It MUST be a valid conventional commit (`type(scope): summary (#N)`). Release PRs MUST be titled exactly `chore(release): vX.Y.Z`, because `tag-release.yml` keys on it.
- **Branch commits never reach `main`.** NEVER test "is it merged?" with commit ancestry (`git branch -r --contains`, `git merge-base --is-ancestor`, `git branch -d`). After a squash merge they report "not merged". Use the PR state instead (see `04-agent-triggers.md`).
- **Branch commits are still the review history.** Keep them clean and logical; "fix" commits during review are fine, because they collapse on merge.
- **Never force push to shared branches** - Especially after others have reviewed or pulled

### Merging Process

When your PR is approved:

```bash
gh pr merge <PR-NUMBER> --squash

# Disabled on this repo; don't use:
# gh pr merge <PR-NUMBER> --merge   ❌
# gh pr merge <PR-NUMBER> --rebase  ❌
```
