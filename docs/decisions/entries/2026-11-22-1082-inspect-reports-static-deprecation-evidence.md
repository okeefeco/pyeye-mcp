---
date: "2026-11-22"
title: "inspect reports a symbol's deprecation as a list of static evidence; [] when checked and none (#1082)"
issues: [1082, 1083, 703, 933]
anchors: ["pyeye.deprecation.evidence", "pyeye.deprecation.DEPRECATION_DECORATORS", "pyeye.mcp.operations.inspect._deprecation_evidence", "pyeye.mcp.operations.inspect._is_deprecation_category", "pyeye._ast_targets.find_class_def_at_line", "tests/test_deprecation_evidence.py"]
status: "amended"
amends: []
supersedes: []
amended_by: ["2026-11-22-1088-overloaded-signature-is-the-implementations-overloads-listed.md"]
superseded_by: []
---

## 2026-11-22 — inspect reports a symbol's deprecation as a list of static evidence; [] when checked and none (#1082)

**Friction:** pyeye couldn't say "this is deprecated". The architecture-facts trial (RFC #1083) had to read the AST itself, and learned that a warning inside a branch usually deprecates an argument or path, not the function. Scrapy's `iterate_spider_output` warns only for coroutine input, and calling that "deprecated" mislabelled 3 real duplicates.

**Decision:** shape and scope proposed by worker-4 and approved by coordinator-3 (2026-11-21) under the maintainer's standing absence-vs-zero rule (`docs/api-redesign.md`; applied in #703: "measured and empty is present, absent only where not measured"). No new ruling was needed.

- **The shape:** `deprecation`, a list of `{kind, via, line}` on `inspect` nodes of kind `function`, `method` and `class`:
  - **`[]`:** the definition was read and nothing was found;
  - **ABSENT:** it couldn't be read (no file, a compiled object, an unparseable file, no `def`/`class` at its line) or the kind doesn't apply;
  - **"Deprecated"** means any entry with `kind: "unconditional"`.
  - A single object present only with evidence (the issue's first sketch) was rejected. Its absence would mean both "checked, nothing" and "couldn't check". That's unlike `stub: true` (#933), where stub-or-not is always known. It would also lose evidence when a symbol has a decorator and branch warnings.
  - The name is `deprecation`, not `deprecated`, so that `[]` doesn't read like a falsy boolean.
- **Evidence** (`pyeye.deprecation`), from the definition's own AST:
  - `unconditional` via `decorator`: a decorator whose qualified name, through the module's import table, is in `DEPRECATION_DECORATORS` (`warnings.deprecated`, `typing_extensions.deprecated`, and the `Deprecated` package's three).
  - `unconditional` via `warn`: `warnings.warn(message, <deprecation category>)` (positional or `category=`, under any import spelling) as a statement of the body (of `__init__`, for a class), or nested only in `with` blocks or a `try` body or `finally`.
  - `conditional` via `warn`: the same under `if`, a loop, `except`, a `try`'s `else` or `match`.
  - Nested `def`/`class` bodies belong to those definitions. Entries are in line order.
- **Categories** (`inspect._is_deprecation_category`):
  - a name ending in `DeprecationWarning`;
  - or a class that statically subclasses one, found through the one module mapper (`file_for_module`) and followed through `class` statements and module-level aliases (`RemovedInNextVersionWarning = RemovedInDjango70Warning`), up to 8 classes deep. This catches Django's `RemovedInDjango70Warning`.
  - An unresolvable category, a missing one (`UserWarning` by default) and `FutureWarning` don't count. `FutureWarning` is excluded because it also marks behaviour changes.
- **inspect only:** stubs (`expand`/`outline`/`trace`) would need each stub's definition parsed on wide queries. They can come later if a consumer needs them.
- **The ceiling,** stated in the tool docstring and `inspect`'s module docstring: static evidence only. A warn in a helper function (Django's own `warn_about_external_use`), a category built at runtime, an unrecognised decorator name and an early `return` before a warn aren't seen.
- **Linter:** B.6 checks `deprecation` only on function/method/class nodes, as a list (never null), with exact `{kind, via, line}` entries; `conditional` is always via `warn`.
- **On django** (`cd385e6b8c`): `BasePaginator.__init__` and `django.core.mail.__getattr__` warn with `RemovedInDjango70Warning` only on some inputs, and are reported as `conditional` at the warn's line. A typeshed `@deprecated` fixture (e.g. `datetime.datetime.utcnow`) wasn't cheap: members of compiled stdlib classes don't resolve, and `datetime.datetime` has no file, so its field is absent.

**Anchor:** `pyeye.deprecation`; `pyeye.mcp.operations.inspect._deprecation_evidence` / `_is_deprecation_category`; `tests/test_deprecation_evidence.py`; #1082.

**Applies-to:**

- `pyeye.deprecation.evidence`, `pyeye.deprecation.DEPRECATION_DECORATORS`, `pyeye.deprecation.dotted_name`, `pyeye.deprecation.qualify`;
- `pyeye.mcp.operations.inspect._deprecation_evidence`, `pyeye.mcp.operations.inspect._is_deprecation_category`, `pyeye.mcp.operations.inspect._top_level_class`, and the `inspect` node for functions, methods and classes;
- `pyeye._ast_targets.find_class_def_at_line`;
- the linter's B.6 (`tests/conformance/response_linter.py`), the `inspect` tool docstring and the `python-explore` skill's absence-vs-zero section.

**Verify:** gold — `uv run pytest tests/test_deprecation_evidence.py` passes. It checks:

- **unconditional:** a top-level warn; the decorator, including an aliased import; `warn` imported under another name with `category=`; a class whose `__init__` warns; a decorated class; a method; a `with` block;
- **conditional:** an `if`; an `__init__` branch; `except`;
- **multiple pieces of evidence**, kept in line order;
- **categories:** direct, chained and aliased subclass categories count; `UserWarning`, `FutureWarning`, no category and an unresolvable one don't;
- **absence:** `[]` for evidence-free definitions, including nested scopes' warns; absent for a module and a variable;
- **B.6:** accepts well-formed values and rejects null, a dict, bad kind/via/line, missing or extra keys, and a wrong kind.
