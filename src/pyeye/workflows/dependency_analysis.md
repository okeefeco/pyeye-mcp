# Dependency Analysis Workflow

## Goal

Understand module dependencies, import relationships, and architectural patterns in a Python project. This workflow helps you:

- Map import relationships (who imports what)
- Identify circular dependencies
- Understand module coupling
- Analyze architectural layers
- Plan refactoring safely

> Tool mechanics (call signatures, return shapes, handles, edges) live in
> `skills/python-explore/SKILL.md`. This workflow references tools by name and
> focuses on the dependency-analysis methodology.

## When to Use This Workflow

- "What does this module depend on?"
- "Which modules use this module?"
- "Are there circular dependencies?"
- "How is the codebase structured?"
- "Can I safely move this module?"

## Steps

### Step 1: Analyze single-module dependencies

Run `analyze_dependencies` on the target module. It is still the dedicated
dependency tool: it reports the module's internal/external/stdlib imports, its
importers, and any circular dependencies in one call.

Key information to read off the result:

- **imports** — what this module depends on (downstream dependencies)
- **imported_by** — what depends on this module (upstream dependents)
- **circular_dependencies** — problematic cycles, if any

For a single edge rather than the full report, `expand(edge="imports")` lists what
a module imports and `expand(edge="imported_by")` lists its importers.

### Step 2: Get a project overview

Use `outline` to see the structural skeleton of a package or module before drilling
in — its modules, classes, and top-level defs. Use this to spot:

- Core modules (heavily imported by others)
- Leaf modules (no internal dependents)
- Large modules (candidates for splitting)

### Step 3: Build a dependency map

Run `analyze_dependencies` on each key module to build the graph by hand, e.g.:

```text
api → services → models → (external: SQLAlchemy, Pydantic)
```

To follow the import closure across multiple hops in one call, use
`trace(follow=["imports"])` from a starting module.

**Pattern recognition:**

- **Layered architecture**: API → Service → Model → Database
- **Vertical slices**: feature modules with minimal cross-dependencies
- **Utility hub**: core utilities imported everywhere

### Step 4: Identify circular dependencies

Pay special attention to `circular_dependencies` in each `analyze_dependencies`
result. Resolution strategies:

1. **Extract interface** — create a base module both can import
2. **Dependency injection** — pass dependencies instead of importing
3. **Lazy import** — import inside a function instead of at module level
4. **Refactor** — move shared code to a separate module

### Step 5: Categorize external dependencies

Split the imports from Step 1 by type:

- **Internal** — changes here affect your own modules
- **External packages** — version upgrades affect this module
- **Standard library** — Python version constraints

**Security consideration**: external dependencies are supply-chain risks — track
them carefully.

### Step 6: Assess module coupling

Compute coupling metrics from the dependency data:

- **Fan-out (efferent coupling)**: count of modules this module imports. High
  fan-out = depends on many things = fragile.
- **Fan-in (afferent coupling)**: count of modules that import this module. High
  fan-in = many dependents = changes are risky.
- **Instability**: `fan_out / (fan_in + fan_out)`. `0` = stable (depended on,
  doesn't depend); `1` = unstable (depends on others, not depended on).

## Worked Example: Analyzing an API Module

**Goal**: understand dependencies of `mypackage.api`.

```text
analyze_dependencies("mypackage.api")
  → imports: services, auth, fastapi, pydantic
  → imported_by: []           (entry point — nothing imports it)
  → circular: none

outline("mypackage")          → api is one of 8 modules

analyze_dependencies("mypackage.services") → imports: models, cache
analyze_dependencies("mypackage.auth")     → imports: models, jose, passlib
```

Resulting dependency graph:

```text
fastapi, pydantic           (API framework)
        ↓
mypackage.api               (API routes)
        ↓
mypackage.services / auth   (business logic / authentication)
        ↓
mypackage.models            (data models)
        ↓
sqlalchemy                  (database ORM)
```

**Insights:**

- Clean layered architecture; dependencies flow downward; no cycles.
- Coupling: API fan-out 4 / fan-in 0 / instability 1.0 (entry point); Services
  fan-out 2 / fan-in 1 / instability 0.67; Models fan-out 1 / fan-in 2 /
  instability 0.33 (stable).
- Change impact: changing Models affects Services, Auth, and transitively API.

## Dependency Analysis Checklist

Quick analysis:

- [ ] Run `analyze_dependencies` on the target module
- [ ] Check for circular dependencies
- [ ] Note direct imports and importers

Deep analysis:

- [ ] Run `outline` for a project overview
- [ ] Build a dependency map for key modules (`trace(follow=["imports"])` for closure)
- [ ] Calculate coupling metrics
- [ ] Identify architectural patterns
- [ ] Assess change impact

## Common Dependency Patterns

- **Layered**: dependencies flow downward (UI/API → business logic → data access
  → database); no upward or lateral edges.
- **Hexagonal / ports & adapters**: stable core domain with no external deps;
  adapters depend on core; easy to swap implementations.
- **Vertical slices**: independent features sharing only stable utilities.
- **Anti-pattern — circular**: `A ←→ B`. Causes import-order issues, testing
  difficulty, and tight coupling.

## Refactoring Based on Dependencies

- **High fan-out** (depends on too many things): extract interfaces, use
  dependency injection, or split into smaller modules.
- **High fan-in** (many dependents): ensure stability with comprehensive tests,
  use semantic versioning, and add deprecation warnings before changes.
- **Circular dependencies**: extract shared code to a new module, use lazy
  imports, or refactor to break the cycle.
- **No clear architecture**: identify layers from the dependency data, then
  enforce dependency rules and refactor toward a pattern.

## Limitations and Considerations

**Known limitations:**

- Dynamic imports are not detected (`importlib.import_module()`).
- Conditional imports may be missed.
- Plugin systems with runtime loading are invisible.
- External packages are shown as names only, not analyzed.

**Best practices:**

- Run analysis regularly (CI/CD integration).
- Track coupling metrics over time.
- Enforce architecture rules via linting.
- Document dependency decisions.

## Success Indicators

- **Clear architecture**: identified a pattern (layered, hexagonal, etc.)
- **No circular dependencies**: all cycles resolved
- **Manageable coupling**: fan-in/fan-out within reasonable limits
- **Change impact understood**: you know what breaks when a module changes
- **External deps tracked**: all third-party dependencies documented

## Related Workflows

- [Refactoring](workflows://refactoring) — use dependency analysis to plan safe refactoring
- [Code Understanding](workflows://code-understanding) — understand module context

## Related Tools

- `analyze_dependencies` — core dependency analysis (imports, importers, cycles)
- `outline` — project/module structure overview
- `expand` (edge `imports` / `imported_by`) — a single import edge from a module
- `trace` (`follow=["imports"]`) — multi-hop import closure
- `inspect` — structural detail for a resolved module or symbol

## Related Issues

- Issue #236: standalone scripts not in dependency graph (workaround: manual tracking)
