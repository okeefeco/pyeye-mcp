# Module Analysis Tools

Tools for understanding project structure, module organization, and dependency relationships. These 4 tools provide comprehensive analysis of Python packages and modules.

## Table of Contents

1. [list_packages](#list_packages)
2. [list_modules](#list_modules)
3. [analyze_dependencies](#analyze_dependencies)
4. [get_module_info](#get_module_info)

---

## list_packages

List all Python packages in the project with structure information.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
Array<{
  name: string;             // Package name (dotted path)
  path: string;             // File system path
  is_namespace: boolean;    // Whether it's a namespace package
  has_init: boolean;        // Has __init__.py file
  subpackages: string[];    // Direct subpackages
  modules: string[];        // Direct module files
  size: number;            // Total size in bytes
  file_count: number;      // Number of Python files
}>
```

### Examples

```python
# List all packages
packages = list_packages(project_path=".")
# Returns: [
#   {
#     "name": "myapp",
#     "path": "/project/myapp",
#     "is_namespace": false,
#     "has_init": true,
#     "subpackages": ["myapp.models", "myapp.views", "myapp.utils"],
#     "modules": ["__init__.py", "config.py", "main.py"],
#     "size": 45678,
#     "file_count": 15
#   },
#   {
#     "name": "myapp.models",
#     "path": "/project/myapp/models",
#     "is_namespace": false,
#     "has_init": true,
#     "subpackages": [],
#     "modules": ["__init__.py", "user.py", "product.py"],
#     "size": 12345,
#     "file_count": 3
#   }
# ]

# List packages in specific directory
packages = list_packages(project_path="../library")
```

### Error Conditions

- Returns empty array if no packages found
- Skips invalid or inaccessible directories
- Ignores non-Python files

### Performance Notes

- Scans directory tree once
- Results cached until file changes
- Ignores common excluded directories (__pycache__, .git, etc.)

### Use Cases

- Understanding project organization
- Identifying namespace packages
- Finding orphaned modules
- Package size analysis

---

## list_modules

List all Python modules with exports, classes, functions, and metrics.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
Array<{
  module_path: string;      // Import path (e.g., "myapp.models.user")
  file_path: string;        // File system path
  exports: string[];        // Names in __all__ or public names
  classes: Array<{
    name: string;
    line: number;
    methods: number;        // Number of methods
    is_abstract: boolean;
  }>;
  functions: Array<{
    name: string;
    line: number;
    is_async: boolean;
    parameters: number;
  }>;
  imports: {
    stdlib: string[];       // Standard library imports
    third_party: string[];  // Third-party package imports
    local: string[];        // Local project imports
  };
  metrics: {
    lines: number;          // Total lines
    code_lines: number;     // Non-blank, non-comment lines
    comment_lines: number;
    docstring_lines: number;
    complexity: number;     // Cyclomatic complexity
  };
}>
```

### Examples

```python
# List all modules with details
modules = list_modules()
# Returns: [
#   {
#     "module_path": "myapp.models.user",
#     "file_path": "/project/myapp/models/user.py",
#     "exports": ["User", "UserProfile", "create_user"],
#     "classes": [
#       {"name": "User", "line": 10, "methods": 5, "is_abstract": false},
#       {"name": "UserProfile", "line": 50, "methods": 3, "is_abstract": false}
#     ],
#     "functions": [
#       {"name": "create_user", "line": 100, "is_async": false, "parameters": 3},
#       {"name": "validate_email", "line": 120, "is_async": false, "parameters": 1}
#     ],
#     "imports": {
#       "stdlib": ["datetime", "typing"],
#       "third_party": ["sqlalchemy", "pydantic"],
#       "local": ["myapp.utils", "myapp.config"]
#     },
#     "metrics": {
#       "lines": 150,
#       "code_lines": 100,
#       "comment_lines": 20,
#       "docstring_lines": 30,
#       "complexity": 15
#     }
#   }
# ]

# Analyze specific project
modules = list_modules(project_path="../shared-lib")
```

### Error Conditions

- Skips files that can't be parsed
- Returns partial info for syntax errors
- Complexity may be approximate for very complex functions

### Performance Notes

- Parses all Python files in project
- Can be slow for large codebases
- Results cached per file modification
- Parallel processing for multiple files

### Use Cases

- Code quality assessment
- Finding large/complex modules
- Import analysis
- Documentation coverage
- API surface analysis

---

## analyze_dependencies

Analyze import dependencies for a module including circular dependency detection.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `module_path` | string | ✅ | - | Import path of the module (e.g., "myapp.services") |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
{
  module: string;                    // The analyzed module
  file_path: string;                // File system path

  imports: Array<{                  // What this module imports
    module: string;                 // Imported module name
    names: string[];                // Specific names imported
    is_relative: boolean;
    is_stdlib: boolean;
    is_third_party: boolean;
    is_local: boolean;
    line: number;                   // Line number of import
  }>;

  imported_by: Array<{              // Modules that import this one
    module: string;
    names: string[];                // What they import from this module
    file_path: string;
  }>;

  dependencies: {
    direct: string[];               // Direct dependencies
    indirect: string[];             // Transitive dependencies
    depth: number;                  // Max dependency depth
  };

  circular_dependencies: Array<{    // Circular import chains
    chain: string[];                // Module names forming the cycle
    severity: "warning" | "error";  // Based on import type
  }>;

  metrics: {
    import_count: number;           // Number of imports
    imported_by_count: number;      // Number of modules importing this
    coupling: number;               // Coupling metric (0-1)
    cohesion: number;              // Cohesion metric (0-1)
  };
}
```

### Examples

```python
# Analyze module dependencies
deps = analyze_dependencies("myapp.services.user_service")
# Returns: {
#   "module": "myapp.services.user_service",
#   "file_path": "/project/myapp/services/user_service.py",
#   "imports": [
#     {
#       "module": "myapp.models.user",
#       "names": ["User", "UserProfile"],
#       "is_relative": false,
#       "is_local": true,
#       "line": 3
#     },
#     {
#       "module": "typing",
#       "names": ["List", "Optional"],
#       "is_stdlib": true,
#       "line": 1
#     }
#   ],
#   "imported_by": [
#     {
#       "module": "myapp.api.endpoints",
#       "names": ["UserService"],
#       "file_path": "/project/myapp/api/endpoints.py"
#     }
#   ],
#   "dependencies": {
#     "direct": ["myapp.models.user", "typing", "datetime"],
#     "indirect": ["myapp.database", "sqlalchemy"],
#     "depth": 3
#   },
#   "circular_dependencies": [
#     {
#       "chain": ["myapp.services.user_service", "myapp.models.user", "myapp.services.user_service"],
#       "severity": "warning"
#     }
#   ],
#   "metrics": {
#     "import_count": 8,
#     "imported_by_count": 3,
#     "coupling": 0.6,
#     "cohesion": 0.8
#   }
# }

# Check for circular dependencies
deps = analyze_dependencies("myapp.core")
if deps["circular_dependencies"]:
    print(f"Warning: {len(deps['circular_dependencies'])} circular dependencies found!")
    for cycle in deps["circular_dependencies"]:
        print(f"  Cycle: {' -> '.join(cycle['chain'])}")
```

### Error Conditions

- Raises error if module doesn't exist
- Returns partial results for parse errors
- May miss dynamic imports
- Circular detection limited to static imports

### Performance Notes

- Analyzes entire import graph
- Can be slow for modules with many dependencies
- Caches dependency graph
- Parallel analysis of import chains

### Use Cases

- Detecting circular dependencies
- Understanding module coupling
- Refactoring planning
- Dependency injection points
- Architecture validation

---

## get_module_info

Get detailed information about a specific module including all exports, classes, functions, and dependencies.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `module_path` | string | ✅ | - | Import path of the module (e.g., "myapp.models.user") |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
{
  module_path: string;           // Import path
  file_path: string;            // File system path
  package: string;              // Parent package

  documentation: {
    module_docstring: string;    // Module-level docstring
    has_docstrings: boolean;     // Whether functions/classes have docstrings
    docstring_coverage: number;  // Percentage (0-100)
  };

  exports: {
    all: string[];              // __all__ definition if present
    public: string[];           // Public names (no underscore)
    private: string[];          // Private names (underscore prefix)
    imported: string[];         // Names imported from other modules
  };

  classes: Array<{
    name: string;
    line: number;
    docstring: string;
    base_classes: string[];     // Parent classes
    methods: Array<{
      name: string;
      line: number;
      is_async: boolean;
      is_static: boolean;
      is_classmethod: boolean;
      is_property: boolean;
      parameters: string[];
    }>;
    attributes: Array<{
      name: string;
      type_hint: string;
      default_value: string;
    }>;
  }>;

  functions: Array<{
    name: string;
    line: number;
    docstring: string;
    is_async: boolean;
    is_generator: boolean;
    parameters: Array<{
      name: string;
      type_hint: string;
      default: string;
    }>;
    return_type: string;
    decorators: string[];
  }>;

  variables: Array<{
    name: string;
    line: number;
    type_hint: string;
    value: string;              // String representation
  }>;

  imports: {
    imports: Array<ImportInfo>;  // See analyze_dependencies
    from_imports: Array<ImportInfo>;
  };

  dependencies: {               // Summary from analyze_dependencies
    direct: string[];
    circular: boolean;
    import_count: number;
    imported_by_count: number;
  };

  metrics: {
    lines: number;
    code_lines: number;
    comment_lines: number;
    docstring_lines: number;
    complexity: number;
    maintainability_index: number;  // 0-100
  };
}
```

### Examples

```python
# Get comprehensive module information
info = get_module_info("myapp.models.user")
# Returns: {
#   "module_path": "myapp.models.user",
#   "file_path": "/project/myapp/models/user.py",
#   "package": "myapp.models",
#
#   "documentation": {
#     "module_docstring": "User model definitions for the application.",
#     "has_docstrings": true,
#     "docstring_coverage": 85.5
#   },
#
#   "exports": {
#     "all": ["User", "UserProfile", "create_user"],
#     "public": ["User", "UserProfile", "create_user", "UserRole"],
#     "private": ["_hash_password", "_validate_email"],
#     "imported": ["BaseModel"]
#   },
#
#   "classes": [
#     {
#       "name": "User",
#       "line": 15,
#       "docstring": "Represents a system user.",
#       "base_classes": ["BaseModel"],
#       "methods": [
#         {
#           "name": "__init__",
#           "line": 20,
#           "is_async": false,
#           "parameters": ["self", "email", "username"]
#         },
#         {
#           "name": "set_password",
#           "line": 30,
#           "is_async": false,
#           "parameters": ["self", "password"]
#         }
#       ],
#       "attributes": [
#         {"name": "email", "type_hint": "str", "default_value": "None"},
#         {"name": "username", "type_hint": "str", "default_value": "None"}
#       ]
#     }
#   ],
#
#   "functions": [
#     {
#       "name": "create_user",
#       "line": 100,
#       "docstring": "Factory function to create a new user.",
#       "is_async": true,
#       "is_generator": false,
#       "parameters": [
#         {"name": "email", "type_hint": "str", "default": "None"},
#         {"name": "username", "type_hint": "str", "default": "None"}
#       ],
#       "return_type": "User",
#       "decorators": ["@validate_input"]
#     }
#   ],
#
#   "metrics": {
#     "lines": 250,
#     "code_lines": 180,
#     "comment_lines": 30,
#     "docstring_lines": 40,
#     "complexity": 12,
#     "maintainability_index": 75
#   }
# }

# Quick module assessment
info = get_module_info("myapp.utils.helpers")
print(f"Module: {info['module_path']}")
print(f"Exports: {', '.join(info['exports']['public'])}")
print(f"Complexity: {info['metrics']['complexity']}")
print(f"Maintainability: {info['metrics']['maintainability_index']}/100")
```

### Error Conditions

- Raises error if module not found
- Returns partial info for syntax errors
- Some metrics may be estimates
- Dynamic exports not detected

### Performance Notes

- Combines multiple analysis passes
- Heavier than other tools
- Fully cached results
- Consider using lighter tools if only need specific info

### Use Cases

- Module documentation generation
- API surface analysis
- Code review preparation
- Refactoring planning
- Quality metrics tracking

---

## Common Patterns

### Project Analysis Workflow

```python
# 1. List all packages
packages = list_packages()
print(f"Found {len(packages)} packages")

# 2. Analyze modules in each package
for package in packages:
    modules = list_modules()
    complex_modules = [m for m in modules
                      if m["metrics"]["complexity"] > 10]

    if complex_modules:
        print(f"Package {package['name']} has {len(complex_modules)} complex modules")

# 3. Check for circular dependencies
for module in modules:
    deps = analyze_dependencies(module["module_path"])
    if deps["circular_dependencies"]:
        print(f"WARNING: {module['module_path']} has circular dependencies")

# 4. Get detailed info for problematic modules
for module_path in problematic_modules:
    info = get_module_info(module_path)
    print(f"{module_path}:")
    print(f"  Complexity: {info['metrics']['complexity']}")
    print(f"  Coupling: {info['dependencies']['import_count']}")
    print(f"  Maintainability: {info['metrics']['maintainability_index']}")
```

### Dependency Graph Building

```python
# Build complete dependency graph
def build_dependency_graph(project_path="."):
    modules = list_modules(project_path)
    graph = {}

    for module in modules:
        deps = analyze_dependencies(module["module_path"])
        graph[module["module_path"]] = {
            "imports": deps["dependencies"]["direct"],
            "imported_by": [m["module"] for m in deps["imported_by"]],
            "circular": len(deps["circular_dependencies"]) > 0
        }

    return graph

# Find most coupled modules
graph = build_dependency_graph()
coupling_scores = {}
for module, data in graph.items():
    coupling_scores[module] = len(data["imports"]) + len(data["imported_by"])

most_coupled = sorted(coupling_scores.items(), key=lambda x: x[1], reverse=True)[:10]
```

### Module Quality Assessment

```python
def assess_module_quality(module_path):
    info = get_module_info(module_path)

    issues = []

    # Check complexity
    if info["metrics"]["complexity"] > 15:
        issues.append(f"High complexity: {info['metrics']['complexity']}")

    # Check documentation
    if info["documentation"]["docstring_coverage"] < 70:
        issues.append(f"Low documentation: {info['documentation']['docstring_coverage']}%")

    # Check dependencies
    deps = analyze_dependencies(module_path)
    if deps["circular_dependencies"]:
        issues.append(f"Circular dependencies: {len(deps['circular_dependencies'])}")

    if deps["metrics"]["coupling"] > 0.7:
        issues.append(f"High coupling: {deps['metrics']['coupling']}")

    # Check size
    if info["metrics"]["code_lines"] > 500:
        issues.append(f"Large module: {info['metrics']['code_lines']} lines")

    return {
        "module": module_path,
        "quality_score": info["metrics"]["maintainability_index"],
        "issues": issues
    }
```

## Related Tools

- __Navigation__: Use [Core Navigation Tools](./core-navigation.md) to navigate to specific symbols found in analysis
- __Framework Analysis__: For framework-specific module analysis:
  - [Pydantic Tools](./pydantic-tools.md) for model analysis
  - [Flask Tools](./flask-tools.md) for route/view analysis
  - [Django Tools](./django-tools.md) for Django app analysis

## Best Practices

1. __Start with `list_packages`__ to understand project structure
2. __Use `list_modules` for broad analysis__, then drill down with `get_module_info`
3. __Run `analyze_dependencies` regularly__ to detect circular dependencies early
4. __Cache results__ - these operations can be expensive for large codebases
5. __Combine with navigation tools__ to jump to problematic code quickly
6. __Set thresholds__ for metrics and automate quality checks
