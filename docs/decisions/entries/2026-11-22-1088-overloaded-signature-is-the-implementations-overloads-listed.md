---
date: "2026-11-22"
title: "An overloaded function's signature is its implementation's, with `overloads` listed; a deprecated overload is conditional (#1088)"
issues: [1088, 1082, 1089]
anchors: ["pyeye.overloads.overload_set", "pyeye.overloads.is_overload", "pyeye.deprecation.overload_evidence", "pyeye.mcp.operations.inspect._build_function_fields", "pyeye.mcp.operations.inspect._deprecation_evidence", "tests/test_overload_signatures.py"]
status: "active"
amends: ["2026-11-22-1082-inspect-reports-static-deprecation-evidence.md", "2026-11-22-1088-an-overloaded-function-anchors-on-its-implementation.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-22 — An overloaded function's signature is its implementation's, with `overloads` listed; a deprecated overload is conditional (#1088)

**Friction:** #1089 anchored an `@overload`'ed function on its implementation, so its location, `parameters`, `return_type`, `deprecation` and `callees` describe the function that runs. Two questions were left for a ruling.

- `signature` still came from Jedi's `get_signatures()[0]`, the first overload.
- `deprecation` had no rule for a `@deprecated` on one overload, or for an overload-only definition, whose body doesn't exist. The latter reported `[]`, implying a check that couldn't happen.

**Decision:** the maintainer's ruling via designer (2026-11-22), as relayed by coordinator-3.

- **Ruling 1, `inspect` only:**
  - `signature` / `parameters` / `return_type` come from the single non-`@overload` implementation.
  - A new field, `overloads`, lists the overloads' signatures in source order. Each is rendered from the AST as `name(args) -> ret`, the style `signature` already uses for decorated functions (#437).
  - Absence-vs-zero is exactly `deprecation`'s: `[]` when the definition was read and isn't overloaded, absent when it couldn't be read.
  - Overload-only (a `.pyi`, a Protocol): `signature` is the first overload's, and `overloads` lists them all.
  - **Not on outline nodes or `expand`/`trace` stubs:** widening `overloads` there needs a size measurement first (the maintainer's 5%/10% condition).
- **Ruling 2, `deprecation`, widening B.6 (amends #1082's entry):**
  - A `@deprecated` on an individual overload deprecates one call form, so it's `{"kind": "conditional", "via": "decorator", "line"}`. B.6 now allows a `conditional` entry via `decorator`, where it was always via `warn`.
  - With an implementation: its evidence (body warns and its own decorators, unchanged), plus a conditional decorator entry per deprecated overload, in line order.
  - Overload-only: never a checked `[]`. The overload-decorator evidence is reported when there is some; otherwise `deprecation` is ABSENT.
  - A `@deprecated` on every overload is reported overload by overload, as `conditional` entries, following the ruling literally.
- **One overload set** (`pyeye.overloads`): the same-named defs in the definition's own body, with `@overload` recognised through the import table (`typing` / `typing_extensions`). The resolver's #1089 rule (`_overload_implementation`) now uses its `is_overload`, so the two can't drift.
- **Linter:** B.6 widened as above; B.7 checks that `overloads` is only on function/method nodes and is a list (never null) of non-empty single-line strings.

**Anchor:** `pyeye.overloads`; `pyeye.deprecation.overload_evidence`; `pyeye.mcp.operations.inspect._build_function_fields` / `_deprecation_evidence`; `tests/test_overload_signatures.py`; #1088.

**Applies-to:**

- `pyeye.overloads.overload_set`, `pyeye.overloads.is_overload`, `pyeye.overloads.OVERLOAD_DECORATORS`;
- `pyeye.deprecation.overload_evidence`, `pyeye.deprecation.decorator_line`;
- `pyeye.mcp.operations.inspect._build_function_fields`, `pyeye.mcp.operations.inspect._overload_context`, `pyeye.mcp.operations.inspect._render_signature`, `pyeye.mcp.operations.inspect._deprecation_evidence`;
- `pyeye.resolver._overload_implementation` (now on `is_overload`);
- the linter's B.6 and B.7, the `inspect` tool docstring, and the `python-explore` skill's absence-vs-zero section.

**Verify:** gold — `uv run pytest tests/test_overload_signatures.py` passes. It checks:

- **with an implementation:** `signature` = the implementation's, and `parameters` / `return_type` follow; `overloads` lists all, in source order; a deprecated overload is conditional via decorator beside the body's conditional warn; a deprecated implementation is unconditional; an overloaded method;
- **overload-only:** the first overload's signature with all listed; `deprecation` absent without a deprecated overload; a deprecated overload still reported; a `.pyi`;
- **no overloads:** a plain function's `overloads` is `[]`; a class or module has no field;
- **B.6/B.7:** they accept a conditional decorator and a list of signatures; B.7 rejects null, a string, empty or multi-line entries, non-strings, and a class node.
