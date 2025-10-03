<!--
Audience: Claude Code
Purpose: Define how to use TodoWrite tool for task tracking
When to update: When task management patterns change
-->

# Task Management with TodoWrite Tool

## Core Principle

Use the **TodoWrite tool** for all task tracking - it persists across context resets without creating commits.

## Best Practices

- **Break tasks into small chunks** - 5-10 minute increments
- **Include file:line references** - e.g., "Fix validation in server.py:125-150"
- **Mark complete immediately** - Update status as you finish each task
- **Keep ONE task in_progress** - Focus on single task at a time
- **Never track in files** - Use TodoWrite tool, not CLAUDE.md or other files

## Task States

1. **pending**: Task not yet started
2. **in_progress**: Currently working on (limit to ONE task at a time)
3. **completed**: Task finished successfully

## Task Description Forms

**IMPORTANT**: Task descriptions must have two forms:

- **content**: The imperative form describing what needs to be done (e.g., "Run tests", "Build the project")
- **activeForm**: The present continuous form shown during execution (e.g., "Running tests", "Building the project")

## When to Use TodoWrite

Use this tool proactively in these scenarios:

1. **Complex multi-step tasks** - When a task requires 3 or more distinct steps
2. **Non-trivial and complex tasks** - Tasks that require careful planning
3. **User explicitly requests todo list** - When the user directly asks
4. **User provides multiple tasks** - When users provide a list of things
5. **After receiving new instructions** - Immediately capture user requirements
6. **When starting work on a task** - Mark as in_progress BEFORE beginning
7. **After completing a task** - Mark as completed and add follow-up tasks

## When NOT to Use TodoWrite

Skip using this tool when:

1. There is only a single, straightforward task
2. The task is trivial and tracking provides no benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Task Management Workflow

```python
# 1. Create initial todo list
todos = [
    {"content": "Analyze requirements", "status": "pending", "activeForm": "Analyzing requirements"},
    {"content": "Write tests", "status": "pending", "activeForm": "Writing tests"},
    {"content": "Implement feature", "status": "pending", "activeForm": "Implementing feature"}
]

# 2. Mark task as in_progress when starting
todos[0]["status"] = "in_progress"

# 3. Mark as completed immediately when done
todos[0]["status"] = "completed"
todos[1]["status"] = "in_progress"

# 4. Update list as you discover new tasks
todos.append({"content": "Fix edge case", "status": "pending", "activeForm": "Fixing edge case"})
```

## Task Completion Requirements

### ONLY mark a task as completed when FULLY accomplished

Never mark as completed if:

- Tests are failing
- Implementation is partial
- You encountered unresolved errors
- You couldn't find necessary files

When blocked:

- Keep task as in_progress
- Create new task describing what needs resolution
- Ask user for guidance

## File Reference Pattern

Always use `file_path:line_number` format for easy navigation:

- `src/server.py:125` - Specific line reference
- `tests/test_validation.py:45-89` - Range reference
- `src/plugins/flask.py:find_routes` - Function reference

## Example Session Flow

```markdown
User: "Add validation for user input and ensure it handles edge cases"

Claude: I'll track this implementation with TodoWrite:
1. Research existing validation patterns
2. Write validation tests including edge cases
3. Implement validation logic
4. Run tests and fix any issues

[Marks item 1 as in_progress]
Let me search for existing validation patterns...
[Completes research, marks item 1 as completed, item 2 as in_progress]
Now writing tests for the validation...
```

## Recovery from Context Loss

If context is lost:

1. TodoWrite preserves your task list
2. Check current in_progress task
3. Resume from where you stopped
4. No commits needed - list persists independently
