# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-08-27

### Added

- Git-based versioning with setuptools_scm - automatic version management from git tags
- Persistent branch support in worktree-manager agent for claude/development workflow

### Changed

- Switched from manual version management to setuptools_scm
- Simplified release process - no more version files to update
- Version now automatically derived from git tags and commits

### Fixed

- CI installation of setuptools_scm before generating version file
- Proper version imports for CI and type checking environments
- Type annotations for version tuple

## [0.1.0] - 2025-08-24

### Added

- Initial release of Python Code Intelligence MCP Server
- Core navigation tools (find_symbol, goto_definition, find_references)
- Multi-project support with LRU caching
- Namespace package resolution across repositories
- File watching with automatic cache updates
- Configuration system (files, env vars, auto-discovery)
- Plugin architecture for framework-specific intelligence
- Django plugin with model/view/URL analysis
- Pydantic plugin with model schema extraction
- Flask plugin with route/blueprint/template analysis
- Module and package analysis tools
- Circular dependency detection
- Connection pooling for optimized multi-project workflows
- Comprehensive test suite
- Pre-commit hooks for code quality
- Documentation and examples

### Fixed

- Author and copyright information corrected

## [0.2.0] - 2025-08-25

### Feat

- enable connection pooling by default for better performance
- add MCP monitoring hooks system for automatic usage tracking
- add persistent branch handling for claude/development workflow
- add PR merging capabilities and composite agent workflows
- add pr-workflow agent for complete PR lifecycle management
- add worktree-manager agent for safe git worktree operations
- add smart-commit agent for intelligent git commit workflow
- add first true Claude Code agent for cross-platform validation
- **agents**: enhance test coverage agent with quality guidelines
- **metrics**: unified metrics system with improved tests
- **metrics**: implement unified metrics collection system
- implement test coverage enhancement agent for systematic improvement
- Complete documentation deployment system setup
- implement release automation agent for end-to-end release management
- **ci**: add version validation to CI pipeline

### Fix

- record cache metrics in ScopedCache to fix 0% hit rate issue
- skip Codecov uploads for Dependabot PRs to prevent CI failures
- add small delay in Windows test for file system sync
- move psutil from dev to main dependencies
- replace DIY atomic operations with filelock for cross-platform compatibility
- implement atomic file operations for Windows compatibility
- resolve defaultdict serialization issue in unified metrics
- properly preserve async functions in fallback decorator
- Make unified metrics import optional to fix CI failures
- Add Windows support for file locking in unified metrics
- **tests**: use sys.executable for Windows CLI test compatibility
- **tests**: handle stderr being None on Windows in CLI test
- **release-automation**: resolve Windows Unicode encoding issues
- **release-automation**: preserve indentation in commitizen version updates
- Properly configure uv virtual environment for docs build
- Remove problematic plugin autosummary entries from docs
- Add --system flag for uv pip install in documentation workflow
- Merge main and update deprecated actions/upload-artifact
- Move docs deployment workflow to correct location
- Update deprecated actions/upload-artifact to v4
- **dogfooding**: implement MCP usage tracking integration
- replace Unicode emojis with ASCII markers for Windows compatibility
- use manual TOML parsing for Python 3.10 compatibility
- improve release process and add worktree safety (issues #162-#165)

## v0.1.0 (2025-08-24)

### Feat

- Update dev workflow to use PAT for branch protection bypass
- Implement development versioning strategy
- Implement automated release workflow
- **dogfooding**: add complete automation for metrics tracking (fixes #138)
- **dogfooding**: implement metrics tracking for MCP usage (fixes #135)
- **guidelines**: add automated checks and documentation to prevent CI failures
- **scope**: implement smart defaults and performance optimizations for namespace packages
- **plugins**: Add namespace package support to all plugin classes
- implement MCP-first dogfooding workflow for development
- Add scope parameter support to 6 core analyzer methods
- Implement core infrastructure for namespace-aware file operations
- Add find_subclasses tool for general inheritance tracking
- Add comprehensive performance monitoring and metrics collection
- **security**: Enable Dependabot for automated dependency updates
- Add configurable performance settings via environment variables
- add re-export tracking to find_symbol tool
- Add module/package listing and dependency analysis tools
- Add workflow_dispatch trigger to CI workflow
- Add coverage percentage badge to README
- Add comprehensive error handling with custom exception hierarchy (#21)
- Add comprehensive input validation and sanitization
- Add CI pipeline status badges to README
- Add comprehensive pre-commit hooks and achieve 100% compliance (#8)
- Add comprehensive pre-commit hooks and achieve 100% compliance
- Add comprehensive pre-commit hooks and achieve 100% compliance

### Fix

- correct changelog generation in release workflow
- disable coverage requirement for version consistency tests in release workflow
- critical syntax error in release workflow
- Update workflow to use DEV_TOKEN instead of ADMIN_PAT
- Simplify dev version workflow for admin bypass
- Fix dev version workflow coverage issue and cleanup test
- Add Python 3.10 compatibility for TOML parsing in tests
- Version synchronization across package files
- resolve find_imports performance and namespace handling issues
- restore default scope to 'all' for backward compatibility
- optimize find_imports performance with ripgrep pre-filtering
- Fix settings import issue causing connection pooling tests to fail
- Address pre-commit hook failures
- Handle PosixPath in get_call_hierarchy errors
- Use as_posix() instead of str() for cross-platform compatibility
- Handle PosixPath serialization in error messages
- ruff linting issues in tests
- synchronize formatter versions and resolve CI failures
- resolve CI failures - black formatting and Windows path tests
- **test**: use as_posix() for cross-platform path comparison in test_list_packages_single_package
- disable cross-platform path pre-commit hook by default
- resolve cross-platform path violations across entire codebase
- **tests**: resolve Windows compatibility issues in test_automation.py
- **scope**: resolve cross-platform path handling and CI performance issues
- **django**: Add scope parameter support and fix duplicate detection
- Update Django plugin tests to use async/await
- specify UTF-8 encoding for Windows compatibility in tests
- simplify dogfooding tests to avoid async execution issues in CI
- update dogfooding tests to handle CI environment differences
- Re-enable test_goto_definition_not_found with proper mocking
- Use POSIX path format for cross-platform template names
- Make tests Windows-compatible
- Resolve paths in tests to handle symlinks and short names on Windows/macOS
- Make decorators async-aware to fix MCP coroutine issue
- Update codecov-action parameter from 'file' to 'files' for v5 compatibility
- Remove test docs file
- **ci**: Add dummy success jobs for docs-only PRs
- replace missed hardcoded assertion with threshold function
- make performance tests more tolerant on CI environments
- add Windows CI exception for flaky performance test
- Make timing-based tests more reliable across platforms
- Move temp_project fixture to module level for all test classes
- Fix flaky cache memory efficiency test
- add pull-requests read permission for paths-filter action
- make performance benchmark test tolerant of CI timing variance
- increase wait time for macOS in flaky debounce test
- update test to use GranularCache instead of ProjectCache
- Make path validation tests cross-platform
- Correct CI workflow syntax for conditional jobs
- correct CI badge URL in README
- Update coverage target to 75% and fix flaky macOS test
- update tests for re-export feature changes
- add company affiliation to author and copyright information
- correct author name and email information
- Prevent infinite recursion in circular dependency detection
- Fix Windows path separators and remove unnecessary type ignores
- Add token to Codecov badge for private repository
- Use Codecov's native badge format
- Add CODECOV_TOKEN to CI workflow
- Also mock watcher in test_cross_repository_import_resolution
- Resolve macOS-specific test failure in multi-project workflow (#24)
- Replace environment variable configuration with override files (#19)
- Cross-platform path resolution issues
- Allow legitimate relative paths in PathValidator while maintaining security
- Remove deprecated safety check and fix mypy CI issues
- Update CI workflow to use pyproject.toml for uv cache

### Refactor

- use as_posix() for all file paths in API responses
- Replace print statements with logging in settings.py
- Move Jedi methods from server to JediAnalyzer

### Perf

- Implement connection pooling for multiple projects
- implement smart cache invalidation for 2-3x performance improvement
- Implement smart cache invalidation for 2-3x performance improvement
- Implement async file operations for non-blocking I/O
- Add performance benchmarking suite with baseline measurements
