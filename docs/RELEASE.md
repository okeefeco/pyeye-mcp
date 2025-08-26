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

## Simplified Release Process

### 1. Prepare for Release

```bash
# Ensure on main with latest changes
git checkout main
git pull origin main

# Run tests
uv run pytest

# Update CHANGELOG.md with release notes
# Move items from "Unreleased" to new version section
```

### 2. Create Release Tag

```bash
# Create annotated tag (version is derived from this!)
git tag -a v0.3.0 -m "Release v0.3.0

Summary of changes:
- Feature X added
- Bug Y fixed
See CHANGELOG.md for details"

# Push tag to trigger release workflow
git push origin v0.3.0
```

### 3. Release Workflow

The GitHub Actions workflow automatically:

1. Validates tests pass
2. Builds distributions (wheel and sdist)
3. Creates GitHub release
4. Uploads distribution files

That's it! No version files to update, no post-release bumps needed.

## How Versioning Works

### During Development

```bash
# Check current version
uv run python -m setuptools_scm
# Output: 0.2.1.dev0+g1234abc.d20250826

# Version is available in code
python -c "from pycodemcp import __version__; print(__version__)"
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
- ✅ No commitizen version tracking
- ✅ No dev version workflows
- ✅ No post-release version bumps
- ✅ Version always matches git state

## Building Packages

```bash
# Install build tools
uv pip install build setuptools_scm[toml]

# Build distributions
uv run python -m build

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
uv pip install -e .
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
