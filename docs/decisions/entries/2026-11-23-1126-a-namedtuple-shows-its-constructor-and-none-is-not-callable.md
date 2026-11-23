---
date: "2026-11-23"
title: "A typed NamedTuple shows its generated constructor, and None isn't callable (#1126)"
issues: [1126, 1129, 437, 407]
anchors: ["pyeye._class_signatures.namedtuple_signature", "pyeye._class_signatures.is_none_signature", "pyeye._class_signatures.is_namedtuple_factory", "pyeye.mcp.operations.inspect._build_signature", "tests/test_namedtuple_signatures.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-23-1129-a-typeddict-shows-its-keyword-only-constructor.md"]
superseded_by: []
---

## 2026-11-23 — A typed NamedTuple shows its generated constructor, and None isn't callable (#1126)

**Friction:** a skills audit found a fresh agent misled by Poetry's `Hexdigest(NamedTuple)`. Its class signature was `typing.NamedTuple`'s functional form, `(typename, fields, /)`, and each field carried `"signature": "NoneType()"`. Measuring showed the second problem isn't NamedTuple-specific. Jedi renders the `None` instance as a callable, so anything that can be `None` (`x: int | None`, `Optional[X]`, `= None`, in any class or at module level) got `NoneType()`.

**Decision** (coordinator-approved, 2026-11-23):

- **None isn't callable.** `_build_signature` drops a signature whose full name is `builtins.NoneType`. The rule is not "attributes get no signature": a variable that aliases a real callable (`alias = f`, `kls = SomeClass`) keeps its signature, because it is one.
- **A typed NamedTuple shows its generated constructor.** When Jedi's signature is `typing.NamedTuple`'s functional form (its parameters `typename, fields` come from `typing`), the signature is rendered from the class's annotated fields, in order, with their defaults: `WithDefaults(name: str, size: int=0, tag: Optional[str]=None)`. The style is Jedi's, the same as a dataclass's. Annotations are shown as written.
- **Limit: a subclass of a NamedTuple class shows no signature.** Its fields are inherited, not in its body, and the AST alone can't reach them. Under absence-vs-zero, absent is honest; the factory's signature is never shown. Walking the inherited fields would lift this if it's ever needed.
- **TypedDict is out of scope.** It shows `Movie()`, which is also wrong, but totality, `Required`/`NotRequired` and inherited keys need a ruling first: #1129. `@dataclass` was measured and is already right.

**Anchor:** `pyeye._class_signatures.namedtuple_signature`, `is_none_signature`, `is_namedtuple_factory`; `pyeye.mcp.operations.inspect._build_signature`; #1126.

**Applies-to:**

- `pyeye.mcp.operations.inspect._build_signature`, and through it every response that carries a `signature`: the stubs (`pyeye.mcp.operations.stubs`, used by `outline`, `expand` and `trace`) and `inspect`'s class and function fields;
- `pyeye._class_signatures`.

**Verify:** gold. `uv run pytest tests/test_namedtuple_signatures.py` passes. It covers:

- the class-form NamedTuple variants (`NamedTuple`, `typing.NamedTuple`, an aliased module, with and without defaults, and empty) in `outline` and `inspect`;
- a NamedTuple subclass with no signature, and no class showing `typename`;
- the dataclass and NamedTuple methods unchanged;
- no `NoneType()` on `X | None`, `Optional[X]` or `= None` fields and variables;
- aliases of a function and a class keeping their signatures.
