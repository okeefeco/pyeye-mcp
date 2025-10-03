# Safe Refactoring Workflow

## Goal

Perform safe refactoring of classes, functions, or modules by understanding the full impact of changes before making them. This workflow ensures you don't break existing code by analyzing:

- Inheritance hierarchies (subclasses that depend on the structure)
- All references (code that uses the symbol)
- Module dependencies (imports and usage relationships)

## When to Use This Workflow

- "I want to rename this class safely"
- "Can I change this function's signature?"
- "What will break if I modify this?"
- "Help me refactor this module"

## Steps

### Step 1: Find All Subclasses (For Classes)

**If refactoring a class**, first check the inheritance hierarchy:

Use `find_subclasses` to find all classes that inherit from the target class:

```python
# Example call
find_subclasses(
    base_class="Animal",
    include_indirect=True,
    show_hierarchy=True
)

# Returns:
# [
#     {
#         "name": "Dog",
#         "file": "/project/animals/dog.py",
#         "hierarchy": ["Animal", "Dog"]
#     },
#     {
#         "name": "Puppy",
#         "file": "/project/animals/puppy.py",
#         "hierarchy": ["Animal", "Dog", "Puppy"]
#     }
# ]
```

**Why this matters**: Subclasses inherit methods/attributes. Changing the base class can break subclass implementations.

### Step 2: Find All References

Use the **[Find All References Workflow](workflows://find-references)** to locate every place the symbol is used:

1. Get fully qualified name with `get_type_info`
2. Find package references with `find_references`
3. Find script/notebook references with `Grep`
4. Combine results

**Example Output**:

- 15 references found in 8 files
- Includes: direct instantiation, imports, type hints, inheritance

**Why this matters**: Every reference is a place that might need updating after your change.

### Step 3: Analyze Module Dependencies

If refactoring affects a module, understand its dependency relationships:

Use `analyze_dependencies` to see what imports the module and what it imports:

```python
# Example call
analyze_dependencies(
    module_path="mypackage.models",
    scope="all"
)

# Returns:
# {
#     "module": "mypackage.models",
#     "imports": ["sqlalchemy", "pydantic"],
#     "imported_by": ["mypackage.services", "mypackage.api"],
#     "circular_dependencies": []
# }
```

**Why this matters**:

- `imported_by` shows which modules will be affected
- `circular_dependencies` reveals potential issues
- `imports` shows external dependencies to consider

### Step 4: Review and Plan Changes

Based on Steps 1-3, create a refactoring plan:

**Impact Assessment**:

- How many subclasses affected? (Step 1)
- How many references to update? (Step 2)
- Which modules depend on this? (Step 3)

**Refactoring Strategy**:

- **Low Impact** (<5 references, no subclasses): Proceed with confidence
- **Medium Impact** (5-20 references, 1-3 subclasses): Update carefully
- **High Impact** (>20 references, complex hierarchy): Consider deprecation strategy

**Change Order**:

1. Update base class/function
2. Update direct subclasses
3. Update all references (from Step 2)
4. Update dependent modules (from Step 3)

### Step 5: Make Changes with Validation

Execute changes in order, validating each step:

1. **Make the change** to the target symbol
2. **Run tests** to catch immediate breaks
3. **Re-run find_references** to verify all usages are updated
4. **Check type hints** if using type checking (mypy/pyright)

## Complete Example: Renaming a Class

**Goal**: Rename `User` class to `Customer`

### Analysis Phase

```text
Step 1: find_subclasses(base_class="User", show_hierarchy=True)
→ Found: PremiumUser, AdminUser (2 subclasses)

Step 2: Find All References (using find-references workflow)
→ get_type_info → "mypackage.models.User"
→ find_references → 12 package references
→ Grep → 3 notebook references
→ Total: 15 references across 10 files

Step 3: analyze_dependencies(module_path="mypackage.models")
→ imported_by: ["mypackage.services", "mypackage.api", "tests.test_models"]
→ No circular dependencies
```

### Impact Assessment

- **Subclasses**: 2 (PremiumUser, AdminUser)
- **References**: 15 total
- **Dependent modules**: 3

**Risk Level**: Medium (manageable with careful execution)

### Refactoring Plan

1. Rename `User` → `Customer` in models.py
2. Update subclasses: PremiumUser, AdminUser
3. Update 12 package references
4. Update 3 notebook references
5. Run full test suite
6. Verify with find_references again

## Refactoring Checklist

Before changing code:

- [ ] Run `find_subclasses` (for classes)
- [ ] Run find-references workflow
- [ ] Run `analyze_dependencies` (for modules)
- [ ] Document impact assessment
- [ ] Create refactoring plan

During refactoring:

- [ ] Follow planned change order
- [ ] Run tests after each major change
- [ ] Update type hints and docstrings
- [ ] Handle both direct and indirect dependencies

After refactoring:

- [ ] Re-run find_references (should show new name only)
- [ ] Run full test suite
- [ ] Check for deprecation warnings
- [ ] Update documentation

## Common Refactoring Patterns

### Pattern 1: Rename Symbol

1. Find all references
2. Update all at once
3. Validate no old name remains

### Pattern 2: Change Function Signature

1. Find all references
2. Check if calls use positional or keyword args
3. Use deprecation warnings for gradual migration

### Pattern 3: Move to Different Module

1. Find all imports
2. Update import statements
3. Consider adding compatibility import in old location

### Pattern 4: Split Large Class

1. Find subclasses (decide which inherits from what)
2. Find all references (categorize by usage)
3. Create new classes
4. Migrate references gradually

## Limitations and Considerations

**Known Limitations**:

- Dynamic imports (e.g., `importlib.import_module()`) may not be found
- String-based references (e.g., class name in config files) need manual search
- Monkey-patching or runtime modifications won't be detected

**Best Practices**:

- Always use version control (git) before refactoring
- Run tests frequently during the process
- Consider feature flags for large refactorings
- Document breaking changes in commit messages

**Performance Tips**:

- Cache results of find_references for reuse
- Process files in dependency order (leaves first, roots last)
- Use batch operations when possible

## Success Indicators

✅ **Complete analysis**: Understood all subclasses, references, and dependencies
✅ **Planned execution**: Clear order of changes with validation points
✅ **No broken references**: All old symbol usages updated
✅ **Tests passing**: Full test suite validates changes
✅ **Clean verification**: Re-running find_references shows only new symbol name

## Related Workflows

- [Find All References](workflows://find-references) - Used in Step 2
- [Dependency Analysis](workflows://dependency-analysis) - Deep dive into module relationships
- [Code Understanding](workflows://code-understanding) - Understanding unfamiliar code before refactoring

## Related Issues

- Issue #234: find_subclasses missing direct subclasses (may need to verify inheritance manually)
- Issue #236: Standalone scripts not included in find_references (this workflow includes Grep workaround)
