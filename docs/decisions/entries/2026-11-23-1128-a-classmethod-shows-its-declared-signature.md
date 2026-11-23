---
date: "2026-11-23"
title: "A classmethod shows its declared signature, cls included; a property stays unsigned (#1128)"
issues: [1128, 1125, 1106, 437]
anchors: ["pyeye.mcp.operations.inspect._build_signature", "pyeye.mcp.operations.inspect._infers_as_classmethod", "pyeye.mcp.operations.inspect._signature_from_source_ast", "tests/test_classmethod_signature.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A classmethod shows its declared signature, cls included; a property stays unsigned (#1128)

**Friction:** found while fixing #1125: `inspect` and `outline` gave a `@classmethod` no `signature` at all, while a staticmethod and a plain method in the same class had one. Jedi infers the classmethod's `def` as an instance of `builtins.classmethod` (the descriptor). typeshed's `classmethod` has no call signature, so `get_signatures()` is `[]` and `_build_signature` returned `None`. Jedi never renders a classmethod on any pyeye path, so there is no Jedi rendering to keep.

**Decision:** assigned by coordinator-3 (2026-11-23), plan approved on the issue.

- **The rule:** when `get_signatures()` is empty and Jedi infers the name as `builtins.classmethod` (`_infers_as_classmethod`), the signature is the `def` as written, rendered from the AST (`_signature_from_source_ast`, #437's fallback). Without source (a C extension), it is omitted, never `""`.
- **`cls` is shown**, as `self` is for a plain method: the signature is the declaration, matching #1125's rule that a shown signature names the declared parameters.
- **Formatting:** `ast.unparse` renders defaults without spaces (`a: int=1`), as Jedi does for a plain method, so a classmethod reads like its siblings.
- **Deliberate difference:** `@property` infers `builtins.property` and stays unsigned. A property is read, not called; its type is its `return_type`. Only `builtins.classmethod` is matched.
- **Order** in `_build_signature`, after #1125's entry: #1106's `TYPE_CHECKING` branch, then this one (both apply only when Jedi gives no signatures), then #999's filter, #437's wrapper-name check and #1125's declared-names rule. #1088's overloaded-function signature is applied after `_build_signature` and is unaffected.

**Anchor:** `pyeye.mcp.operations.inspect._build_signature` / `_infers_as_classmethod`; `tests/test_classmethod_signature.py`; #1128.

**Applies-to:**

- `pyeye.mcp.operations.inspect._build_signature` and `pyeye.mcp.operations.inspect._infers_as_classmethod`, and through them every `signature` pyeye shows for a classmethod: `inspect`, and `outline` nodes, which use the same builder.

**Verify:** gold — `uv run pytest tests/test_classmethod_signature.py` passes. It checks:

- **a classmethod has its declared signature**, `cls` included, in `inspect` and `outline`: with defaults, with no parameters but `cls`, and an abstract one with positional-only and keyword-only parameters;
- **unchanged:** a staticmethod and a plain method keep Jedi's rendering; a property has no signature;
- **the branch:** a classmethod with no source is omitted; a non-classmethod with no signatures is still omitted.
