# Core Navigation Tools

The core navigation tools provide essential functionality for navigating and understanding Python code. These 11 tools form the foundation of the Python Code Intelligence MCP Server.

## Table of Contents

1. [find_symbol](#find_symbol)
2. [goto_definition](#goto_definition)
3. [find_references](#find_references)
4. [get_type_info](#get_type_info)
5. [find_imports](#find_imports)
6. [get_call_hierarchy](#get_call_hierarchy)
7. [configure_packages](#configure_packages)
8. [find_symbol_multi](#find_symbol_multi)
9. [configure_namespace_package](#configure_namespace_package)
10. [find_in_namespace](#find_in_namespace)
11. [list_project_structure](#list_project_structure)

---

## find_symbol

Find symbol definitions in the project, including support for compound symbols.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | ✅ | - | Symbol name to search for (supports compound symbols like "Class.method") |
| `project_path` | string | ❌ | "." | Root path of the project to search |
| `fuzzy` | boolean | ❌ | false | Whether to use fuzzy matching (only for simple symbols) |
| `use_config` | boolean | ❌ | true | Whether to use configuration file for additional packages |

### Returns

```typescript
Array<{
  name: string;           // Symbol name
  type: string;          // Symbol type: "class", "function", "variable", "module"
  file: string;          // File path containing the symbol
  line: number;          // Line number (1-indexed)
  column: number;        // Column number (0-indexed)
  import_paths: string[]; // All possible import paths for the symbol
}>
```

### Examples

```python
# Find a specific class
result = find_symbol("UserModel")
# Returns: [{
#   "name": "UserModel",
#   "type": "class",
#   "file": "/project/models/user.py",
#   "line": 15,
#   "column": 0,
#   "import_paths": ["models.user.UserModel", "models.UserModel"]
# }]

# Find a specific method of a class (compound symbol)
result = find_symbol("UserModel.__init__")
# Returns: [{
#   "name": "__init__",
#   "type": "function",
#   "file": "/project/models/user.py",
#   "line": 17,
#   "column": 4,
#   "import_paths": ["models.user.UserModel.__init__"]
# }]

# Find a class method (compound symbol)
result = find_symbol("Calculator.add")
# Returns only the add method of Calculator class, not other add methods

# Find a module function (compound symbol)
result = find_symbol("utils.helpers.format_date")
# Returns the specific format_date function in utils.helpers module

# Find with fuzzy matching (simple symbols only)
result = find_symbol("UsrMdl", fuzzy=True)
# May return matches like "UserModel", "UserModule", etc.

# Search in specific project
result = find_symbol("Config", project_path="/path/to/project")
```

### Compound Symbol Support

**New in v0.3.0**: The `find_symbol` tool now supports compound symbols, allowing you to search for specific methods, attributes, or nested symbols:

- **Class methods**: `ClassName.method_name` - finds only that specific method
- **Magic methods**: `Model.__init__`, `Model.__str__` - finds special methods
- **Module functions**: `module.function` or `package.module.function`
- **Nested classes**: `OuterClass.InnerClass.method`
- **Properties**: `User.email` - finds property definitions

This provides more precise results compared to searching for the method name alone, which would return all methods with that name across all classes.

### Error Conditions

- Raises `ValidationError` if `name` is empty
- Returns empty array if no symbols found
- Respects `PYCODEMCP_MAX_FILE_SIZE` for file analysis

### Performance Notes

- Results are cached for 5 minutes (configurable via `PYCODEMCP_CACHE_TTL`)
- Fuzzy matching is slower than exact matching
- Large projects may take longer on first search

---

## goto_definition

Go to symbol definition from a specific position.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | string | ✅ | - | Path to the file |
| `line` | number | ✅ | - | Line number (1-indexed) |
| `column` | number | ✅ | - | Column number (0-indexed) |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
{
  file: string;     // File containing the definition
  line: number;     // Line number of definition
  column: number;   // Column number of definition
  name: string;     // Name of the defined symbol
  type: string;     // Type of symbol
} | null
```

### Examples

```python
# Jump to definition of symbol at cursor position
definition = goto_definition(
    file="app.py",
    line=42,
    column=15
)
# Returns: {
#   "file": "/project/models/user.py",
#   "line": 25,
#   "column": 4,
#   "name": "User",
#   "type": "class"
# }

# Returns None if no definition found
definition = goto_definition(
    file="config.py",
    line=10,
    column=5
)
# Returns: None
```

### Error Conditions

- Returns `None` if no definition found
- Raises `FileNotFoundError` if file doesn't exist
- Raises `ValidationError` for invalid line/column numbers

### Performance Notes

- Uses Jedi's goto functionality for accurate results
- Fast operation, typically < 100ms

---

## find_references

Find all references to the symbol at a specific position.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | string | ✅ | - | Path to the file |
| `line` | number | ✅ | - | Line number (1-indexed) |
| `column` | number | ✅ | - | Column number (0-indexed) |
| `project_path` | string | ❌ | "." | Root path of the project |
| `include_definitions` | boolean | ❌ | true | Whether to include definitions in results |

### Returns

```typescript
Array<{
  file: string;       // File containing the reference
  line: number;       // Line number of reference
  column: number;     // Column number of reference
  context: string;    // Line of code containing the reference
  type: string;       // "usage" or "definition"
}>
```

### Examples

```python
# Find all usages of a class
references = find_references(
    file="models/user.py",
    line=15,  # Line where User class is defined
    column=6
)
# Returns: [
#   {"file": "views.py", "line": 10, "column": 12, "context": "user = User()", "type": "usage"},
#   {"file": "tests.py", "line": 25, "column": 8, "context": "assert isinstance(obj, User)", "type": "usage"}
# ]

# Exclude definitions from results
references = find_references(
    file="utils.py",
    line=30,
    column=4,
    include_definitions=False
)
```

### Error Conditions

- Returns empty array if no references found
- File must exist and be readable
- Invalid positions return empty results

### Performance Notes

- May be slow for symbols used extensively
- Searches entire project by default
- Can be limited by configuration

---

## get_type_info

Get type information at a specific position.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | string | ✅ | - | Path to the file |
| `line` | number | ✅ | - | Line number (1-indexed) |
| `column` | number | ✅ | - | Column number (0-indexed) |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
{
  type: string;           // Inferred type (e.g., "str", "List[int]", "User")
  docstring: string;      // Associated docstring if available
  signature: string;      // Function/method signature if applicable
  module: string;         // Module where type is defined
  is_builtin: boolean;    // Whether it's a built-in type
}
```

### Examples

```python
# Get type of a variable
type_info = get_type_info(
    file="app.py",
    line=50,
    column=10
)
# Returns: {
#   "type": "List[User]",
#   "docstring": "",
#   "module": "typing",
#   "is_builtin": false
# }

# Get function signature
type_info = get_type_info(
    file="utils.py",
    line=25,
    column=4
)
# Returns: {
#   "type": "function",
#   "signature": "process_data(items: List[str], config: Config) -> Dict[str, Any]",
#   "docstring": "Process data items according to config.",
#   "module": "utils",
#   "is_builtin": false
# }
```

### Error Conditions

- Returns minimal info for unresolvable types
- May return "Any" for dynamic types
- Empty docstring if none available

### Performance Notes

- Uses Jedi's type inference
- Fast for simple types, slower for complex inference
- Cached per file modification

---

## find_imports

Find all imports of a specific module in the project.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `module_name` | string | ✅ | - | Name of the module to find imports for |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
Array<{
  file: string;         // File containing the import
  line: number;         // Line number of import statement
  import_statement: string; // The actual import statement
  imported_names: string[]; // Names imported from the module
  is_relative: boolean;     // Whether it's a relative import
}>
```

### Examples

```python
# Find all imports of a module
imports = find_imports("models.user")
# Returns: [
#   {
#     "file": "views.py",
#     "line": 5,
#     "import_statement": "from models.user import User, UserProfile",
#     "imported_names": ["User", "UserProfile"],
#     "is_relative": false
#   },
#   {
#     "file": "tests/test_user.py",
#     "line": 3,
#     "import_statement": "import models.user",
#     "imported_names": ["models.user"],
#     "is_relative": false
#   }
# ]

# Find imports of standard library module
imports = find_imports("typing")
```

### Error Conditions

- Returns empty array if module not imported anywhere
- Module name must be valid Python module path
- Handles both absolute and relative imports

### Performance Notes

- Scans all Python files in project
- Results cached until files change
- Can be slow for large projects

---

## get_call_hierarchy

Get the call hierarchy for a function.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `function_name` | string | ✅ | - | Name of the function |
| `file` | string | ❌ | null | Optional file to search in (searches whole project if not specified) |
| `project_path` | string | ❌ | "." | Root path of the project |

### Returns

```typescript
{
  function: {
    name: string;
    file: string;
    line: number;
  };
  callers: Array<{      // Functions that call this function
    name: string;
    file: string;
    line: number;
    context: string;    // Line of code with the call
  }>;
  callees: Array<{      // Functions called by this function
    name: string;
    file: string;
    line: number;
    context: string;
  }>;
}
```

### Examples

```python
# Get call hierarchy for a function
hierarchy = get_call_hierarchy("process_data")
# Returns: {
#   "function": {"name": "process_data", "file": "utils.py", "line": 45},
#   "callers": [
#     {"name": "main", "file": "app.py", "line": 100, "context": "result = process_data(items)"},
#     {"name": "batch_process", "file": "batch.py", "line": 55, "context": "process_data(batch)"}
#   ],
#   "callees": [
#     {"name": "validate", "file": "utils.py", "line": 47, "context": "validate(item)"},
#     {"name": "transform", "file": "utils.py", "line": 50, "context": "transform(validated)"}
#   ]
# }

# Search in specific file
hierarchy = get_call_hierarchy("helper_function", file="helpers.py")
```

### Error Conditions

- Returns empty callers/callees if none found
- Function must exist in project
- May miss dynamic calls

### Performance Notes

- Can be slow for frequently used functions
- Analyzes entire project for callers
- Cached based on file modifications

---

## configure_packages

Configure additional package locations for analysis.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `packages` | array[string] | ❌ | null | List of package paths to include |
| `namespaces` | object | ❌ | null | Namespace packages with their repo paths |
| `save` | boolean | ❌ | true | Whether to save configuration to .pycodemcp.json |

### Returns

```typescript
{
  packages: string[];              // Currently configured packages
  namespaces: {[key: string]: string[]}; // Configured namespaces
  config_file: string;            // Path to configuration file
  auto_discovered: string[];      // Auto-discovered packages
}
```

### Examples

```python
# Add additional packages
config = configure_packages(
    packages=["../my-lib", "~/repos/shared-utils"],
    namespaces={
        "company": ["~/repos/company-auth", "~/repos/company-api"]
    }
)
# Returns: {
#   "packages": ["../my-lib", "~/repos/shared-utils"],
#   "namespaces": {"company": ["~/repos/company-auth", "~/repos/company-api"]},
#   "config_file": ".pycodemcp.json",
#   "auto_discovered": []
# }

# Add packages without saving
config = configure_packages(
    packages=["../temp-package"],
    save=False
)
```

### Error Conditions

- Invalid paths are skipped with warning
- Creates .pycodemcp.json if it doesn't exist
- Validates package paths exist

### Performance Notes

- Configuration changes trigger cache clear
- New packages analyzed on first use
- File watchers created for new packages

---

## find_symbol_multi

Find symbol across multiple projects.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | ✅ | - | Symbol name to search for |
| `project_paths` | array[string] | ✅ | - | List of project paths to search |
| `fuzzy` | boolean | ❌ | false | Whether to use fuzzy matching |

### Returns

```typescript
{
  [project_path: string]: Array<{
    name: string;
    type: string;
    file: string;
    line: number;
    column: number;
    import_paths: string[];
  }>
}
```

### Examples

```python
# Search across multiple projects
results = find_symbol_multi(
    name="BaseModel",
    project_paths=[".", "../lib", "~/repos/shared"]
)
# Returns: {
#   ".": [{"name": "BaseModel", "file": "models/base.py", ...}],
#   "../lib": [{"name": "BaseModel", "file": "core/base.py", ...}],
#   "~/repos/shared": []
# }

# Fuzzy search across projects
results = find_symbol_multi(
    name="UsrMdl",
    project_paths=[".", "../services"],
    fuzzy=True
)
```

### Error Conditions

- Non-existent paths return empty results
- Each project searched independently
- Errors in one project don't affect others

### Performance Notes

- Searches projects in parallel
- Each project uses its own cache
- Can be slow for many large projects

---

## configure_namespace_package

Configure a namespace package spread across multiple repositories.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `namespace` | string | ✅ | - | Package namespace (e.g., "mycompany.services") |
| `repo_paths` | array[string] | ✅ | - | List of repository paths containing parts of this namespace |

### Returns

```typescript
{
  namespace: string;
  repo_paths: string[];
  discovered_structure: {
    [repo_path: string]: {
      packages: string[];     // Packages found in this repo
      modules: string[];       // Modules found
      init_files: string[];    // __init__.py files
    }
  };
  total_packages: number;
  total_modules: number;
}
```

### Examples

```python
# Configure distributed namespace
config = configure_namespace_package(
    namespace="mycompany",
    repo_paths=[
        "~/repos/mycompany-auth",
        "~/repos/mycompany-api",
        "~/repos/mycompany-utils"
    ]
)
# Returns: {
#   "namespace": "mycompany",
#   "repo_paths": [...],
#   "discovered_structure": {
#     "~/repos/mycompany-auth": {
#       "packages": ["mycompany.auth", "mycompany.auth.models"],
#       "modules": ["login.py", "logout.py"],
#       "init_files": ["mycompany/__init__.py", "mycompany/auth/__init__.py"]
#     },
#     ...
#   },
#   "total_packages": 8,
#   "total_modules": 25
# }
```

### Error Conditions

- Invalid repo paths are skipped
- Namespace must be valid Python package name
- Warns if namespace not found in repos

### Performance Notes

- Scans repos on configuration
- Creates file watchers for each repo
- Namespace resolution cached

---

## find_in_namespace

Find a module/class within a namespace package spread across repos.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `import_path` | string | ✅ | - | Full import path (e.g., "mycompany.auth.models.User") |
| `namespace_repos` | array[string] | ✅ | - | Repository paths to search |

### Returns

```typescript
Array<{
  repo_path: string;      // Repository containing the import
  file_path: string;      // Full file path
  line: number;          // Line number if specific symbol
  type: string;          // "module", "class", "function", etc.
  exists: boolean;       // Whether the import exists
}>
```

### Examples

```python
# Find class in distributed namespace
locations = find_in_namespace(
    import_path="mycompany.auth.models.User",
    namespace_repos=["~/repos/mycompany-auth", "~/repos/mycompany-core"]
)
# Returns: [
#   {
#     "repo_path": "~/repos/mycompany-auth",
#     "file_path": "~/repos/mycompany-auth/mycompany/auth/models.py",
#     "line": 25,
#     "type": "class",
#     "exists": true
#   }
# ]

# Find module
locations = find_in_namespace(
    import_path="mycompany.utils.helpers",
    namespace_repos=["~/repos/mycompany-utils"]
)
```

### Error Conditions

- Returns empty array if not found
- Invalid import paths return empty results
- Handles both modules and symbols

### Performance Notes

- Searches repos in order provided
- Stops at first match by default
- Uses cached namespace structure

---

## list_project_structure

List the Python project structure.

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_path` | string | ❌ | "." | Root path of the project |
| `max_depth` | number | ❌ | 3 | Maximum directory depth to traverse |

### Returns

```typescript
{
  root: string;           // Project root path
  structure: {
    name: string;        // Directory/file name
    type: "dir" | "file";
    path: string;        // Relative path from root
    children?: [];       // Subdirectories and files (if directory)
    size?: number;       // File size in bytes (if file)
    is_package?: boolean; // Has __init__.py (if directory)
    module_name?: string; // Python module name (if file)
  };
  statistics: {
    total_dirs: number;
    total_files: number;
    total_python_files: number;
    total_packages: number;
    total_size_bytes: number;
  };
}
```

### Examples

```python
# List project structure
structure = list_project_structure(project_path=".", max_depth=2)
# Returns: {
#   "root": "/project",
#   "structure": {
#     "name": "project",
#     "type": "dir",
#     "path": ".",
#     "is_package": false,
#     "children": [
#       {
#         "name": "src",
#         "type": "dir",
#         "path": "src",
#         "is_package": true,
#         "children": [
#           {"name": "__init__.py", "type": "file", "path": "src/__init__.py", "size": 0},
#           {"name": "main.py", "type": "file", "path": "src/main.py", "size": 1234}
#         ]
#       },
#       {"name": "tests", "type": "dir", "path": "tests", "is_package": true}
#     ]
#   },
#   "statistics": {
#     "total_dirs": 5,
#     "total_files": 20,
#     "total_python_files": 15,
#     "total_packages": 3,
#     "total_size_bytes": 50000
#   }
# }

# Shallow listing
structure = list_project_structure(max_depth=1)
```

### Error Conditions

- Returns empty structure for non-existent path
- Skips inaccessible directories
- Ignores common non-source directories (.git, **pycache**, etc.)

### Performance Notes

- Can be slow for large projects with deep nesting
- Respects .gitignore patterns
- Results not cached (filesystem state)

---

## Related Tools

- **Module Analysis**: For detailed module information, see [Module Analysis Tools](./module-analysis.md)
- **Framework Tools**: For framework-specific navigation, see:
  - [Pydantic Tools](./pydantic-tools.md)
  - [Flask Tools](./flask-tools.md)
  - [Django Tools](./django-tools.md)

## Common Patterns

### Symbol Discovery Flow

```python
# 1. Find symbol
symbols = find_symbol("MyClass")

# 2. Get type information
if symbols:
    type_info = get_type_info(
        file=symbols[0]["file"],
        line=symbols[0]["line"],
        column=symbols[0]["column"]
    )

# 3. Find references
    refs = find_references(
        file=symbols[0]["file"],
        line=symbols[0]["line"],
        column=symbols[0]["column"]
    )

# 4. Analyze call hierarchy if function
    if symbols[0]["type"] == "function":
        hierarchy = get_call_hierarchy(symbols[0]["name"])
```

### Multi-Project Analysis

```python
# 1. Configure packages
configure_packages(
    packages=["../lib", "../shared"],
    namespaces={"company": ["~/repos/company-*"]}
)

# 2. Search across all
results = find_symbol_multi(
    "BaseClass",
    project_paths=[".", "../lib", "../shared"]
)

# 3. Analyze dependencies
for path, symbols in results.items():
    if symbols:
        imports = find_imports(f"{path}.{symbols[0]['name']}")
```
