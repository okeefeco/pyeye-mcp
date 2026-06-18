# Safe Refactoring Workflow

## Goal

Refactor a class, function, or module by understanding the impact of a change
*before* making it. Honest scope first: pyeye can confirm **inheritance impact**,
**module-level dependents**, and the **dependency closure** statically. It **cannot**
yet confirm **caller/reference impact** — that is deferred to the Pyright backend
([#333](https://github.com/okeefeco/pyeye-mcp/issues/333)). Any refactor that touches
shared code must say so plainly.

Tool mechanics (call shapes, return shapes, handles, edge semantics) live in
`skills/python-explore/SKILL.md` — this file references tools by name only.

## When to Use This Workflow

- "I want to rename this class safely"
- "Can I change this function's signature?"
- "What will break if I modify this?"
- "Help me refactor this module"

## The Honest-Impact Boundary

| Question | Tool | Reliable? |
|----------|------|-----------|
| What subclasses depend on this class? | `expand(edge="subclasses")` | Yes |
| What base classes does it inherit from? | `expand(edge="superclasses")` | Yes |
| Which modules import this module? | `expand(edge="imported_by")` | Yes (module-level) |
| What is the dependency closure? | `analyze_dependencies` / `trace(follow=["imports"])` | Yes |
| What is the current signature/structure? | `inspect` | Yes |
| **Who calls / references this symbol?** | — | **No — deferred to #333** |

**The crux:** there is no reliable "who calls this?" answer yet. Do NOT fake one with
`grep` or the deprecated legacy reference tools — they under-report
non-deterministically (see SKILL.md → "Honest Limits"). State the gap instead.

## Steps

### Step 1: Establish the current shape

`inspect` the target symbol for its signature, docstring, and `edge_counts`. Record
the before-state so you can compare after the change. For a class or module, `outline`
gives the full skeleton in one call.

### Step 2: Inheritance impact (for classes)

`expand(edge="subclasses")` on the class to find project classes that extend it, and
`expand(edge="superclasses")` to see what it inherits. Subclasses inherit
methods/attributes — changing the base can break them.

### Step 3: Module dependents and dependency closure

If the change affects a module:

- `expand(edge="imported_by")` — which project modules import this one (module-level
  dependents that will at least need an import update).
- `analyze_dependencies` — imports, importers, and circular-dependency warnings.
- `trace(follow=["imports"])` — walk the import closure across multiple hops when the
  blast radius is wider than direct importers.

### Step 4: Assess impact honestly, then plan

Combine what you measured:

- **Inheritance impact** — subclass count (Step 2).
- **Module dependents** — importer count and dependency closure (Step 3).
- **Caller/reference impact** — **unverified.** pyeye cannot statically confirm which
  call sites or references touch this symbol (#333). Flag this explicitly in your plan
  whenever the symbol is shared.

Risk guidance:

- **Low** — no subclasses, few/no importers: proceed, but still note callers are
  unverified.
- **Medium** — some subclasses or several importers: update deliberately, lean on tests.
- **High** — deep hierarchy or wide import closure: consider a deprecation/compat shim,
  and rely on the test suite (not pyeye) to surface caller breakage.

Change order: base symbol → direct subclasses → dependent modules.

### Step 5: Make changes with validation

Tests are your caller-impact safety net, since pyeye can't be:

1. Make the change to the target symbol.
2. Run the test suite — this is the primary check that callers still work.
3. `inspect` the symbol again to confirm the new signature/structure.
4. Run the type checker (mypy/pyright) — it catches caller breakage pyeye cannot.

## Refactoring Patterns

- **Rename symbol** — update the definition; rely on tests + type checker to catch
  callers (not statically enumerable).
- **Change signature** — `inspect` before/after; deprecation shims ease migration since
  every call site cannot be confirmed in advance.
- **Move to another module** — `expand(edge="imported_by")` to find importers; add a
  compatibility import in the old location if the closure is wide.
- **Split a class** — `expand(edge="subclasses")` to decide the new hierarchy; migrate
  members, then validate with tests.

## Checklist

Before changing code:

- [ ] `inspect` (and `outline` for classes/modules) to capture the before-state
- [ ] `expand(edge="subclasses")` / `superclasses` for inheritance impact
- [ ] `expand(edge="imported_by")` and `analyze_dependencies` for module dependents
- [ ] Document impact — and explicitly flag that caller impact is unverified (#333)

After refactoring:

- [ ] Run the full test suite (primary caller-impact check)
- [ ] Run the type checker
- [ ] `inspect` to confirm the new shape

## Limitations

- **Caller/reference impact is not statically available** (deferred to #333). Tests and
  the type checker are the safety net.
- Dynamic imports (`importlib.import_module()`) and string-based references (config
  files, class names in strings) are invisible to static analysis — search manually.
- Monkey-patching and runtime modifications won't be detected.
- Always refactor under version control and run tests frequently.

## Related Workflows

- [Dependency Analysis](workflows://dependency-analysis) — deeper module-relationship analysis
- [Code Understanding](workflows://code-understanding) — orient in unfamiliar code first
