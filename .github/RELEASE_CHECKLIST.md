# Release Checklist

## Pre-Release Verification

- [ ] All tests passing locally with coverage >85%
- [ ] Version numbers synchronized across:
  - [ ] pyproject.toml (project.version)
  - [ ] pyproject.toml (tool.commitizen.version)
  - [ ] src/pycodemcp/__init__.py
- [ ] CHANGELOG.md updated with release notes
- [ ] No uncommitted changes on main branch

## Release Process

1. [ ] Create release branch: `git checkout -b release/X.Y.Z`
2. [ ] Update version from dev (X.Y.Z.dev0) to release (X.Y.Z)
3. [ ] Run version consistency tests: `pytest tests/test_version_consistency.py -v --no-cov`
4. [ ] Update CHANGELOG.md - move Unreleased to version section
5. [ ] Create PR and merge to main
6. [ ] Create and push tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
7. [ ] Push tag to trigger workflow: `git push origin vX.Y.Z`
8. [ ] Monitor workflow progress: `gh run watch`
9. [ ] Verify release artifacts on GitHub

## Post-Release

- [ ] Verify automatic version bump to X.Y.(Z+1).dev0
- [ ] Verify distribution files uploaded correctly:
  - [ ] Wheel: `python_code_intelligence_mcp-X.Y.Z-py3-none-any.whl`
  - [ ] Source: `python_code_intelligence_mcp-X.Y.Z.tar.gz`
- [ ] Test installation: `pip install python-code-intelligence-mcp==X.Y.Z`
- [ ] Announce release if needed
- [ ] Close release milestone (if applicable)

## Emergency Procedures

### If Release Workflow Fails

1. __Check workflow logs__:

   ```bash
   gh run list --workflow=release.yml --limit=1
   gh run view <run-id>
   ```

2. __Common issues and fixes__:
   - __Distribution filename mismatch__: Check underscores vs hyphens (PEP 625/427)
   - __Version consistency test coverage__: Use `--no-cov` flag
   - __Changelog generation errors__: Check commitizen configuration

3. __To retry a failed release__:

   ```bash
   # Delete the tag locally and remotely
   git tag -d vX.Y.Z
   git push origin :refs/tags/vX.Y.Z

   # Fix the issue, then recreate and push tag
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

### Force Merge for Critical Fixes

**Only use when absolutely necessary during release**:

```bash
# Requires admin privileges or PAT with appropriate permissions
gh pr merge <PR-NUMBER> --admin --merge
```

## Troubleshooting

### Version Synchronization Issues

- Ensure all three locations have identical versions
- Use `scripts/check_version_sync.py` to validate (if available)

### Changelog Problems

- Commitizen doesn't support `--file-format md`
- Use `cz changelog --dry-run` to preview
- Maintain CHANGELOG.md manually during development

### Distribution File Naming

- __PyPI project names__: Use hyphens (python-code-intelligence-mcp)
- __Distribution files__: Use underscores (python_code_intelligence_mcp)
- References: [PEP 625](https://peps.python.org/pep-0625/), [PEP 427](https://peps.python.org/pep-0427/)

## Automation Scripts

### Quick Status Check

```bash
# Check current version
grep "^version = " pyproject.toml

# Check recent tags
git tag -l "v*" | tail -5

# Check workflow status
gh run list --workflow=release.yml --limit=3
```

### Version Bump Helper

```bash
# For patch release (X.Y.Z -> X.Y.Z+1)
cz bump --increment PATCH

# For minor release (X.Y.Z -> X.Y+1.0)
cz bump --increment MINOR

# For major release (X.Y.Z -> X+1.0.0)
cz bump --increment MAJOR
```

## References

- [Release Workflow](.github/workflows/release.yml)
- [Contributing Guidelines](../CONTRIBUTING.md)
- [Python Packaging Standards](https://packaging.python.org/)
