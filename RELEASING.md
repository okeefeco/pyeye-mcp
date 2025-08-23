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

## Release Workflow

### Prerequisites

Ensure you have:

- Push access to the repository
- Commitizen installed (`uv pip install commitizen`)
- All tests passing
- Clean working directory

### Steps to Release

1. **Update version using commitizen**

   ```bash
   # For automatic version bump based on commits
   cz bump --changelog

   # Or specify version type
   cz bump --increment PATCH  # or MINOR, MAJOR
   ```

2. **Review the generated CHANGELOG**

   ```bash
   # Commitizen will create/update CHANGELOG.md
   # Review and edit if needed
   git add CHANGELOG.md
   git commit --amend
   ```

3. **Push changes with tags**

   ```bash
   git push origin main
   git push origin --tags
   ```

4. **Create GitHub Release**

   ```bash
   # Using GitHub CLI
   gh release create v$(cz version --project) \
     --title "v$(cz version --project)" \
     --notes-from-tag
   ```

5. **Publish to PyPI** (when ready)

   ```bash
   # Build the package
   uv build

   # Upload to PyPI (requires PyPI credentials)
   uv publish
   ```

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

- [ ] All tests pass: `uv run pytest`
- [ ] Pre-commit hooks pass: `pre-commit run --all-files`
- [ ] Documentation is updated
- [ ] CLAUDE.md reflects any workflow changes
- [ ] Breaking changes have migration guides
- [ ] Version number makes sense per SemVer
- [ ] Branch protection rules are satisfied

## GitHub Actions (Future)

Consider adding workflows for:

- Automatic changelog generation on PR merge
- Release creation on version tag push
- PyPI publishing on GitHub release
- Version bump PR creation

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
