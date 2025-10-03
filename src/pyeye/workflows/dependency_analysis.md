# Dependency Analysis Workflow

## Goal

Understand module dependencies, import relationships, and architectural patterns in a Python project. This workflow helps you:

- Map import relationships (who imports what)
- Identify circular dependencies
- Understand module coupling
- Analyze architectural layers
- Plan refactoring safely

## When to Use This Workflow

- "What does this module depend on?"
- "Which modules use this module?"
- "Are there circular dependencies?"
- "How is the codebase structured?"
- "Can I safely move this module?"

## Steps

### Step 1: Analyze Single Module Dependencies

Use `analyze_dependencies` to understand a specific module's import relationships:

```python
# Example call
analyze_dependencies(
    module_path="mypackage.services",
    scope="all"
)

# Returns:
# {
#     "module": "mypackage.services",
#     "imports": [
#         {"module": "mypackage.models", "type": "internal"},
#         {"module": "sqlalchemy", "type": "external"},
#         {"module": "logging", "type": "stdlib"}
#     ],
#     "imported_by": [
#         {"module": "mypackage.api", "file": "/project/api/routes.py"},
#         {"module": "mypackage.cli", "file": "/project/cli/commands.py"}
#     ],
#     "circular_dependencies": []
# }
```

**Key Information**:

- **imports**: What this module depends on (downstream dependencies)
- **imported_by**: What depends on this module (upstream dependents)
- **circular_dependencies**: Problematic cycles if any

### Step 2: Explore Project Structure

Use `list_modules` to get an overview of all modules in the project:

```python
list_modules()

# Returns list of modules with:
# [
#     {
#         "module": "mypackage.models",
#         "file": "/project/mypackage/models.py",
#         "exports": ["User", "Product", "Order"],
#         "classes": 3,
#         "functions": 5,
#         "lines": 234
#     },
#     ...
# ]
```

**Insight**: Identify:

- Core modules (heavily imported by others)
- Leaf modules (no internal dependents)
- Large modules (candidates for splitting)

### Step 3: Build Dependency Map

For each key module, run `analyze_dependencies` to build a complete dependency graph:

```python
# Core business logic module
analyze_dependencies("mypackage.models")

# Service layer
analyze_dependencies("mypackage.services")

# API layer
analyze_dependencies("mypackage.api")

# Build mental model:
# api → services → models → (external: SQLAlchemy, Pydantic)
```

**Pattern Recognition**:

- **Layered Architecture**: API → Service → Model → Database
- **Vertical Slices**: Feature modules with minimal cross-dependencies
- **Utility Hub**: Core utilities imported everywhere

### Step 4: Identify Circular Dependencies

Pay special attention to `circular_dependencies` in the analysis:

```python
analyze_dependencies("mypackage.models")

# If circular dependency exists:
# {
#     "circular_dependencies": [
#         {
#             "cycle": ["mypackage.models", "mypackage.services", "mypackage.models"],
#             "severity": "high"
#         }
#     ]
# }
```

**Circular Dependency Resolution Strategies**:

1. **Extract Interface**: Create a base module both can import
2. **Dependency Injection**: Pass dependencies instead of importing
3. **Lazy Import**: Import inside function instead of module level
4. **Refactor**: Move shared code to separate module

### Step 5: Analyze External Dependencies

Categorize dependencies by type:

```python
# From Step 1 results, extract imports by type:

Internal dependencies: ["mypackage.models", "mypackage.utils"]
→ Impact: Changes affect these modules

External packages: ["sqlalchemy", "pydantic", "requests"]
→ Impact: Version upgrades affect this module

Standard library: ["logging", "typing", "pathlib"]
→ Impact: Python version constraints
```

**Security Consideration**: External dependencies are supply chain risks - track them carefully.

### Step 6: Assess Module Coupling

Calculate coupling metrics from dependency analysis:

**Fan-out (Efferent Coupling)**:

- Count of modules this module imports
- High fan-out = depends on many things = fragile

**Fan-in (Afferent Coupling)**:

- Count of modules that import this module
- High fan-in = many dependents = changes are risky

**Instability**:

- Formula: Fan-out / (Fan-in + Fan-out)
- 0 = Stable (depended on, doesn't depend)
- 1 = Unstable (depends on others, not depended on)

## Complete Example: Analyzing API Module

**Goal**: Understand dependencies of `mypackage.api` module

### Analysis Phase

```text
Step 1: analyze_dependencies("mypackage.api")
→ Imports: ["mypackage.services", "mypackage.auth", "fastapi", "pydantic"]
→ Imported by: [] (it's an entry point, nothing imports it)
→ Circular: None

Step 2: list_modules()
→ API is one of 8 modules in the project
→ API has 450 lines, 0 classes, 12 functions (route handlers)

Step 3: Analyze dependencies of API's imports
→ analyze_dependencies("mypackage.services")
  → Imports: ["mypackage.models", "mypackage.cache"]
→ analyze_dependencies("mypackage.auth")
  → Imports: ["mypackage.models", "jose", "passlib"]

Dependency Chain:
api → services → models
api → auth → models
```

### Dependency Graph

```text
External:
  fastapi, pydantic (API framework)
    ↓
  mypackage.api (API routes)
    ↓
  mypackage.services (Business logic)
  mypackage.auth (Authentication)
    ↓
  mypackage.models (Data models)
    ↓
  sqlalchemy (Database ORM)
```

### Insights Gained

**Architecture Pattern**: Clean layered architecture

- API layer depends on Services and Auth
- Services layer depends on Models
- Models layer depends on Database ORM
- No circular dependencies ✅

**Coupling Metrics**:

- API module: Fan-out = 4, Fan-in = 0, Instability = 1.0 (entry point)
- Services: Fan-out = 2, Fan-in = 1, Instability = 0.67 (moderate)
- Models: Fan-out = 1, Fan-in = 2, Instability = 0.33 (stable)

**Change Impact**:

- Changing API: No impact (nothing imports it)
- Changing Services: Affects API only
- Changing Models: Affects Services, Auth, and transitively API

## Dependency Analysis Checklist

Quick analysis:

- [ ] Run `analyze_dependencies` on target module
- [ ] Check for circular dependencies
- [ ] Identify direct imports and importers

Deep analysis:

- [ ] Run `list_modules` for project overview
- [ ] Build dependency map for key modules
- [ ] Calculate coupling metrics
- [ ] Identify architectural patterns
- [ ] Assess change impact

## Common Dependency Patterns

### Pattern 1: Layered Architecture

```text
UI/API Layer (high instability)
    ↓
Business Logic Layer
    ↓
Data Access Layer
    ↓
Database/External (stable)
```

**Characteristics**:

- Dependencies flow downward
- No upward or lateral dependencies
- Clear separation of concerns

### Pattern 2: Hexagonal/Ports & Adapters

```text
Core Domain (stable, no external deps)
    ↑
Ports (interfaces)
    ↑
Adapters (implementations, unstable)
```

**Characteristics**:

- Core is isolated
- Adapters depend on core
- Easy to swap implementations

### Pattern 3: Microservices/Vertical Slices

```text
Feature A     Feature B     Feature C
   ↓             ↓             ↓
Shared Utils  Shared Utils  Shared Utils
```

**Characteristics**:

- Features are independent
- Minimal cross-feature dependencies
- Shared utilities are stable

### Anti-Pattern: Circular Dependencies

```text
Module A ←→ Module B  (BAD!)
```

**Problems**:

- Import order issues
- Testing difficulties
- Tight coupling

## Refactoring Based on Dependencies

### High Fan-out (Module depends on too many things)

**Problem**: Fragile, breaks when dependencies change
**Solution**:

- Extract interfaces
- Use dependency injection
- Split into smaller modules

### High Fan-in (Many things depend on this module)

**Problem**: Changes affect many modules
**Solution**:

- Ensure stability (comprehensive tests)
- Use semantic versioning
- Consider deprecation warnings

### Circular Dependencies

**Problem**: Import errors, tight coupling
**Solution**:

- Extract shared code to new module
- Use lazy imports
- Refactor to break cycle

### No Clear Architecture

**Problem**: Hard to understand, difficult to change
**Solution**:

- Identify layers from dependency analysis
- Enforce dependency rules
- Refactor toward pattern

## Advanced Analysis Techniques

### Technique 1: Dependency Depth Analysis

```python
# Trace how deep dependencies go
Level 0: mypackage.api
Level 1: mypackage.services, mypackage.auth
Level 2: mypackage.models
Level 3: sqlalchemy

Max depth = 3 (reasonable)
```

### Technique 2: Change Impact Prediction

```python
# If changing mypackage.models:
Direct impact: services, auth (from imported_by)
Indirect impact: api (imports services and auth)
Total modules affected: 3
```

### Technique 3: Dependency Violation Detection

```python
# Define rule: API should not import Models directly
analyze_dependencies("mypackage.api")
→ Check if "mypackage.models" in imports
→ Violation if present
```

### Technique 4: External Dependency Audit

```python
# Collect all external dependencies
for module in list_modules():
    deps = analyze_dependencies(module)
    external = [d for d in deps["imports"] if d["type"] == "external"]

# Result: Complete list of third-party dependencies
# Use for security audits, license compliance
```

## Visualization Tips

**Dependency Graph**:

- Nodes = modules
- Edges = import relationships
- Color = instability (red = unstable, green = stable)

**Layering Diagram**:

- Horizontal layers = architectural tiers
- Arrows point downward = valid dependencies
- Upward arrows = violations

**Circular Dependency Detection**:

- Highlight cycles in red
- Show all modules in cycle
- Indicate break points

## Limitations and Considerations

**Known Limitations**:

- Dynamic imports not detected (`importlib.import_module()`)
- Conditional imports may be missed
- Plugin systems with runtime loading
- External packages only shown as names, not analyzed

**Best Practices**:

- Run analysis regularly (CI/CD integration)
- Track metrics over time (coupling trends)
- Enforce architecture rules (linting)
- Document dependency decisions

**Performance Tips**:

- Cache results for large projects
- Analyze only changed modules in incremental builds
- Use scope parameter to limit analysis depth

## Success Indicators

✅ **Clear architecture**: Identified pattern (layered, hexagonal, etc.)
✅ **No circular dependencies**: All cycles resolved
✅ **Manageable coupling**: Fan-in/fan-out within reasonable limits
✅ **Change impact understood**: Know what breaks when module changes
✅ **External deps tracked**: All third-party dependencies documented

## Related Workflows

- [Refactoring](workflows://refactoring) - Use dependency analysis to plan safe refactoring
- [Code Understanding](workflows://code-understanding) - Understand module context
- [Find All References](workflows://find-references) - See actual import statements

## Related Tools

- `analyze_dependencies` - Core dependency analysis
- `list_modules` - Project structure overview
- `get_module_info` - Detailed module information
- `find_imports` - Find import statements

## Related Issues

- Issue #236: Standalone scripts not in dependency graph (workaround: manual tracking)
