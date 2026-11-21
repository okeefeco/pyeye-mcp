---
date: "2026-11-22"
title: "An @overload'ed function anchors on its implementation, not its first overload stub (#1088)"
issues: [1088, 857, 1082, 1022]
anchors: ["pyeye.resolver._anchor_on_bindings", "pyeye.resolver._overload_implementation", "tests/test_overload_anchor.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — An @overload'ed function anchors on its implementation, not its first overload stub (#1088)

**Friction:** verifying #1082 on Scrapy, `inspect("scrapy.utils.spider.iterate_spider_output")` anchored on the first of three `@overload` stubs. Its location, its signature and `deprecation: []` all described that stub, although the implementation warns. Reproduced in a fixture, it also hit `resolve`, `resolve_at` on any of the definitions (the implementation's included), overloaded methods, and `expand(f, "callees")`. That last one gave `[]` with no unresolved call sites, a false measured-empty read from the stub's `...` body. The cause was #857's `_anchor_on_bindings`. It has no decision entry of its own, only its docstring: "everything else keeps the first binding, as before", listing overloads with a property's setter and an `if`/`else` `def`. #857 kept that older answer for them on purpose, without fixing it.

**Decision:** approved by coordinator-3 (2026-11-22) as a fix to a wrong answer, with no new response shape.

- **The rule** (`_overload_implementation`, the first rule after a single binding): when every same-named binding is a `def` and all but one carry `@overload`, that one is the anchor. That's `typing.overload` or `typing_extensions.overload`, recognised through the module's import table, so `from typing import overload`, `@typing.overload` and `import typing_extensions as te` all work. It is the implementation: it runs and has the body, so the location and every edge read from the body describe the real function.
- **Unchanged:**
  - overload-only definitions (a `.pyi`, a Protocol, a stub) keep the first overload, since there's no body to prefer;
  - a property's setter keeps the getter;
  - an `if`/`else` pair keeps the first;
  - the rest of #857's rules, and #1022's ambiguity for function-local twins.
- **Every tool at once:** `resolve`, `resolve_at` (any of the definitions gives the same handle and the implementation's location), `inspect` (location, `deprecation`) and body-read edges (`callees`) all follow the one anchor.
- **Still open, with designer** (#1088's design questions), so not changed here:
  - `inspect`'s `signature` / `parameters` / `return_type` for an overloaded function still come from Jedi's signatures, which list the overloads. The question is whether to report the implementation's signature, with the overloads in a new field.
  - Deprecation evidence for overload-only definitions and for `@deprecated` on a single overload.

**Anchor:** `pyeye.resolver._anchor_on_bindings` / `_overload_implementation`; `tests/test_overload_anchor.py`; #1088.

**Applies-to:**

- `pyeye.resolver._anchor_on_bindings` and `pyeye.resolver._overload_implementation`, and through them every caller that anchors a placed definition (`resolve`, `resolve_at`, `inspect`, the body-read edges such as `callees`).

**Verify:** gold — `uv run pytest tests/test_overload_anchor.py` passes. It checks:

- **the anchor is the implementation:** `resolve`; `resolve_at` on each of the four definitions gives the same handle and the implementation's line; `inspect`'s location and `deprecation`; `callees` from the implementation's body; `typing.overload` and `typing_extensions` spellings; overloaded methods;
- **the first overload is kept** for overload-only definitions (a Protocol, a `.pyi`);
- **unchanged:** a property keeps its getter, and an `if`/`else` pair keeps the first.
