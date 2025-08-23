# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/okeefeco/python-code-intelligence-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/okeefeco/python-code-intelligence-mcp/releases/tag/v0.1.0
