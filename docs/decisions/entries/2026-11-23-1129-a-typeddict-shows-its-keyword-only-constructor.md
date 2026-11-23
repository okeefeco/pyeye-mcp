---
date: "2026-11-23"
title: "A TypedDict shows its keyword-only constructor, or no signature when a base doesn't resolve (#1129)"
issues: [1129, 1126]
anchors: ["pyeye._class_signatures.typeddict_class", "pyeye._class_signatures.typeddict_signature", "pyeye.mcp.operations.inspect._build_signature", "tests/test_typeddict_signatures.py"]
status: "active"
amends: ["2026-11-23-1126-a-namedtuple-shows-its-constructor-and-none-is-not-callable.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A TypedDict shows its keyword-only constructor, or no signature when a base doesn't resolve (#1129)

**Friction:** #1126 left TypedDict out of scope. Jedi gives a TypedDict class `dict`'s overloads, renamed, so its first signature, `Movie()`, says it takes no arguments. It is built `Movie(title="x", year=None)`.
**Decision** (maintainer ruling, 2026-11-23):

- A TypedDict class (Jedi's `is_typeddict()` on the single class it infers to) renders `Movie(*, title: str, year: int=...)`: keyword-only parameters, with an optional key (`total=False`, `NotRequired`) marked `...` because it has no real default.
- `Required` / `NotRequired` override the class's totality per key, and `ReadOnly` is stripped, as is every key qualifier, by name or attribute (`typing.Required`).
- Inherited keys come first, from each base in declaration order, depth first. They are included only when every base infers to exactly one TypedDict class, or to the `TypedDict` root, and every class's `total=` is a literal bool. Otherwise the class has no signature, never a partial one. Bases are walked through Jedi's own inference, so this amends #1126's limit for TypedDict only (a NamedTuple subclass still shows none).
- The functional form `TypedDict("M", {...})` is a variable, which Jedi gives no signature, so nothing changes there.
- The style is `ast.unparse`'s, `n: int=...`, the same as #1126's `size: int=0`; the ruling's `= ...` spacing is schematic.
**Anchor:** `pyeye._class_signatures.typeddict_class`, `pyeye._class_signatures.typeddict_signature`, `pyeye.mcp.operations.inspect._build_signature`; #1129, #1126.
**Applies-to:** `pyeye.mcp.operations.inspect._build_signature`, and through it every response that carries a `signature`: the stubs (`pyeye.mcp.operations.stubs`, used by `outline`, `expand` and `trace`) and `inspect`'s class field.
**Verify:** gold. `uv run pytest tests/test_typeddict_signatures.py` passes. In `outline` and `inspect` it covers total and `total=False` classes, `Required`/`NotRequired`/`ReadOnly` (bare and `typing.`), a dotted `typing.TypedDict` base, an empty TypedDict (`Empty()`), single, partial-total and cross-file multiple inheritance, an ambiguous base (no signature), the functional form (none), no `dict` overload anywhere, and a plain class unchanged.
