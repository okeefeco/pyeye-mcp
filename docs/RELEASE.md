# Release Process Documentation

## Overview

This document provides detailed instructions for releasing new versions of Python Code Intelligence MCP Server. Our release process is automated through GitHub Actions, but requires careful preparation and monitoring.

## Release Strategy

### Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- **Major (X.0.0)**: Breaking API changes
- **Minor (0.X.0)**: New features, backward compatible
- **Patch (0.0.X)**: Bug fixes, backward compatible
- **Dev (X.Y.Z.dev0)**: Development versions between releases

### Release Frequency

- **Patch releases**: As needed for critical bug fixes
- **Minor releases**: Monthly or when significant features are ready
- **Major releases**: Annually or for breaking changes

## Detailed Release Process

### 1. Pre-Release Preparation

#### Verify Clean State

```bash
# Ensure you're on main branch with latest changes
git checkout main
git pull origin main
git status  # Should show clean working directory
```

#### Run Full Test Suite

```bash
# Run all tests with coverage
pytest --cov=src/pycodemcp --cov-fail-under=85

# Run version consistency tests specifically
pytest tests/test_version_consistency.py -v --no-cov
```

#### Update Changelog

Edit `CHANGELOG.md` to move items from "Unreleased" to the new version section:

```markdown
## [Unreleased]

## [0.2.0] - 2024-01-15
### Added
- New feature descriptions
### Fixed
- Bug fix descriptions
```

### 2. Version Update Process

#### Manual Method

Update version in three locations:

1. `pyproject.toml` - `version = "X.Y.Z"`
2. `pyproject.toml` - `[tool.commitizen] version = "X.Y.Z"`
3. `src/pycodemcp/__init__.py` - `__version__ = "X.Y.Z"`

#### Using Commitizen (Recommended)

```bash
# For patch release
cz bump --increment PATCH --no-tag

# For minor release
cz bump --increment MINOR --no-tag

# For major release
cz bump --increment MAJOR --no-tag
```

### 3. Create Release Branch

```bash
# Create release branch
git checkout -b release/X.Y.Z

# Commit version changes
git add -A
git commit -m "chore: prepare release vX.Y.Z"

# Push branch
git push -u origin release/X.Y.Z
```

### 4. Create and Merge PR

```bash
# Create PR
gh pr create \
  --title "Release vX.Y.Z" \
  --body "Prepare release vX.Y.Z\n\nSee CHANGELOG.md for details." \
  --base main

# After review and approval
gh pr merge <PR-NUMBER> --merge
```

### 5. Create and Push Release Tag

```bash
# Switch back to main and pull latest
git checkout main
git pull origin main

# Create annotated tag
git tag -a vX.Y.Z -m "Release vX.Y.Z

$(cat CHANGELOG.md | sed -n '/## \[X.Y.Z\]/,/## \[/p' | head -n -1)"

# Push tag to trigger release workflow
git push origin vX.Y.Z
```

### 6. Monitor Release Workflow

```bash
# Watch workflow execution
gh run list --workflow=release.yml --limit=1
gh run watch

# Check release status
gh release view vX.Y.Z
```

## Release Workflow Details

### What the Workflow Does

1. **Validation**:
   - Runs full test suite
   - Checks version consistency
   - Validates changelog exists

2. **Build**:
   - Creates wheel distribution
   - Creates source distribution
   - Generates checksums

3. **Release Creation**:
   - Creates GitHub release
   - Uploads distribution files
   - Generates release notes

4. **Post-Release**:
   - Bumps version to next dev version
   - Creates PR for version bump
   - Updates changelog template

### Workflow Configuration

The release workflow is defined in `.github/workflows/release.yml` and is triggered by:

- Tags matching pattern `v*.*.*`
- Manual workflow dispatch (for testing)

## Troubleshooting

### Common Issues

#### 1. Distribution Filename Mismatch

**Problem**: Workflow expects wrong filename format
**Solution**: Ensure using underscores in distribution filenames (PEP 625/427)

```yaml
asset_path: dist/python_code_intelligence_mcp-X.Y.Z.tar.gz  # Correct
```

#### 2. Version Consistency Test Coverage

**Problem**: Version tests have low coverage (~17%)
**Solution**: Use `--no-cov` flag for these tests:

```bash
pytest tests/test_version_consistency.py -v --no-cov
```

#### 3. Changelog Generation Errors

**Problem**: Commitizen flags don't work as expected
**Solution**: Maintain CHANGELOG.md manually or use:

```bash
cz changelog --dry-run  # Preview changes
```

### Recovery Procedures

#### Delete and Recreate Tag

```bash
# Delete tag locally
git tag -d vX.Y.Z

# Delete tag remotely
git push origin :refs/tags/vX.Y.Z

# Fix issues, then recreate
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

#### Clean Up Failed Release

```bash
# Delete draft release if created
gh release delete vX.Y.Z --yes

# Remove tag
git push origin :refs/tags/vX.Y.Z
git tag -d vX.Y.Z
```

#### Force Merge (Emergency Only)

```bash
# Requires admin privileges
gh pr merge <PR-NUMBER> --admin --merge
```

## Automation Tools

### Release Preparation Script

Located at `scripts/prepare_release.py` (when available):

- Validates prerequisites
- Updates version numbers
- Creates release branch
- Generates PR

### Version Check Script

Located at `scripts/check_version_sync.py` (when available):

- Validates version synchronization
- Reports discrepancies
- Suggests fixes

### Release Status Script

```bash
#!/bin/bash
# scripts/check_release_status.sh
echo "Current version:"
grep "^version = " pyproject.toml

echo "\nRecent releases:"
gh release list --limit=5

echo "\nRecent workflow runs:"
gh run list --workflow=release.yml --limit=5
```

## Best Practices

### Do's

- ✅ Always run full test suite before release
- ✅ Update CHANGELOG.md with clear descriptions
- ✅ Use annotated tags with descriptive messages
- ✅ Monitor workflow execution
- ✅ Test installation after release

### Don'ts

- ❌ Don't skip version consistency checks
- ❌ Don't force push to main branch
- ❌ Don't delete tags without understanding impact
- ❌ Don't release with failing tests
- ❌ Don't use squash merge for release PRs

## Release Metrics

Track these metrics to improve the release process:

- Time from tag to release completion
- Release success rate
- Number of manual interventions
- Post-release issues discovered
- Installation success rate

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Python Packaging User Guide](https://packaging.python.org/)
- [Semantic Versioning](https://semver.org/)
- [PEP 625 - sdist naming](https://peps.python.org/pep-0625/)
- [PEP 427 - wheel naming](https://peps.python.org/pep-0427/)
- [Commitizen Documentation](https://commitizen-tools.github.io/commitizen/)
