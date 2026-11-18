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

### Changelog Entries (fragments, #660)

- NEVER edit `CHANGELOG.md` in a feature PR. Add a hand-written fragment, `changes/<issue>.<category>.md`, holding one or more `-` bullets and no heading. The categories are `breaking`, `added`, `changed`, `deprecated`, `removed`, `fixed` and `security` (`changes/README.md`).
- A second PR for the same issue uses `changes/<issue>-<n>.<category>.md` (e.g. `623-2.fixed.md`).
- Leave the bullets already under `[Unreleased]` alone. `prepare` releases them with the fragments.
- While 2.x is current, run `python scripts/changelog.py no-breaking` on every PR. It MUST print `0`. A `*.breaking.md` fragment or a `### BREAKING CHANGES` heading fails it.
- `python scripts/changelog.py check` (CI `changelog-validation`) rejects bad fragment names and unknown categories.

### Decision Entries (one file per decision, #679)

- **Before changing a contract, read the relevant decisions.** Run `python scripts/decisions.py index --active` (narrow it with `--symbol <name>` or `--issue <N>`), then open the one to three entries that matter. Do not grep or read the whole log.
- NEVER add an entry to `docs/decisions/DECISIONS.md`. It is a static header. A new decision is a new file, `docs/decisions/entries/YYYY-MM-DD-<issue>-<slug>.md`, written with the `decision-log` skill (its File Convention defines the front matter).
- Amending or superseding an entry: add the link to the new entry's front matter, add the reverse link to the old entry (`amended_by` / `superseded_by`), and set its `status`. Never rewrite an old entry's body.
- Every new entry MUST have `**Applies-to:**`: every governed site, or `none (<why>)` for a policy decision. `check` enforces it (#636). Never add a name to `APPLIES_TO_GRANDFATHERED`; it only shrinks.
- Run `python scripts/decisions.py check` (also in CI and pre-commit). It MUST pass.
- If a merge of `main` brings entries back into `DECISIONS.md` (a branch that predates #679), run `python scripts/decisions.py migrate`. It splits them into files, verifies each body and restores the header. It is idempotent.

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
# MANDATORY: Run ALL tests with coverage (pyproject's addopts enforce the threshold)
uv run pytest --cov=src/pyeye
```

## Using Smart-Commit Agent

**When user says "commit" or similar**, ALWAYS use the smart-commit agent:

```bash
# Instead of manual commands, use:
Agent tool with subagent_type="smart-commit"
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

### Releases

A release is a PR; see `docs/RELEASE.md`.

- Prepare it with `python scripts/changelog.py prepare X.Y.Z`. It collects `[Unreleased]` and the `changes/` fragments into the version section, deletes the fragments and stamps the version into `docs/facts/` (#826). Commit all three: `git add -A CHANGELOG.md changes/ docs/facts/`. NEVER hand-edit the version heading or assemble fragments by hand.
- The commit subject AND the PR title MUST both be exactly `chore(release): vX.Y.Z`. The tag workflow keys on it, and commitizen rejects the non-conventional `release: vX.Y.Z` (#587).
- NEVER tag manually after merging a release PR: `tag-release.yml` tags and publishes. A manual tag races it.
- If `prepare` refuses (e.g. an under-bump against `### BREAKING CHANGES`), fix the version or the notes. Don't work around it.
- NEVER generate CHANGELOG prose from commits (`cz changelog` / `cz bump`); commitizen only lints commit messages (#210).
