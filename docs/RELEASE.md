# Release Process Documentation

## Overview

This project uses **setuptools_scm** for version management. Version numbers are automatically derived from git tags - no manual version bumping required!

## Version Strategy

We follow [Semantic Versioning](https://semver.org/):

- **Major (X.0.0)**: Breaking API changes
- **Minor (0.X.0)**: New features, backward compatible
- **Patch (0.0.X)**: Bug fixes, backward compatible

Development versions are automatically generated:

- Tagged release: `0.2.0`
- Development after tag: `0.2.1.dev0+g1234abc.d20250826`

## Release Process

A release is a pull request. Merging it tags the release and publishes it (#583).

### 1. Keep `[Unreleased]` current

Every user-facing PR adds its entry under `## [Unreleased]` in `CHANGELOG.md`,
in Keep a Changelog form (`### Added`, `### Changed`, `### Fixed`,
`### Removed`, or `### BREAKING CHANGES` with a "Required action" note).
Entries are written by hand, while the reasoning is fresh, and reviewed with the
code.

### 2. Open the release PR

```bash
git checkout -b release/v2.0.0 origin/main

# Promote [Unreleased] to "## [2.0.0] - <today>" and start a fresh [Unreleased]
python scripts/changelog.py prepare 2.0.0

git commit -am "chore(release): v2.0.0"
git push -u origin release/v2.0.0
gh pr create --title "chore(release): v2.0.0" --body "Release v2.0.0. See CHANGELOG.md."
```

`prepare` refuses to:

- release an empty `[Unreleased]`
- reuse or go below an existing version (section or tag)
- under-bump: `### BREAKING CHANGES` needs a major bump (a minor one before
  1.0), and `### Added` needs at least a minor one

The commit subject and the PR title **must** both be `chore(release): vX.Y.Z`.
It has to be a conventional commit, because the commitizen `commit-msg` hook
rejects anything else. And the two have to match, because a single-commit
squash uses the commit subject. Review the promoted section like any
other change; this is the last chance to edit the release notes.

### 3. Merge it

On the merge to `main`, `.github/workflows/tag-release.yml`:

1. reads the newest released version in `CHANGELOG.md` (`changelog.py pending-release`);
2. if it has no tag **and** the merge came from a PR titled `chore(release): vX.Y.Z`,
   tags that commit `vX.Y.Z`. Squash merges and merge commits both work: the
   PR title is the squash subject, or the line after a merge commit's
   `Merge pull request #N from …` subject;
3. dispatches `release.yml` on the new tag.

`release.yml` then tests, builds, creates the GitHub Release, and publishes to
TestPyPI and PyPI. The release body is the version's `CHANGELOG.md` section
(`changelog.py notes`), followed by GitHub's generated PR list. A tag without a
CHANGELOG section fails the release early.

Both guards in step 2 are deliberate: an ordinary PR that adds a version heading
by mistake never tags anything, and re-running the workflow on an already
tagged version does nothing.

> **Why dispatch:** a tag pushed with the workflow's `GITHUB_TOKEN` does not
> trigger `on: push` workflows, but `workflow_dispatch` always creates a run.
> **Why not a reusable workflow:** PyPI trusted publishing does not support
> reusable workflows, so `release.yml` must run as a top-level workflow.

### Manual tag (fallback)

Pushing a tag by hand still runs `release.yml` directly, but the version must
already have a `CHANGELOG.md` section:

```bash
git tag -a v2.0.1 -m "Release v2.0.1"
git push origin v2.0.1
```

### CHANGELOG checks in CI

`python scripts/changelog.py check` runs on every PR. It requires that:

- the headings are well-formed and `[Unreleased]` comes first
- released sections are dated, non-empty, unique and newest-first
- every `v*` tag has a section
- every section has a tag, except the newest, which may be a pending release

## How Versioning Works

### During Development

```bash
# Check current version
uv run python -m setuptools_scm
# Output: 0.2.1.dev0+g1234abc.d20250826

# Version is available in code
python -c "from pyeye import __version__; print(__version__)"
```

### In Tagged Releases

```bash
# At tag v0.3.0
uv run python -m setuptools_scm
# Output: 0.3.0

# Built packages have clean version
ls dist/
# python_code_intelligence_mcp-0.3.0-py3-none-any.whl
```

## No More Version Sync Issues

With setuptools_scm:

- ✅ No version in pyproject.toml to update
- ✅ No version in **init**.py to maintain
- ✅ No commitizen version tracking (commitizen only lints commit messages; see #210)
- ✅ No dev version workflows
- ✅ No post-release version bumps
- ✅ Version always matches git state

## Building Packages

```bash
# Build distributions (uv provides the build frontend; setuptools_scm comes
# from [build-system].requires)
uv build

# Files created in dist/
ls dist/
```

## Troubleshooting

### No Version Found

If setuptools_scm can't find version:

```bash
# Ensure you have at least one tag
git tag -a v0.1.0 -m "Initial release"
git push origin v0.1.0
```

### Version Shows Unknown

If `__version__` shows "0.0.0+unknown":

```bash
# Reinstall in development mode
uv sync --frozen
```

### Clean vs Dev Versions

- Clean version: Only at tagged commits (v0.3.0 → 0.3.0)
- Dev version: Any commit after tag (0.3.1.dev5+g1234abc)

## Benefits of This Approach

1. **Single Source of Truth**: Git tags
2. **No Manual Sync**: Version derived automatically
3. **Cleaner History**: No version bump commits
4. **Simpler CI/CD**: No complex workflows needed
5. **Industry Standard**: Used by pytest, pip, pandas

## Migration Notes

Previous version management files removed:

- `.github/workflows/dev-version.yml` - No longer needed
- `scripts/check_version.py` - Obsolete
- `scripts/validate_version_format.py` - Obsolete
- Version consistency tests - Unnecessary

Version now comes from git tags via setuptools_scm!
