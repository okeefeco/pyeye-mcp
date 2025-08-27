# Python Code Intelligence MCP Server - Claude Instructions

## 🎯 SESSION STARTUP: Detect Context First

**MANDATORY at session start - Run immediately:**

```bash
# Store where Claude was started from
export CLAUDE_STARTUP_DIR=$(pwd)
export CLAUDE_IS_WORKTREE=$(git worktree list | grep -q "$(pwd)" && echo "true" || echo "false")
export CLAUDE_WORKTREE_BRANCH=$(git branch --show-current 2>/dev/null || echo "none")

# Initialize working directory tracking
export CLAUDE_WORKING_DIR=$(pwd)  # This can change when switching to issue worktrees

# Report context
echo "Claude started from: $CLAUDE_STARTUP_DIR"
echo "Is worktree: $CLAUDE_IS_WORKTREE"
echo "Branch: $CLAUDE_WORKTREE_BRANCH"
```

**This determines:**

- Where Claude configuration files (.claude/) are read from (CLAUDE_STARTUP_DIR)
- Where agent/instruction edits should be saved (CLAUDE_STARTUP_DIR)
- Where actual work happens (CLAUDE_WORKING_DIR - updates when switching worktrees)
- How to create new worktrees (sibling vs child)

@.claude/startup-context.md - Detailed worktree-aware workflow instructions

## 🔄 CRITICAL: Working Directory Management

### The Shell Reset Problem

**Issue**: After each command, the shell working directory resets to CLAUDE_STARTUP_DIR (usually claude-development).

### Solution: Update CLAUDE_WORKING_DIR When Switching Worktrees

**When switching to work on an issue:**

```bash
# After creating/switching to issue worktree
cd ../python-code-intelligence-mcp-work/fix-123-issue-name
export CLAUDE_WORKING_DIR=$(pwd)

# Now prefix subsequent commands with cd to stay in context
cd $CLAUDE_WORKING_DIR && git status
cd $CLAUDE_WORKING_DIR && uv run pytest
```

**Better: Use a worktree switch function:**

```bash
switch_worktree() {
    local WORKTREE_PATH=$1
    cd "$WORKTREE_PATH"
    export CLAUDE_WORKING_DIR=$(pwd)
    echo "Switched working context to: $CLAUDE_WORKING_DIR"
    echo "Claude home remains: $CLAUDE_STARTUP_DIR"
}

# Usage when switching to issue worktree
switch_worktree "../python-code-intelligence-mcp-work/fix-123-issue-name"
```

### Best Practices

1. **Always update CLAUDE_WORKING_DIR** when switching to issue worktrees
2. **Prefix commands with `cd $CLAUDE_WORKING_DIR &&`** to maintain context
3. **Use absolute paths** in worktree operations to avoid confusion
4. **Check current context** with `echo $CLAUDE_WORKING_DIR` if uncertain

## 📚 Required Context Files

These files are automatically loaded to provide essential workflow context:

@CONTRIBUTING.md - GitHub issue workflow, merge strategy, validation rules, development setup
@docs/LABELS.md - GitHub issue labeling system and priorities

**CRITICAL**: The workflows in CONTRIBUTING.md are MANDATORY. Always follow the GitHub issue-based workflow and NEVER use squash merges.

## 📝 Optional User-Specific Configuration

For personal development settings (worktrees, local paths, etc.):

- Create: `~/.claude/projects/{org}/{repo}.md`
- Example: `~/.claude/projects/okeefeco/python-code-intelligence-mcp.md`
- This file is ignored if it doesn't exist and won't be committed to the repository

@~/.claude/projects/okeefeco/python-code-intelligence-mcp.md

## Development Environment

- **Working Directory**: /home/mark/GitHub/python-code-intelligence-mcp
- **Python Environment**: uv managed

### ⚠️ CRITICAL: This Project Uses `uv` Package Manager

**ALWAYS prefix Python commands with `uv run`:**

- ❌ **WRONG**: `pytest tests/test_file.py`
- ✅ **RIGHT**: `uv run pytest tests/test_file.py`

This applies to ALL Python tools:

- `uv run pytest` - Run tests
- `uv run black` - Format code
- `uv run ruff` - Lint code
- `uv run mypy` - Type checking
- `uv run python` - Run Python scripts

**Why**: Dependencies are installed in the uv-managed virtual environment, not globally.

## 🚨 MANDATORY REQUIREMENTS

### ⚠️ CRITICAL: Worktree Safety Rules

#### NEVER force-delete worktrees without explicit permission

1. **Before ANY worktree removal**:

   ```bash
   # Check for uncommitted changes
   git -C <worktree-path> status --short

   # Or use our safety script
   python scripts/worktree_safety.py check <worktree-path>
   ```

2. **Worktree Ownership**:
   - Only remove worktrees YOU created in current session
   - Check `.worktree-ownership.json` if it exists
   - When in doubt, ASK the user

3. **Safe Cleanup Process**:

   ```bash
   # List all worktrees with safety status
   python scripts/worktree_safety.py list

   # Check specific worktree
   python scripts/worktree_safety.py check <path>

   # Safe removal (prompts if changes detected)
   python scripts/worktree_safety.py remove <path>

   # NEVER use --force without explicit user permission
   ```

4. **If you see "contains modified or untracked files"**:
   - STOP immediately
   - Report to user
   - Ask for explicit instructions
   - Do NOT proceed with --force

**Remember**: Worktrees can contain days of uncommitted work from other sessions!

### Critical Development Rules

**These are non-negotiable - violations will cause CI failures:**

1. **🖥️ Cross-Platform Paths**: ALWAYS use `path.as_posix()` for display/storage. NEVER use `str(path)` in string contexts.
2. **⏱️ Performance Tests**: ALWAYS use `PerformanceThresholds` framework. NEVER write naive `assert elapsed < 0.2` assertions.
3. **✅ Tests Required**: ALL code changes MUST include comprehensive tests.

### Test-Driven Development Workflow

**ALL code changes MUST include tests. This is enforced by CI.**

When implementing ANY feature or fix:

1. **Write tests FIRST** (TDD approach recommended)
2. **Implement the feature/fix**
3. **Run tests locally with coverage check**:

   ```bash
   # IMPORTANT: Run ALL tests, not just your new tests!
   uv run pytest --cov=src/pycodemcp --cov-fail-under=85
   ```

4. **Fix any failing tests or coverage issues**
5. **NEVER commit code without tests**

### Coverage Requirements

- **Minimum 85% total coverage** (CI will fail below this)
- **New code should have >90% coverage**
- **All bug fixes MUST include regression tests**
- **ALWAYS run full test suite before pushing** (learned from PR #77)

### Before Marking Tasks Complete

Always run these validation commands:

```bash
# MANDATORY: Run ALL tests with coverage (not just your new tests!)
uv run pytest --cov=src/pycodemcp --cov-fail-under=85

# Note: Linting/type checks are handled by pre-commit hooks automatically
```

## 🚀 MCP-First Development Workflow (Dogfooding Our Own Tools)

**CRITICAL**: We build Python Code Intelligence MCP - we MUST use it for our own development!

### Why MCP-First?

We're developing a powerful semantic code analysis tool but have been falling back to basic grep/glob patterns. This is like building a sports car and pushing it instead of driving it. From now on, ALL Python development in this project MUST prioritize MCP tools over traditional text search.

### Core Principle: Semantic Over Text

**Always choose semantic understanding over text matching:**

- Understand code structure, not just text patterns
- Navigate by meaning, not by string search
- Leverage type information and relationships
- Use framework-specific intelligence when available

### Required Workflow for Python Code Analysis

Before working on ANY Python code:

1. **Discovery Phase** - Understanding the codebase:

   ```bash
   mcp__python-intelligence__list_packages        # See package structure
   mcp__python-intelligence__list_modules         # Understand module organization
   mcp__python-intelligence__list_project_structure  # Get project layout
   ```

2. **Navigation Phase** - Finding code:

   ```bash
   mcp__python-intelligence__find_symbol         # Find definitions (not grep!)
   mcp__python-intelligence__goto_definition     # Jump to definitions
   mcp__python-intelligence__find_references     # Find all usages
   mcp__python-intelligence__get_type_info       # Understand types
   ```

3. **Analysis Phase** - Understanding relationships:

   ```bash
   mcp__python-intelligence__analyze_dependencies  # Module dependencies
   mcp__python-intelligence__get_call_hierarchy   # Function call chains
   mcp__python-intelligence__find_subclasses      # Inheritance trees
   mcp__python-intelligence__find_imports         # Import tracking
   ```

4. **Framework-Specific Intelligence** (when applicable):

   ```bash
   # Pydantic projects:
   mcp__python-intelligence__find_models
   mcp__python-intelligence__get_model_schema

   # Flask projects:
   mcp__python-intelligence__find_routes
   mcp__python-intelligence__find_blueprints

   # Django projects:
   mcp__python-intelligence__find_django_models
   mcp__python-intelligence__find_django_views
   ```

### Pattern Replacements (MANDATORY)

These replacements are REQUIRED - using the old patterns is considered a workflow violation:

#### Finding Code

- ❌ **WRONG**: `grep -r "class MyClass"` or `Grep("class MyClass")`
- ✅ **RIGHT**: `mcp__python-intelligence__find_symbol("MyClass")`

- ❌ **WRONG**: `grep -r "def function_name"`
- ✅ **RIGHT**: `mcp__python-intelligence__find_symbol("function_name")`

- ❌ **WRONG**: `find . -name "*.py" | xargs grep "import module"`
- ✅ **RIGHT**: `mcp__python-intelligence__find_imports("module")`

#### Understanding Code Structure

- ❌ **WRONG**: `ls -la src/` or `tree src/`
- ✅ **RIGHT**: `mcp__python-intelligence__list_project_structure()`

- ❌ **WRONG**: Reading entire file to understand exports
- ✅ **RIGHT**: `mcp__python-intelligence__get_module_info("module.path")`

- ❌ **WRONG**: Manually tracing function calls
- ✅ **RIGHT**: `mcp__python-intelligence__get_call_hierarchy("function_name")`

#### Refactoring Preparation

- ❌ **WRONG**: Grep for symbol before renaming
- ✅ **RIGHT**: `mcp__python-intelligence__find_references()` at position

- ❌ **WRONG**: Manually checking inheritance
- ✅ **RIGHT**: `mcp__python-intelligence__find_subclasses("BaseClass")`

- ❌ **WRONG**: Reading files to understand dependencies
- ✅ **RIGHT**: `mcp__python-intelligence__analyze_dependencies("module")`

### Real-World Usage Examples

#### Example 1: Adding a New Method to a Class

```python
# 1. Find the class definition
result = mcp__python-intelligence__find_symbol("ProjectManager")

# 2. Get type info to understand the class
info = mcp__python-intelligence__get_type_info(
    file=result[0]["file"],
    line=result[0]["line"],
    column=result[0]["column"]
)

# 3. Find all references to ensure compatibility
refs = mcp__python-intelligence__find_references(
    file=result[0]["file"],
    line=result[0]["line"],
    column=result[0]["column"]
)

# 4. Check subclasses that might be affected
subclasses = mcp__python-intelligence__find_subclasses("ProjectManager")
```

#### Example 2: Refactoring a Module

```python
# 1. Understand module structure
module_info = mcp__python-intelligence__get_module_info("pycodemcp.cache")

# 2. Analyze dependencies
deps = mcp__python-intelligence__analyze_dependencies("pycodemcp.cache")

# 3. Find all imports of this module
imports = mcp__python-intelligence__find_imports("pycodemcp.cache")

# 4. Check for circular dependencies
# deps["circular_dependencies"] will list any found
```

#### Example 3: Understanding Plugin Architecture

```python
# 1. Find base plugin class
base = mcp__python-intelligence__find_symbol("BasePlugin")

# 2. Find all plugin implementations
plugins = mcp__python-intelligence__find_subclasses("BasePlugin", show_hierarchy=True)

# 3. Understand each plugin's structure
for plugin in plugins:
    info = mcp__python-intelligence__get_module_info(plugin["module"])
```

### Measuring Success

We track MCP tool usage vs traditional search methods. Target metrics:

- **>80% of Python navigation** should use MCP tools
- **100% of refactoring** should use find_references first
- **All inheritance checks** should use find_subclasses
- **Zero grep usage** for Python symbol search

### Troubleshooting Common Scenarios

#### "I can't find a symbol"

1. First try exact match: `find_symbol("exact_name")`
2. Then try fuzzy match: `find_symbol("partial", fuzzy=True)`
3. Check if it's in a different project/package
4. Use `find_symbol_multi` for multi-project search

#### "I need to understand how something works"

1. Start with `get_type_info` for documentation
2. Use `get_call_hierarchy` to trace execution
3. Use `analyze_dependencies` to understand module relationships
4. Check `find_references` to see usage patterns

#### "I'm refactoring and need to ensure nothing breaks"

1. Always start with `find_references` - NEVER skip this
2. Check `find_subclasses` for inheritance implications
3. Run `analyze_dependencies` to understand impact
4. Use `get_call_hierarchy` to trace call chains

### Benefits We've Discovered

Through dogfooding our own tool, we've found:

1. **3x faster navigation** compared to grep
2. **Catches more edge cases** during refactoring
3. **Better understanding** of code relationships
4. **Finds issues** that text search misses
5. **Type-aware** navigation prevents mistakes

### Performance Tips

- MCP tools are cached for 5 minutes - repeated queries are instant
- Use `list_modules` once at start for overview
- Batch related queries together
- Framework-specific tools are faster than generic ones

### Contributing to MCP Tool Usage

When you discover a new pattern or use case:

1. Document it in this section
2. Add it to troubleshooting if it was non-obvious
3. Consider if we need a new MCP tool for the pattern
4. Share performance comparisons with traditional methods

Remember: **We build this tool - we must be its best users!**

## 📊 Dogfooding Metrics Tracking

To measure our MCP adoption and identify improvement opportunities, we track usage metrics during development sessions.

### 🎯 Claude Code Hooks Integration (Active)

**Automatic MCP monitoring using Claude Code's native hook system:**

```bash
# One-time setup for hooks-based monitoring
bash scripts/claude_hooks/setup_mcp_monitoring.sh

# Load convenience commands (already in ~/.bashrc)
source ~/.claude/mcp_monitoring/aliases.sh

# View real-time analytics
mcp-report         # 7-day report
mcp-report-month   # 30-day report
mcp-logs          # Watch live activity
mcp-session       # View active session
mcp-errors        # Check for hook errors
```

**What it tracks automatically:**

- Every MCP Python Intelligence tool call
- Grep/find/rg usage in Bash commands
- Session start/end events
- Tool success rates and response sizes
- Direct Grep tool usage

**Note:** Hooks are active and tracking. The old shell alias system has been removed in favor of this cleaner approach.

See `scripts/claude_hooks/README.md` for full documentation.

### ⚡ What Happens Automatically

After Claude hooks setup, metrics tracking is completely automatic:

1. **Session Start**: Claude Code session start → Auto-tracked via hooks
2. **Grep Usage**: `grep "function"` → Auto-tracked in Bash commands
3. **MCP Usage**: All MCP tool calls → Auto-tracked via hooks
4. **Session End**: Claude Code session end → Auto-tracked and reported
5. **Tool Success**: Response sizes and success rates → Auto-tracked

The Claude hooks system handles everything - no manual intervention needed!

### Weekly Reporting

```bash
# Generate 7-day report
python scripts/dogfooding_metrics.py report --days 7
```

### Target Metrics

We're tracking progress toward these goals:

- **Week 1**: Establish baseline, >30% MCP usage
- **Week 2**: >50% MCP usage, document 5+ time-saving examples
- **Week 3**: >70% MCP usage, identify feature gaps
- **Week 4**: >80% MCP usage, measurable productivity gains

### Real Usage Examples We've Discovered

1. **Finding plugin implementations** (3x faster than grep):

   ```python
   plugins = mcp__python-intelligence__find_subclasses("BasePlugin")
   # Found all 3 plugins in 0.2s vs 15s with grep
   ```

2. **Refactoring safely** (prevented 2 bugs):

   ```python
   refs = mcp__python-intelligence__find_references(file, line, col)
   # Found usage in test file that grep missed
   ```

3. **Understanding module structure** (5min → 30s):

   ```python
   info = mcp__python-intelligence__get_module_info("pycodemcp.cache")
   # Instant view of exports, metrics, dependencies
   ```

## 🤖 Mandatory Agent Usage

### ALWAYS Use These Agents (Never Manual Commands)

**When the user says any variant of:**

#### "Let's commit this" / "Commit these changes" / "Create a commit"

→ **IMMEDIATELY use**: `Task tool with subagent_type="smart-commit"`
→ **NEVER use**: Manual `git status`, `git add`, `git commit` commands

#### "Validate this works on Windows/Mac/Linux" / "Check cross-platform"

→ **IMMEDIATELY use**: `Task tool with subagent_type="cross-platform-validator"`
→ **NEVER use**: Manual path checking or grep for .as_posix()

#### "Setup a worktree" / "Switch to issue X" / "Clean up worktrees"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **NEVER use**: Manual `git worktree add` commands

#### "PR is merged" / "Update after merge" / "Sync after external merge"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **NEVER use**: Manual `git checkout`, `git merge`, `git pull` sequences
→ **Note**: Handles special cases like persistent claude/development branch

#### "Push and create PR" / "Create a PR" / "Monitor CI" / "Check if CI passes"

→ **IMMEDIATELY use**: `Task tool with subagent_type="pr-workflow"`
→ **NEVER use**: Manual `git push`, `gh pr create`, `gh run list` sequences

### Composite Agent Workflows

These commands trigger multiple agents in sequence:

#### "Merge and cleanup" / "Merge PR and clean up" / "Finish this PR"

→ **EXECUTE IN SEQUENCE**:

1. `Task tool with subagent_type="pr-workflow"` - Merge the PR, update main, delete remote branch
2. `Task tool with subagent_type="worktree-manager"` - Remove the worktree safely after confirming no uncommitted changes

#### "PR is merged. update" / "Update after merge" / "Sync with main" / "Merged externally"

→ **IMMEDIATELY use**: `Task tool with subagent_type="worktree-manager"`
→ **Purpose**: Handle post-merge updates when PR was merged externally (via GitHub UI or by another user)
→ **Special handling**: For claude/development, updates the persistent branch without removing worktree

#### "Start issue X" / "Begin work on issue X"

→ **EXECUTE IN SEQUENCE**:

1. `Task tool with subagent_type="worktree-manager"` - Create worktree for the issue
2. Review issue with `gh issue view X`
3. Create initial todo list based on issue requirements

### Available Agents

- **smart-commit**: Intelligent git commit workflow with pre-commit validation
- **cross-platform-validator**: Validates cross-platform compatibility
- **worktree-manager**: Safe worktree operations with session tracking
- **pr-workflow**: Complete PR lifecycle - push, create/update PR, monitor CI
- **general-purpose**: For complex multi-step research tasks

**Note**: Agents are defined in `.claude/agents/` and are automatically available via the Task tool.

### Special Workflow: Claude Development Branch

The `claude-development` worktree has a **special merge workflow** that differs from standard issue branches:

#### Standard Issue Workflow (Delete After Merge)

```bash
# Normal issue branches:
1. Create PR from feat/123-feature → main
2. Merge PR
3. Delete remote branch
4. Remove worktree (worktree-manager does this)
```

#### Claude Development Workflow (Keep and Update)

```bash
# For claude/development branch:
1. Create PR from claude/development → main
2. Merge PR (keeps branch)
3. DO NOT delete remote branch
4. DO NOT remove worktree
5. Update local branch:
   cd /home/mark/GitHub/python-code-intelligence-mcp-work/claude-development
   git checkout main
   git pull origin main
   git checkout claude/development
   git merge main  # or rebase if preferred
   git push origin claude/development
```

**Important for Agents**:

- When using `pr-workflow` agent with claude/development, specify `--no-delete-branch`
- When "merge and cleanup" is requested for claude/development, only merge - skip cleanup
- The worktree at `/home/mark/GitHub/python-code-intelligence-mcp-work/claude-development` is **persistent**
- **NEVER switch this worktree to other branches** - always create new worktrees for releases, features, etc.

#### Release Workflow (Create New Worktree)

```bash
# For releases, ALWAYS create a new worktree:
git worktree add ../python-code-intelligence-mcp-work/release-0-3-0 -b release/0.3.0 main
cd ../python-code-intelligence-mcp-work/release-0-3-0
# Do release work here, NOT in claude-development worktree
```

## Project Overview

This is the Python Code Intelligence MCP Server - an extensible MCP (Model Context Protocol) server that provides intelligent Python code analysis for AI assistants like Claude.

## Key Features

- **Semantic Code Navigation**: Find symbols, go to definitions, find references using Jedi
- **Multi-Project Support**: Analyze multiple projects and dependencies simultaneously
- **Namespace Packages**: Handle packages distributed across multiple repositories
- **Auto-Update**: File watching automatically reflects code changes
- **Configuration System**: Flexible configuration via files, env vars, or auto-discovery
- **Plugin Architecture**: Extensible with custom analyzers for project patterns

## Architecture

- **Core Server**: FastMCP-based MCP server implementation
- **Project Manager**: Handles multiple projects with LRU caching (max 10)
- **Analysis Engine**: Jedi for semantic analysis and type inference
- **Caching Layer**: File watchers (watchdog) + result cache (5min TTL)
- **Plugin System**: Base class + framework plugins (Django example included)

## MCP Tools Available

### Core Navigation Tools

1. `configure_packages` - Set up additional package locations
2. `find_symbol` - Find class/function/variable definitions
3. `goto_definition` - Jump to symbol definition
4. `find_references` - Find all symbol usages
5. `get_type_info` - Get type hints and docstrings
6. `find_imports` - Track module imports
7. `get_call_hierarchy` - Analyze function calls
8. `find_subclasses` - Find all classes inheriting from a base class
9. `find_symbol_multi` - Search across multiple projects
10. `configure_namespace_package` - Set up distributed namespaces
11. `find_in_namespace` - Search within namespace packages
12. `list_project_structure` - View project file organization

### Module & Package Analysis Tools

1. `list_packages` - List all Python packages with structure
2. `list_modules` - List modules with exports, classes, functions, and metrics
3. `analyze_dependencies` - Analyze module imports and detect circular dependencies
4. `get_module_info` - Get detailed module information including metrics and dependencies

### Pydantic-Specific Tools (auto-activated when Pydantic detected)

1. `find_pydantic_models` - Discover all BaseModel classes with fields
2. `get_model_schema` - Extract complete model schema
3. `find_validators` - Locate all validation methods
4. `find_field_validators` - Find field-specific validators
5. `find_model_config` - Extract model configurations
6. `trace_model_inheritance` - Map model inheritance hierarchies
7. `find_computed_fields` - Find computed_field and @property fields

### Django-Specific Tools (auto-activated when Django detected)

- `find_django_models` - Find all Django models
- `find_django_views` - Find all views
- `find_django_urls` - Find URL patterns
- `find_django_templates` - Find templates
- `find_django_migrations` - Find migrations

### Flask-Specific Tools (auto-activated when Flask detected)

- `find_flask_routes` - Discover all route decorators with methods and endpoints
- `find_flask_blueprints` - Locate Blueprint definitions and registrations
- `find_flask_views` - Find view functions and MethodView classes
- `find_flask_templates` - Locate Jinja2 templates and render_template calls
- `find_flask_extensions` - Identify Flask extensions (SQLAlchemy, Login, CORS, etc.)
- `find_flask_config` - Find configuration files and app.config usage
- `find_error_handlers` - Locate @app.errorhandler decorators
- `find_cli_commands` - Find Flask CLI commands (@app.cli.command)

## Configuration

The server supports configuration via:

- `.pycodemcp.json` in project root
- `pyproject.toml` [tool.pycodemcp] section
- Environment variables (PYCODEMCP_PACKAGES, etc.)
- Global config `~/.config/pycodemcp/config.json`
- Auto-discovery of sibling packages

Example `.pycodemcp.json`:

```json
{
  "packages": ["../my-lib", "~/repos/shared-utils"],
  "namespaces": {
    "company": ["~/repos/company-auth", "~/repos/company-api"]
  }
}
```

## Development Commands

```bash
# Run server in dev mode
uv run mcp dev src/pycodemcp/server.py

# Run tests
uv run pytest

# Format code
uv run black src/
uv run ruff check src/
```

## Current Status

✅ **Fully functional** with all core features implemented:

- Basic navigation tools working
- Multi-project support with LRU caching
- Namespace package resolution
- Auto-updating on file changes
- Configuration system with multiple sources
- Plugin architecture with Django, Pydantic, and Flask plugins
- Comprehensive documentation
- **NEW**: Flask framework intelligence with 8 specialized tools for routes, blueprints, templates, and more

## Next Steps / Improvements

Potential enhancements to consider:

- Add more framework plugins (FastAPI)
- Consider Tree-sitter for advanced pattern matching (future enhancement)
- Add test coverage
- Publish to PyPI for easier installation
- Add more sophisticated caching strategies
- Create VS Code extension integration

## Important Notes

- The server is configured globally for Claude Code via `claude mcp add`
- Each Claude instance gets its own MCP server instance (not shared)
- File watchers automatically update when code changes
- Configuration is loaded from multiple sources with precedence
- Plugins auto-activate based on project detection (Django, Pydantic, Flask)
- Framework plugins provide deep understanding beyond basic navigation

## File Structure

```text
src/pycodemcp/
├── server.py              # Main MCP server with 17 core tools
├── project_manager.py     # Multi-project management with LRU
├── namespace_resolver.py  # Distributed package handling
├── config.py             # Configuration system
├── cache.py              # Caching and file watching
├── analyzers/
│   └── jedi_analyzer.py # Jedi wrapper for analysis
└── plugins/
    ├── base.py          # Plugin base class
    ├── django.py        # Django framework plugin
    ├── pydantic.py      # Pydantic models plugin
    └── flask.py         # Flask framework plugin (NEW)
```

## Context Loss Recovery

If context is lost:

1. **Check the GitHub issue** - `gh issue view <number>` (branch name shows issue number)
2. **Your todo list persists** - The TodoWrite tool maintains your session progress
3. **Check git state** - `git status`, `git log --oneline -5`, `git diff`
4. **Resume from todo list** - Continue from where your tasks show you stopped

The TodoWrite tool is your primary progress tracker - it persists across context resets without creating commits.

## Task Management with TodoWrite Tool

Use the **TodoWrite tool** for all task tracking - it persists across context resets without creating commits.

### Best Practices

- **Break tasks into small chunks** - 5-10 minute increments
- **Include file:line references** - e.g., "Fix validation in server.py:125-150"
- **Mark complete immediately** - Update status as you finish each task
- **Keep ONE task in_progress** - Focus on single task at a time
- **Never track in files** - Use TodoWrite tool, not CLAUDE.md or other files

### File Reference Pattern

Always use `file_path:line_number` format for easy navigation:

- `src/server.py:125` - Specific line reference
- `tests/test_validation.py:45-89` - Range reference
- `src/plugins/flask.py:find_routes` - Function reference

## Cross-Platform Path Handling

### Key Learning from PR #121

When working with paths that will be displayed or compared as strings:

- **Always use `.as_posix()`** for consistent forward-slash format
- **Don't use raw `str(Path)`** for relative paths - it uses OS-native separators
- **Example**: Template names, config paths, display paths

### Quick Reference

```python
# ❌ WRONG - OS-dependent separators
template_name = str(template_file.relative_to(template_dir))
# Windows: "admin\\dashboard.html"
# Unix: "admin/dashboard.html"

# ✅ CORRECT - Always forward slashes
template_name = template_file.relative_to(template_dir).as_posix()
# All platforms: "admin/dashboard.html"
```

### Path Utilities Available

- `src/pycodemcp/path_utils.py` has helpers:
  - `path_to_key()` - For dictionary keys/comparison
  - `ensure_posix_path()` - Convert any path to forward slashes
  - `paths_equal()` - Platform-safe path comparison

### Testing on Windows

- CI runs on Windows, macOS, and Linux
- Windows path issues typically show as:
  - `AssertionError: 'path/to/file' != 'path\\to\\file'`
  - Template/config file paths are common culprits
