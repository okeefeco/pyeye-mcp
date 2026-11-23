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

### 1. Add a changelog fragment with each PR

Every user-facing PR adds a **fragment** instead of editing `CHANGELOG.md`
(#660): a file `changes/<issue>.<category>.md` holding one or more `-` bullets.
A second PR for the same issue uses a suffix, `changes/<issue>-2.<category>.md`.
The category picks the Keep a Changelog heading: `breaking`
(`### BREAKING CHANGES`, with a "Required action" note), `added`, `changed`,
`deprecated`, `removed`, `fixed` or `security`. `changes/README.md` has the
table. Because no two PRs edit the same lines, parallel PRs no longer conflict
over `CHANGELOG.md`.

Entries are still written by hand, while the reasoning is fresh, and reviewed
with the code. Nothing generates them from commits (#210).

Bullets already under `[Unreleased]` from before fragments existed stay where
they are; `prepare` releases them together with the fragments.

While 2.x is current, no change may be breaking. Check with:

```bash
python scripts/changelog.py no-breaking   # prints the count; exits 1 if any
```

It counts a `### BREAKING CHANGES` heading under `[Unreleased]` and every
`*.breaking.md` fragment.

### 2. Verify on real codebases

Before opening the release PR, fresh agents run the release candidate (current
`main`) on real projects at pinned commits, and file what pyeye gets wrong (#1140).
This is the dogfooding practice: the unit suite can't see how pyeye behaves on a
real codebase, and this run is how #1125, #1126 and #1159 were found.

Run it with the `pyeye-verify` skill (`.claude/skills/pyeye-verify/`) on at least the
two release-pass scenarios from the `pyeye-scenarios` skill:

- `poetry`: Poetry 2.5.2, a `src/`-layout project;
- `scrapy`: Scrapy 2.20.0, a plain tree.

`multirepo-namespace` (in the repository, no network) covers namespace packages; add
it when namespace or config code changed.

The skill has the steps. In outline:

1. Provision each scenario at its pin, and **copy it outside the pyeye
   repository**. Clone pyeye at the commit under test.
2. Run everything against a **fresh server** on that commit:
   `claude --plugin-dir <pyeye clone>`, started from the scenario copy. Never use a
   long-lived session's server, which runs the code it started on.
3. Run the scenario's probe suite and round-trip probe, and diff them against its
   latest baseline record (`.claude/skills/pyeye-scenarios/baselines/`).
4. Run its task trial: the discovery task, answered by a grep-only control and by
   an agent with the `python-explore` skill and pyeye.

The run passes when:

- no probe has **regressed** from its baseline (a ✅ row now failing);
- the round-trip probe finds no more misses than the baseline;
- in each task trial, the skill-and-pyeye arm is **at least as accurate** as the
  control. It may cost more tokens.

Every confirmed defect is reproduced on current `main`, minimised where possible, and
filed as an issue before release. A regression blocks the release until it's fixed or
the maintainer accepts it. A newly found defect that isn't a regression is filed and
doesn't block. Write the run up as a short dated report,
`docs/audits/YYYY-MM-DD-structured-verification.md`, and record any changed probe
result as a new baseline record (never by editing an old one). Commit both with the
release PR, or in a PR of their own before it.

A scheduled run between releases is optional. Recommended: a monthly run, so a
regression isn't found only on release day.

### 3. Open the release PR

`X.Y.Z` stands for the new version, which must be newer than the latest tag
(`git tag -l 'v*' --sort=-v:refname | head -1`).

```bash
git checkout -b release/vX.Y.Z origin/main

# Collect [Unreleased] and the changes/ fragments into "## [X.Y.Z] - <today>",
# leave a fresh [Unreleased], delete the fragments, and stamp the version into
# the docs-facts ledgers in docs/facts/
python scripts/changelog.py prepare X.Y.Z

git add -A CHANGELOG.md changes/ docs/facts/
git commit -m "chore(release): vX.Y.Z"
git push -u origin release/vX.Y.Z
gh pr create --title "chore(release): vX.Y.Z" --body "Release vX.Y.Z. See CHANGELOG.md."
```

`prepare` builds the release section from the bullets already under
`[Unreleased]` (kept verbatim, first) and then the fragments (by issue number).
Headings come in a fixed order: BREAKING CHANGES, Added, Changed, Deprecated,
Removed, Fixed, Security, then any other heading `[Unreleased]` had. Because it
rewrites `CHANGELOG.md`, the release PR always touches it, which is what
`tag-release.yml` triggers on.

`prepare` also replaces every `"unreleased"` in `docs/facts/removed.json`
(`removed_in`) and `docs/facts/uncovered.json` (`first_seen`) with the version, so
each removed name and each newly uncovered fact records the release it shipped in
(#826). A checkout without those files is left alone.

`prepare` refuses to:

- release when `[Unreleased]` is empty and there are no fragments
- run with an invalid fragment (it then changes nothing)
- reuse or go below an existing version (section or tag)
- under-bump: `### BREAKING CHANGES` (or a `breaking` fragment) needs a major
  bump (a minor one before 1.0), and `### Added` (or an `added` fragment) needs
  at least a minor one

The commit subject and the PR title **must** both be `chore(release): vX.Y.Z`.
It has to be a conventional commit, because the commitizen `commit-msg` hook
rejects anything else. PRs are squash-merged, and the repository uses the PR
title as the squash commit's subject, so the PR title is what lands on `main`;
keeping the commit subject identical avoids any doubt about which one counts.
Review the promoted section like any other change; this is the last chance to
edit the release notes.

### 4. Merge it

On the merge to `main`, `.github/workflows/tag-release.yml`:

1. reads the newest released version in `CHANGELOG.md` (`changelog.py pending-release`);
2. if it has no tag **and** the merge came from a PR titled `chore(release): vX.Y.Z`,
   tags that commit `vX.Y.Z`. PRs are squash-merged with the PR title as the
   commit subject. The workflow also recognises a merge commit's
   `Merge pull request #N from …` form, but merge commits are disabled on
   this repository;
3. dispatches `release.yml` on the new tag.

**Merge queue (#649).** `main` merges through GitHub's merge queue with the squash
method. v2.1.0 (#821) was the first release through the queue; its squash subject
was the PR title plus `(#N)`, which `tag-release.yml` accepts: it only needs the
subject to start with `chore(release): vX.Y.Z`, and that is both the release PR's
title and the subject of the commit you make after `changelog.py prepare`. Keep
extra commits on a release PR after that one. If the subject doesn't start with
`chore(release): vX.Y.Z`, nothing is tagged and nothing is published. Fix the
workflow or setting forward rather than tagging by hand.

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

Only when `tag-release.yml` did not tag a merged release PR (check
`git tag -l vX.Y.Z`); never alongside it, because a hand-pushed tag races the
workflow.

Pushing a tag by hand still runs `release.yml` directly, but the version must
already have a `CHANGELOG.md` section:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

### CHANGELOG checks in CI

`python scripts/changelog.py check` runs on every PR. It requires that:

- the headings are well-formed and `[Unreleased]` comes first
- released sections are dated, non-empty, unique and newest-first
- every `v*` tag has a section
- every section has a tag, except the newest, which may be a pending release
- every file in `changes/` other than `README.md` is a valid fragment: a known
  category, a `<issue>[-<n>].<category>.md` name, and content that starts with a
  `-` bullet and has no headings

## How Versioning Works

### During Development

```bash
# Check current version
uv run python -m setuptools_scm
# Output: 0.2.1.dev0+g1234abc.d20250826

# Version is available in code
uv run python -c "from pyeye import __version__; print(__version__)"
```

### In Tagged Releases

```bash
# At tag v0.3.0
uv run python -m setuptools_scm
# Output: 0.3.0

# Built packages have clean version
ls dist/
# pyeye_mcp-0.3.0-py3-none-any.whl  (and pyeye_mcp-0.3.0.tar.gz)
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

## Migration Notes

Previous version management files removed:

- `.github/workflows/dev-version.yml` - No longer needed
- `scripts/check_version.py` - Obsolete
- `scripts/validate_version_format.py` - Obsolete
- Version consistency tests - Unnecessary

Version now comes from git tags via setuptools_scm!
