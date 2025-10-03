# PyEye Server Demo

## What This Server Does

The PyEye server provides semantic analysis of Python code, allowing Claude Code to understand your codebase deeply without reading every file.

## Demo: Analyzing examples/test_project/example.py

### 1. Finding Symbols

**Question**: "Where is the Calculator class defined?"

- The server can instantly locate `Calculator` at line 7 in `examples/test_project/example.py`
- It knows it's a class with methods: `__init__`, `add`, `multiply`, `divide`, `get_history`

### 2. Type Information

**Question**: "What type does Calculator.add return?"

- Returns `float` (rounded to precision)
- Takes parameters `a: float, b: float`
- Has full docstring available

### 3. Finding References

**Question**: "Where is the calculate_area function used?"

- Used in the `__main__` block at lines 115-119
- Called with different shapes: "circle" and "rectangle"

### 4. Call Hierarchy

**Question**: "What functions does the main block call?"

- `Calculator()` constructor
- `calc.add()`, `calc.multiply()`, `calc.divide()`
- `calculate_area()` with different parameters
- `calc.get_history()`

### 5. Project Structure

The server can show the entire Python project structure:

```text
pyeye-mcp/
├── src/pyeye/
│   ├── server.py (main server)
│   ├── analyzers/
│   │   └── jedi_analyzer.py
│   └── plugins/
│       ├── base.py
│       └── django.py
├── examples/test_project/
│   └── example.py
└── tests/
```

## Benefits Over Direct File Reading

1. **Context Efficiency**: Instead of reading entire files, Claude gets precise locations
2. **Semantic Understanding**: Knows relationships between code elements
3. **Framework Awareness**: Django plugin can find models, views, templates
4. **Speed**: Cached analysis, instant results
5. **Scalability**: Works on large codebases without overwhelming context

## Real-World Use Cases

1. **Code Navigation**: "Show me all places where User.save() is called"
2. **Refactoring**: "Find all functions that take a 'request' parameter"
3. **Understanding**: "What's the inheritance hierarchy of this class?"
4. **Framework Tasks**: "List all Django models and their fields"
5. **Dead Code**: "Find unused imports in this project"

## How to Use in Claude Code

Simply ask natural language questions about your Python code:

- "Find the definition of process_data"
- "Show me all uses of the Calculator class"
- "What type does this function return?"
- "List all Django views in this project"

The MCP server handles the analysis behind the scenes, giving Claude Code deep understanding of your Python codebase without consuming your context window with file contents!
