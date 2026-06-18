# Find All References Workflow

## Goal

Answer "who references / who calls this symbol?" **honestly**.

The crux: pyeye **cannot give reliable reverse-reference data yet**. Caller and
reference edges are deferred to an indexed Pyright backend
([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). This workflow shows what to
say instead, and which forward relationships you *can* answer reliably.

Tool mechanics (signatures, return shapes, edge list) live in
`skills/python-explore/SKILL.md` — read its "⭐ Honest Limits" section first.

## When to Use This Workflow

- "Find all usages of this class/function"
- "Where is this symbol used?"
- "Who calls this?" / "What references this before I refactor?"
- "Which modules depend on this?"

## Steps

### Step 1: State the limit plainly

There is **no reliable way** to enumerate callers/references today. Do not fake it:

- Do **not** use `grep` to guess who uses a symbol — it under-reports and false-matches.
- Do **not** use the deprecated legacy reference tools — they are backed by exactly the
  non-deterministic reverse search the redesign rejected.

Tell the user directly, e.g.: "pyeye can't give reliable caller/reference data yet
(deferred to #333). A confident wrong answer is worse than an honest gap — here's what I
*can* show."

### Step 2: Offer the forward relationships you CAN answer

Reach for `expand(handle, edge=...)` (resolve the name to a handle first):

- **Who imports a module:** `expand(handle, edge="imported_by")` — static, reliable.
- **What a function calls:** `expand(handle, edge="callees")` — forward call targets.
- **Inheritance:** `expand(handle, edge="subclasses")` / `edge="superclasses"`.
- **Structure:** `expand(handle, edge="members")` for a class's/module's contents.

For module-level dependency direction, `analyze_dependencies` complements
`imported_by`.

### Step 3: Be explicit about what's unverified

When the task is a refactor, say so in your mental-model summary: caller impact
**cannot be statically confirmed** until the Pyright backend lands
([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). Read the relevant
`file:line` pointers and reason about impact manually rather than claiming completeness.

## Example: the honest refusal

> Reliable caller data isn't available yet — `callers` is deferred to the Pyright
> backend (#333), and faking it would under-report. What I *can* show: what this
> function itself calls (`expand` with `callees`), and which modules import its module
> (`expand` with `imported_by`). Want either of those?
