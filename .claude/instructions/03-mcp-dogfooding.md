<!--
Audience: Claude Code
Purpose: Enforce MCP-first development workflow for Python code analysis
When to update: When new MCP tools are added or patterns discovered
-->

# MCP-First Development Workflow (Dogfooding Our Own Tools)

**CRITICAL**: We build Python Code Intelligence MCP - we MUST use it for our own development!

## Why MCP-First?

We're developing a powerful semantic code analysis tool but have been falling back to basic grep/glob patterns. This is like building a sports car and pushing it instead of driving it. From now on, ALL Python development in this project MUST prioritize MCP tools over traditional text search.

## Core Principle: Semantic Over Text

**Always choose semantic understanding over text matching:**

- Understand code structure, not just text patterns
- Navigate by meaning, not by string search
- Leverage type information and relationships
- Use framework-specific intelligence when available

## Required Workflow for Python Code Analysis

Before working on ANY Python code:

### 1. Discovery Phase - Understanding the codebase

```bash
mcp__pyeye__list_packages        # See package structure
mcp__pyeye__list_modules         # Understand module organization
mcp__pyeye__list_project_structure  # Get project layout
```

### 2. Navigation Phase - Finding code

```bash
mcp__pyeye__find_symbol         # Find definitions (not grep!)
mcp__pyeye__goto_definition     # Jump to definitions
mcp__pyeye__find_references     # Find all usages
mcp__pyeye__get_type_info       # Understand types
```

### 3. Analysis Phase - Understanding relationships

```bash
mcp__pyeye__analyze_dependencies  # Module dependencies
mcp__pyeye__get_call_hierarchy   # Function call chains
mcp__pyeye__find_subclasses      # Inheritance trees
mcp__pyeye__find_imports         # Import tracking
```

### 4. Framework-Specific Intelligence (when applicable)

```bash
# Pydantic projects:
mcp__pyeye__find_models
mcp__pyeye__get_model_schema

# Flask projects:
mcp__pyeye__find_routes
mcp__pyeye__find_blueprints

# Django projects:
mcp__pyeye__find_django_models
mcp__pyeye__find_django_views
```

## Pattern Replacements (MANDATORY)

These replacements are REQUIRED - using the old patterns is considered a workflow violation:

### Finding Code

- ❌ **WRONG**: `grep -r "class MyClass"` or `Grep("class MyClass")`
- ✅ **RIGHT**: `mcp__pyeye__find_symbol("MyClass")`

- ❌ **WRONG**: `grep -r "def function_name"`
- ✅ **RIGHT**: `mcp__pyeye__find_symbol("function_name")`

- ❌ **WRONG**: `find . -name "*.py" | xargs grep "import module"`
- ✅ **RIGHT**: `mcp__pyeye__find_imports("module")`

### Understanding Code Structure

- ❌ **WRONG**: `ls -la src/` or `tree src/`
- ✅ **RIGHT**: `mcp__pyeye__list_project_structure()`

- ❌ **WRONG**: Reading entire file to understand exports
- ✅ **RIGHT**: `mcp__pyeye__get_module_info("module.path")`

- ❌ **WRONG**: Manually tracing function calls
- ✅ **RIGHT**: `mcp__pyeye__get_call_hierarchy("function_name")`

### Refactoring Preparation

- ❌ **WRONG**: Grep for symbol before renaming
- ✅ **RIGHT**: `mcp__pyeye__find_references()` at position

- ❌ **WRONG**: Manually checking inheritance
- ✅ **RIGHT**: `mcp__pyeye__find_subclasses("BaseClass")`

- ❌ **WRONG**: Reading files to understand dependencies
- ✅ **RIGHT**: `mcp__pyeye__analyze_dependencies("module")`

## Real-World Usage Examples

### Example 1: Adding a New Method to a Class

```python
# 1. Find the class definition
result = mcp__pyeye__find_symbol("ProjectManager")

# 2. Get type info to understand the class
info = mcp__pyeye__get_type_info(
    file=result[0]["file"],
    line=result[0]["line"],
    column=result[0]["column"]
)

# 3. Find all references to ensure compatibility
refs = mcp__pyeye__find_references(
    file=result[0]["file"],
    line=result[0]["line"],
    column=result[0]["column"]
)

# 4. Check subclasses that might be affected
subclasses = mcp__pyeye__find_subclasses("ProjectManager")
```

### Example 2: Refactoring a Module

```python
# 1. Understand module structure
module_info = mcp__pyeye__get_module_info("pycodemcp.cache")

# 2. Analyze dependencies
deps = mcp__pyeye__analyze_dependencies("pycodemcp.cache")

# 3. Find all imports of this module
imports = mcp__pyeye__find_imports("pycodemcp.cache")

# 4. Check for circular dependencies
# deps["circular_dependencies"] will list any found
```

### Example 3: Understanding Plugin Architecture

```python
# 1. Find base plugin class
base = mcp__pyeye__find_symbol("BasePlugin")

# 2. Find all plugin implementations
plugins = mcp__pyeye__find_subclasses("BasePlugin", show_hierarchy=True)

# 3. Understand each plugin's structure
for plugin in plugins:
    info = mcp__pyeye__get_module_info(plugin["module"])
```

## Measuring Success

We track MCP tool usage vs traditional search methods. Target metrics:

- **>80% of Python navigation** should use MCP tools
- **100% of refactoring** should use find_references first
- **All inheritance checks** should use find_subclasses
- **Zero grep usage** for Python symbol search

## Troubleshooting Common Scenarios

### "I can't find a symbol"

1. First try exact match: `find_symbol("exact_name")`
2. Then try fuzzy match: `find_symbol("partial", fuzzy=True)`
3. Check if it's in a different project/package
4. Use `find_symbol_multi` for multi-project search

### "I need to understand how something works"

1. Start with `get_type_info` for documentation
2. Use `get_call_hierarchy` to trace execution
3. Use `analyze_dependencies` to understand module relationships
4. Check `find_references` to see usage patterns

### "I'm refactoring and need to ensure nothing breaks"

1. Always start with `find_references` - NEVER skip this
2. Check `find_subclasses` for inheritance implications
3. Run `analyze_dependencies` to understand impact
4. Use `get_call_hierarchy` to trace call chains

## Benefits We've Discovered

Through dogfooding our own tool, we've found:

1. **3x faster navigation** compared to grep
2. **Catches more edge cases** during refactoring
3. **Better understanding** of code relationships
4. **Finds issues** that text search misses
5. **Type-aware** navigation prevents mistakes

## Performance Tips

- MCP tools are cached for 5 minutes - repeated queries are instant
- Use `list_modules` once at start for overview
- Batch related queries together
- Framework-specific tools are faster than generic ones

## Contributing to MCP Tool Usage

When you discover a new pattern or use case:

1. Document it in this section
2. Add it to troubleshooting if it was non-obvious
3. Consider if we need a new MCP tool for the pattern
4. Share performance comparisons with traditional methods

Remember: **We build this tool - we must be its best users!**
