# Code Understanding Workflow

## Goal

Quickly understand unfamiliar code by systematically exploring its structure, purpose, relationships, and usage patterns. This workflow guides you from "What is this?" to "How does this work?" to "Where is this used?"

## When to Use This Workflow

- "What does this class/function do?"
- "How does this codebase work?"
- "I'm new to this project, where do I start?"
- "Explain how this module fits into the system"

## Steps

### Step 1: Locate the Symbol

Use `find_symbol` to locate the definition of the class, function, or module you want to understand:

```python
# Example: Find a class
find_symbol(
    name="DataProcessor",
    fuzzy=False
)

# Returns:
# [
#     {
#         "name": "DataProcessor",
#         "type": "class",
#         "file": "/project/processing/processor.py",
#         "line": 45,
#         "column": 0,
#         "import_paths": ["processing.processor.DataProcessor"]
#     }
# ]
```

**Fuzzy Search**: If you don't know the exact name, use `fuzzy=True`:

```python
find_symbol(name="process", fuzzy=True)
# Finds: DataProcessor, process_data, ProcessManager, etc.
```

### Step 2: Inspect the Symbol

Use `get_type_info` to understand what the symbol is and what it does:

```python
# Example call
get_type_info(
    file="/project/processing/processor.py",
    line=45,
    column=0,
    detailed=True
)

# Returns:
# {
#     "name": "DataProcessor",
#     "type": "class",
#     "full_name": "processing.processor.DataProcessor",
#     "docstring": "Processes raw data into structured format...",
#     "base_classes": ["BaseProcessor"],
#     "mro": ["DataProcessor", "BaseProcessor", "object"],
#     "methods": ["process", "validate", "transform"],
#     "attributes": ["config", "logger"]
# }
```

**Key Information to Extract**:

- **Docstring**: What the code is supposed to do
- **Base classes**: What it inherits from (for classes)
- **Methods/Attributes**: Available functionality (if `detailed=True`)
- **Type hints**: Expected input/output types

### Step 3: Understand the Hierarchy (For Classes)

If the symbol is a class, explore its inheritance relationships:

**Option A: Find Parent Classes**
Already shown in Step 2's `base_classes` and `mro` (Method Resolution Order)

**Option B: Find Child Classes**
Use `find_subclasses` to see what inherits from this class:

```python
find_subclasses(
    base_class="DataProcessor",
    show_hierarchy=True
)

# Returns:
# [
#     {
#         "name": "CSVProcessor",
#         "hierarchy": ["DataProcessor", "CSVProcessor"]
#     },
#     {
#         "name": "JSONProcessor",
#         "hierarchy": ["DataProcessor", "JSONProcessor"]
#     }
# ]
```

**Insight**: This shows you:

- How the class is extended/specialized
- Common patterns in the codebase
- The design hierarchy

### Step 4: Trace Execution Flow (For Functions)

Use `get_call_hierarchy` to understand how functions are called and what they call:

```python
get_call_hierarchy(
    function_name="process_data",
    file="/project/processing/processor.py"
)

# Returns:
# {
#     "function": "process_data",
#     "callers": [
#         {"function": "main", "file": "/project/app.py", "line": 23},
#         {"function": "batch_process", "file": "/project/batch.py", "line": 67}
#     ],
#     "callees": [
#         {"function": "validate", "file": "/project/processing/processor.py"},
#         {"function": "transform", "file": "/project/processing/processor.py"}
#     ]
# }
```

**Insight**:

- **Callers**: Where is this function used? (entry points)
- **Callees**: What does this function do? (implementation details)

### Step 5: See Usage Patterns

Use the **[Find All References Workflow](workflows://find-references)** to see real-world usage:

1. Get fully qualified name (already have from Step 2)
2. Find all references in packages and scripts
3. Examine actual usage code

**Why this matters**: Documentation tells you what code *should* do, usage shows what it *actually* does.

Example insights from usage:

- Common parameter patterns
- Typical use cases
- Integration patterns
- Error handling approaches

### Step 6: Understand Module Context (For Modules)

Use `get_module_info` to understand the module's structure and purpose:

```python
get_module_info(
    module_path="processing.processor"
)

# Returns:
# {
#     "module": "processing.processor",
#     "file": "/project/processing/processor.py",
#     "exports": ["DataProcessor", "process_data", "validate_input"],
#     "classes": [{"name": "DataProcessor", "line": 45}],
#     "functions": [{"name": "process_data", "line": 12}],
#     "imports": ["logging", "typing", "processing.base"],
#     "metrics": {"lines": 234, "classes": 1, "functions": 5}
# }
```

**Insight**:

- **Exports**: Public API of the module
- **Imports**: Dependencies and relationships
- **Metrics**: Size and complexity

## Complete Example: Understanding a New Class

**Goal**: Understand the `UserManager` class in an unfamiliar codebase

### Discovery Phase

```text
Step 1: find_symbol(name="UserManager")
→ Found at: /project/auth/manager.py:30

Step 2: get_type_info(file="/project/auth/manager.py", line=30, detailed=True)
→ Class: UserManager
→ Docstring: "Manages user authentication and authorization"
→ Base classes: [BaseManager]
→ Methods: [authenticate, authorize, create_user, delete_user]
→ Attributes: [db, cache, logger]

Step 3: find_subclasses(base_class="UserManager", show_hierarchy=True)
→ Subclasses: AdminUserManager, GuestUserManager
→ Hierarchy: BaseManager → UserManager → [Admin/Guest]UserManager
```

### Understanding Phase

```text
Step 4: get_call_hierarchy(function_name="authenticate")
→ Callers: login_endpoint, api_auth_middleware (entry points)
→ Callees: validate_credentials, create_session (implementation)

Step 5: Find All References (using workflow)
→ 23 references found across 12 files
→ Common pattern: manager = UserManager(db); user = manager.authenticate(...)

Step 6: get_module_info(module_path="auth.manager")
→ Exports: UserManager, authenticate_user, create_user
→ Imports: auth.base, database.models, cache.redis
→ Module provides: Authentication and user management layer
```

### Knowledge Gained

- **Purpose**: Central authentication/authorization manager
- **Design**: Follows manager pattern, inherits from BaseManager
- **Usage**: Used by API endpoints and middleware
- **Architecture**: Sits between API layer and database layer
- **Variants**: Admin and Guest have specialized versions

## Progressive Understanding Levels

### Level 1: Basic (Steps 1-2)

- What is it? (class/function/module)
- Where is it defined?
- What's it supposed to do? (docstring)

### Level 2: Structure (Steps 3-4)

- How does it relate to other code? (inheritance/calls)
- What's the execution flow?

### Level 3: Integration (Steps 5-6)

- How is it actually used?
- Where does it fit in the system?

## Understanding Checklist

Quick understanding:

- [ ] Located symbol with `find_symbol`
- [ ] Read docstring with `get_type_info`
- [ ] Understood immediate context

Deep understanding:

- [ ] Explored inheritance with `find_subclasses` (for classes)
- [ ] Traced execution with `get_call_hierarchy` (for functions)
- [ ] Examined usage with find-references workflow
- [ ] Understood module context with `get_module_info`

## Common Understanding Patterns

### Pattern 1: Top-Down (Architecture First)

1. Start with module structure (`list_modules`, `get_module_info`)
2. Identify key classes/functions
3. Drill into specifics with `get_type_info`

### Pattern 2: Bottom-Up (Symbol First)

1. Start with specific symbol (`find_symbol`)
2. Understand the symbol (`get_type_info`)
3. Expand to context (hierarchy, callers, module)

### Pattern 3: Flow-Based (Execution Path)

1. Find entry point (main, endpoint, handler)
2. Trace execution (`get_call_hierarchy`)
3. Understand each step along the path

### Pattern 4: Usage-Based (Learn by Example)

1. Find the symbol
2. Find all references (usage examples)
3. Learn patterns from real usage
4. Understand design from patterns

## Tips for Faster Understanding

**For Classes**:

- Check base classes to understand inherited behavior
- Look at subclasses to see how it's extended
- Examine **init** to understand initialization

**For Functions**:

- Check callers to understand purpose/context
- Check callees to understand implementation
- Look at usage for parameter patterns

**For Modules**:

- Start with exports (public API)
- Check imports (dependencies)
- Review metrics (complexity)

**For Large Codebases**:

- Use fuzzy search to explore naming patterns
- Follow dependency chains (`analyze_dependencies`)
- Look for README or docs in module docstrings

## Limitations and Considerations

**Known Limitations**:

- Dynamic code (eval, exec) won't be fully understood
- Decorator behavior may not be evident
- Magic methods require manual inspection

**Best Practices**:

- Start broad, then narrow (module → class → method)
- Look for tests - they're excellent usage examples
- Check commit history for context on "why"
- Draw diagrams of relationships for complex systems

## Success Indicators

✅ **Can explain what it does**: Clear understanding of purpose
✅ **Know where it's used**: Identified all usage points
✅ **Understand relationships**: Clear picture of inheritance/calls
✅ **See integration**: Know how it fits in the system
✅ **Ready to modify**: Confident enough to make changes

## Related Workflows

- [Find All References](workflows://find-references) - See real usage patterns (Step 5)
- [Refactoring](workflows://refactoring) - Apply understanding to safe changes
- [Dependency Analysis](workflows://dependency-analysis) - Deep dive into module relationships

## Related Tools

- `find_symbol` - Locate definitions
- `get_type_info` - Inspect symbols
- `find_subclasses` - Explore inheritance
- `get_call_hierarchy` - Trace execution
- `get_module_info` - Module structure
- `list_modules` - Project overview
