# Code Understanding Workflow

Tool mechanics (call signatures, return shapes, handles, edges) live in the
python-explore skill (`skills/python-explore/SKILL.md`). This workflow only sequences
the primitives; it does not restate them.

## Goal

Quickly understand unfamiliar code by exploring its structure, purpose, and
relationships. This workflow guides you from "What is this?" to "How does this work?"
using pyeye's progressive-disclosure primitives.

## When to Use This Workflow

- "What does this class/function do?"
- "How does this codebase work?"
- "I'm new to this project, where do I start?"
- "Explain how this module fits into the system"

## Steps

### Step 1: Orient on the symbol

`resolve` the name (or `resolve_at` a `file:line`) to a canonical handle. If `resolve`
reports the name is ambiguous, pick the intended candidate or re-resolve with the full
dotted handle. The handle is what every later step consumes.

### Step 2: Inspect what it is

`inspect` the handle for kind, signature, docstring, and `edge_counts`. This answers
"what is this and what does it claim to do?" Read the docstring, note base classes for
a class, and use `edge_counts` to decide which edges are worth drilling. When you want
the actual source, `Read` the `file:line` the handle points at.

### Step 3: Map structure

- For a module or class, `outline` the handle for its skeleton (members, nested defs)
  in one call.
- For inheritance, `expand` the `subclasses` edge (classes that extend it) and the
  `superclasses` edge (its bases).
- For any container, `expand` the `members` edge; for a nested symbol, `expand`
  `enclosing_scope` to find the scope around it.

### Step 4: Follow the forward flow (for functions)

`expand` the `callees` edge to see what a function calls. To follow the call structure
across several hops, `trace` from the handle following `callees`.

> **Honest limit — reverse references are not available.** "Who calls this?" and "what
> references this?" cannot be answered reliably yet; those edges are deferred to the
> Pyright backend ([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). Do not
> substitute `grep` or legacy reference tools — they under-report. Say so plainly, then
> offer what pyeye *can* answer: `callees` (forward), `imported_by`/`imports` (around a
> module), and `subclasses`/`superclasses` (inheritance).

### Step 5: Understand module context (for modules)

`outline` the module for its top-level structure, then `expand` the `imports` edge to
see its dependencies and the `imported_by` edge to see which project modules depend on
it. For a wider dependency picture, use `analyze_dependencies`.

## Progressive Understanding Levels

- **Level 1 — Basic (Steps 1-2):** what is it, where is it defined, what should it do.
- **Level 2 — Structure (Steps 3-4):** how it relates to other code and what it calls.
- **Level 3 — Integration (Step 5):** how it fits into the module and dependency graph.

## Common Understanding Patterns

- **Top-down (architecture first):** `outline` a module, identify key symbols, then
  `inspect` each.
- **Bottom-up (symbol first):** `resolve` a symbol, `inspect` it, then `expand` outward
  to context.
- **Flow-based (execution path):** start at an entry point, `expand`/`trace` `callees`
  to follow the forward path.

## Limitations and Considerations

- Reverse references (callers/references) are deferred (#333) — caller impact cannot be
  statically confirmed; state this on any change that touches shared code.
- Dynamic code (`eval`, `exec`) and some decorator behaviour won't be fully captured.
- Tests are excellent usage examples; check them when you need real-world patterns.

## Success Indicators

- Can explain what it does and where it is defined.
- Understand its inheritance and forward call structure.
- Know its module dependencies and importers.
- Confident enough to make changes (acknowledging unverified caller impact, #333).

## Related Workflows

- [Refactoring](workflows://refactoring) - Apply understanding to safe changes
- [Dependency Analysis](workflows://dependency-analysis) - Deep dive into module relationships

## Related Tools

- `resolve` / `resolve_at` - Name or position to a canonical handle
- `inspect` - What a symbol is (kind, signature, docstring, edge counts)
- `outline` - Module or class skeleton in one call
- `expand` - Walk one edge (members, callees, imported_by, subclasses, superclasses,
  imports, enclosing_scope)
- `trace` - Walk edges across multiple hops
- `analyze_dependencies` - Module dependency relationships
