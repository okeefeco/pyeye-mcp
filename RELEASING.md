# Release Process

## Versioning Strategy

This project follows [Semantic Versioning](https://semver.org/) (SemVer):

- **MAJOR** version (1.0.0 → 2.0.0): Breaking API changes
- **MINOR** version (0.1.0 → 0.2.0): New features, backwards compatible
- **PATCH** version (0.1.0 → 0.1.1): Bug fixes, backwards compatible

### Version Bumping Guidelines

#### Increment PATCH version when you

- Fix bugs without changing API
- Update documentation
- Improve performance without changing behavior
- Update dev dependencies

#### Increment MINOR version when you

- Add new MCP tools
- Add new plugin support
- Add new configuration options
- Add backwards-compatible features
- Deprecate features (but not remove)

#### Increment MAJOR version when you

- Remove deprecated features
- Change tool signatures or behavior
- Change configuration format incompatibly
- Require newer Python version
- Make breaking changes to plugin API

## Development Versioning Strategy

We use a **development versioning strategy** to clearly distinguish between unreleased development code and published releases.

### Version Types

#### Development Versions (Main Branch)

- Format: `X.Y.Z.dev0`, `X.Y.Z.dev1`, etc.
- **Purpose**: Clearly identify unreleased development code
- **Auto-increment**: Automatically bumped on each main branch commit
- **Examples**: `0.1.0.dev0`, `0.1.1.dev5`, `1.0.0.dev12`

#### Pre-release Versions

- **Alpha**: `X.Y.ZaN` (e.g., `0.2.0a0`, `0.2.0a1`)
- **Beta**: `X.Y.ZbN` (e.g., `0.2.0b0`, `0.2.0b1`)
- **Release Candidate**: `X.Y.ZrcN` (e.g., `0.2.0rc0`, `0.2.0rc1`)

#### Release Versions

- Format: `X.Y.Z` (clean semantic versions)
- **Purpose**: Tagged releases available on GitHub and PyPI
- **Examples**: `0.1.0`, `0.2.0`, `1.0.0`

### Development Workflow

#### Continuous Development

```bash
# Main branch always has development versions
0.1.0.dev0  →  commit  →  0.1.0.dev1  →  commit  →  0.1.0.dev2
```

#### Release Preparation

```bash
# Commitizen removes .dev suffix and creates clean version
0.1.0.dev15  →  cz bump  →  0.1.0  →  tag v0.1.0  →  GitHub Release
```

#### Post-Release

```bash
# Automatic bump to next development version
v0.1.0 released  →  auto-bump  →  0.1.1.dev0  →  development continues
```

### Benefits

- **Clear Identification**: `pip list` shows `0.1.0.dev5` vs `0.1.0`
- **Proper Pip Handling**: Development versions are treated as pre-releases
- **User Clarity**: No confusion about installed version vs release
- **Testing**: Easy to identify which development version has issues
- **CI/CD**: Build artifacts clearly labeled with development versions

### Automated Version Management

#### Main Branch Commits

- **Trigger**: Any commit to main branch
- **Action**: Auto-increment dev version (e.g., `0.1.0.dev0` → `0.1.0.dev1`)
- **Workflow**: `.github/workflows/dev-version.yml`

#### Release Process

- **Trigger**: Push version tag (`v*`)
- **Action**: Create release, then bump to next dev version
- **Workflow**: `.github/workflows/release.yml`

## Release Workflow

We use **automated GitHub Actions workflows** for consistent, reliable releases. The process involves two workflows:

1. **Manual**: Version bumping and tagging (still manual for control)
2. **Automated**: Release creation and validation (fully automated)

### Prerequisites

Ensure you have:

- Push access to the repository
- Commitizen installed (`uv pip install commitizen`)
- All tests passing locally
- Clean working directory

### Automated Release Process

#### 1. **Version Bump and Tag Creation** (Manual)

```bash
# Update version using commitizen (removes .dev suffix, creates clean release version)
cz bump --changelog

# This automatically:
# - Converts 0.1.0.dev15 → 0.1.0 (or increments: 0.1.0 → 0.1.1)
# - Updates version in pyproject.toml and src/pycodemcp/__init__.py
# - Creates/updates CHANGELOG.md
# - Creates a git commit
# - Creates a version tag (e.g., v0.1.0)
```

#### 2. **Trigger Automated Release** (Push the Tag)

```bash
# Push the version commit and tag to trigger the release workflow
git push origin main --tags
```

#### 3. **Automated Release Pipeline** (GitHub Actions)

Once the tag is pushed, the release workflow automatically:

✅ **Validates the Release:**

- Runs version consistency tests
- Verifies tag matches package version
- Executes full test suite with 85% coverage requirement
- Performs type checking with mypy
- Runs security checks with bandit
- Validates all pre-commit hooks

✅ **Creates GitHub Release:**

- Generates changelog from git history and commitizen
- Builds Python package (wheel + source distribution)
- Creates GitHub release with auto-generated notes
- Uploads package artifacts to the release
- Detects pre-release versions (alpha/beta/rc) automatically

✅ **Post-Release Development Setup:**

- Automatically bumps main branch to next development version
- Example: `v0.1.0` released → main branch becomes `0.1.1.dev0`
- Ensures continued development is clearly distinguished from release
- Reports success/failure status and provides links to created release

### Manual PyPI Publishing (Optional)

After the automated release, you can optionally publish to PyPI:

```bash
# Download artifacts from GitHub release or build locally
uv build

# Publish to PyPI (when PyPI account is ready)
uv publish dist/*
```

### Release Validation

The automated workflow ensures every release:

- ✅ Has consistent versions across all files
- ✅ Passes all tests with required coverage
- ✅ Passes type checking and security scans
- ✅ Includes proper changelog entries
- ✅ Has built packages attached to release

### Pre-release Versions

For alpha/beta releases:

```bash
# Manually set pre-release version
cz bump --prerelease alpha  # Creates 0.2.0a0
cz bump --prerelease beta   # Creates 0.2.0b0
cz bump --prerelease rc     # Creates 0.2.0rc0
```

## Changelog Management

The CHANGELOG.md is automatically maintained by commitizen based on conventional commits:

- `feat:` commits → Added section
- `fix:` commits → Fixed section
- `docs:` commits → Documentation section
- `perf:` commits → Performance section
- `refactor:` commits → Refactored section
- `BREAKING CHANGE:` in footer → Breaking Changes section

### Manual Changelog Edits

After running `cz bump --changelog`, you can edit CHANGELOG.md to:

- Add migration guides for breaking changes
- Highlight important features
- Add acknowledgments
- Fix formatting

## Release Checklist

Before releasing, ensure:

- [ ] All tests pass locally: `uv run pytest`
- [ ] Pre-commit hooks pass: `pre-commit run --all-files`
- [ ] Documentation is updated
- [ ] CLAUDE.md reflects any workflow changes
- [ ] Breaking changes have migration guides
- [ ] Version number makes sense per SemVer
- [ ] Ready for automated validation (workflow will re-verify all checks)

**Note**: The automated release workflow will re-run all validation steps, so local failures will prevent release creation.

## Automated GitHub Actions Workflows

✅ **Implemented Workflows:**

- ✅ **Release Workflow** (`.github/workflows/release.yml`)
  - Triggers on version tag push (`v*`)
  - Validates release with full test suite
  - Creates GitHub release with changelog
  - Uploads package artifacts
  - **Post-release**: Auto-bumps main to next dev version

- ✅ **Development Version Workflow** (`.github/workflows/dev-version.yml`)
  - Triggers on main branch commits
  - Auto-increments development version numbers
  - Maintains clear dev/release distinction
  - Skips version/release commits to avoid loops

- ✅ **CI Workflow** (`.github/workflows/ci.yml`)
  - Runs on every PR and main branch push
  - Multi-platform testing (Linux, Windows, macOS)
  - Coverage reporting and type checking
  - Security scanning with bandit

🚀 **Future Enhancements:**

- PyPI publishing integration (when PyPI account available)
- Automatic dependency updates
- Performance regression detection
- Release announcement automation
- Version bump PR creation

## Troubleshooting Automated Releases

### Common Release Workflow Failures

#### Version Mismatch Error

```text
Version mismatch: package=0.1.0, tag=0.1.1
```

**Solution**: Ensure the git tag matches the version in `pyproject.toml` and `__init__.py`. Re-run `cz bump` to sync versions.

#### Test Failures

```text
pytest --cov-fail-under=85 failed
```

**Solution**: Fix failing tests locally first. The workflow requires 85% coverage and all tests passing.

#### Type Checking Failures

```text
mypy src/pycodemcp --ignore-missing-imports failed
```

**Solution**: Fix type errors locally. Run `mypy src/pycodemcp` to see specific issues.

#### Security Check Failures

```text
bandit -r src/ -ll failed
```

**Solution**: Address security issues flagged by bandit. Review the specific findings in the workflow logs.

#### Pre-commit Hook Failures

```text
pre-commit validation failed
```

**Solution**: Run `pre-commit run --all-files` locally and fix any formatting or linting issues.

### Monitoring Release Progress

1. **Check GitHub Actions**: Go to the "Actions" tab in the repository
2. **View Release Workflow**: Look for the workflow triggered by your tag
3. **Monitor Progress**: Watch the validation and release creation steps
4. **Check Release Page**: Successful releases appear on the GitHub releases page

### Manual Intervention

If the automated workflow fails and you need to create a release manually:

```bash
# After fixing issues, manually create the release
gh release create v0.1.1 \
  --title "Release v0.1.1" \
  --notes "Release notes here" \
  dist/*.whl dist/*.tar.gz
```

## Rollback Process

If a release has issues:

1. **Delete the tag locally and remotely**

   ```bash
   git tag -d v0.1.1
   git push origin :refs/tags/v0.1.1
   ```

2. **Fix the issue**

3. **Re-release with patch bump**

   ```bash
   cz bump --increment PATCH
   ```

## Version Locations

Version is maintained in:

- `pyproject.toml` - Single source of truth for package metadata
- `src/pycodemcp/__init__.py` - Package version accessible at runtime
- Git tags - Version control markers
- CHANGELOG.md - Version history

Commitizen automatically keeps `pyproject.toml` and `__init__.py` in sync via `version_files` configuration. When you run `cz bump`, both files are updated simultaneously to prevent version drift.
