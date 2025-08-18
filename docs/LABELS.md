# GitHub Labels Guide

This document describes the label system used for issues and pull requests in the Python Code Intelligence MCP project.

## Label Categories

### 🎯 Priority Levels

Used to indicate urgency and importance.

- `priority: critical` (🔴) - Must be fixed ASAP, blocking releases or core functionality
- `priority: high` (🟠) - High priority, should be addressed soon
- `priority: medium` (🟡) - Medium priority, normal workflow
- `priority: low` (🟢) - Low priority, nice to have

### 📦 Components

Identifies which part of the codebase is affected.

- `component: server` - MCP server core functionality
- `component: plugins` - Plugin system (Django, Flask, Pydantic)
- `component: analyzer` - Code analysis (Jedi integration)
- `component: cache` - Caching system
- `component: config` - Configuration handling

### 💻 Platforms

Identifies platform-specific issues.

- `platform: all` - Affects all platforms
- `platform: windows` - Windows-specific
- `platform: macos` - macOS-specific
- `platform: linux` - Linux-specific

### 🔧 Issue Types

Core GitHub labels for categorizing issues.

- `bug` - Something isn't working
- `enhancement` - New feature or request
- `documentation` - Documentation improvements
- `question` - Further information requested

### 👷 Development

Related to development workflow and code quality.

- `testing` - Test coverage and testing
- `refactor` - Code refactoring and cleanup
- `performance` - Performance improvements
- `security` - Security-related issues
- `tech-debt` - Technical debt
- `ci/cd` - CI/CD pipeline
- `dependencies` - Dependency updates

### 📊 Status

Tracks the current state of issues and PRs.

- `in-progress` - Currently being worked on
- `blocked` - Blocked by another issue
- `needs-review` - Needs review from maintainers
- `ready-to-merge` - PR approved and ready
- `needs-discussion` - Requires discussion

### 🚀 Special

Special labels for specific purposes.

- `good first issue` - Good for newcomers
- `help wanted` - Extra attention needed
- `breaking-change` - Breaking API change
- `duplicate` - Duplicate issue
- `invalid` - Not a valid issue
- `wontfix` - Will not be fixed

## Usage Guidelines

### For Issues

1. **Always add a priority label** to help with triage
2. **Add component labels** to identify affected areas
3. **Add platform labels** if platform-specific
4. **Use status labels** to track progress

### For Pull Requests

1. **Add component labels** for changed areas
2. **Add `testing` label** if adding/modifying tests
3. **Use `breaking-change`** if API changes
4. **Update to `ready-to-merge`** when approved

### Examples

#### Bug Report

```text
bug, priority: high, component: analyzer, platform: macos
```

#### Feature Request

```text
enhancement, priority: medium, component: plugins, needs-discussion
```

#### Test Improvement

```text
testing, priority: low, good first issue
```

#### Critical Fix

```text
bug, priority: critical, security, platform: all
```

## Automation

Consider adding GitHub Actions to:

- Auto-label PRs based on changed files
- Add `needs-review` when PR is ready
- Add `stale` label for inactive issues
- Require priority labels on all issues

## Maintenance

- Review and clean up unused labels quarterly
- Ensure consistency in label usage
- Update this document when labels change
