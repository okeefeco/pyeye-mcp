---
date: "2026-11-23"
title: "A signature Jedi renders across lines is re-rendered whole, never cut off (#1159)"
issues: [1159, 1125, 437, 407]
anchors: ["pyeye.mcp.operations.inspect._build_signature", "pyeye.mcp.operations.inspect._single_line_signature", "pyeye.mcp.operations.inspect._signature_from_source_ast", "tests/test_multiline_signatures.py"]
status: "active"
amends: ["2026-11-23-1125-a-rendered-signature-must-name-the-declared-parameters.md"]
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A signature Jedi renders across lines is re-rendered whole, never cut off (#1159)

**Friction:** Jedi's `Signature.to_string()` keeps the source text of each annotation, default and return type, newlines and comments included. `_build_signature` made it single-line by keeping the text before the first newline. A split annotation (Scrapy's `Request.__init__`, found by the #1140 verification run) cut the signature off mid-parameter, with no closing parenthesis and no later parameters or return type.

**Decision:**

- **A multi-line rendering is re-rendered, not truncated.** `_single_line_signature` parses it as `def <rendering>: ...` and rebuilds `name(args) -> ret` with `ast.unparse`, the style pyeye's own renderers use (`_signature_from_source_ast`, `_render_signature`, the NamedTuple and TypedDict constructors). The result is one line with balanced brackets.
- **Rejected: collapsing each newline and its indentation to a space** (the issue's first suggestion). Jedi keeps a comment inside a split annotation (`Mapping[str, Any]  # str keys`), which would swallow the rest of the line. A triple-quoted default's newlines are part of its value. `ast.unparse` drops the comment and renders the string exactly (`'a\n  b'`).
- **Never cut off:** a rendering that won't parse falls back to the declared signature (`_signature_from_source_ast`), and without source it is omitted, as #407 requires (present-with-value or absent).
- **Unchanged:** a single-line rendering is used as Jedi gave it, byte for byte. Only a rendering containing `\n` or `\r` is touched.
- **Order** in `_build_signature`, amending #1125's list: #1106's and #1128's branches (no signatures), #999's restricted filter with #1126's `None` drop, #1126's NamedTuple and #1129's TypedDict constructors, then **this step**, then #437's wrapper-name check and #1125's declared-names rule, which run on the re-rendered string and Jedi's `params`. #1088's overload signature is applied after `_build_signature`, from the AST, and is unaffected.

**Anchor:** `pyeye.mcp.operations.inspect._build_signature` / `_single_line_signature`; `tests/test_multiline_signatures.py`; #1159.

**Applies-to:**

- the one place a Jedi rendering becomes a `signature`: `pyeye.mcp.operations.inspect._build_signature`. Through it, `inspect`'s class and function fields and `pyeye.mcp.operations.stubs.build_stub` (every `outline` node and edge stub) all show the whole signature;
- the AST renderers that already give one line, unchanged: `_signature_from_source_ast`, `_render_signature` (#1088's overloads), `pyeye._class_signatures.namedtuple_signature` and `typeddict_signature`.

**Verify:** gold. `uv run pytest tests/test_multiline_signatures.py` passes. It checks that:

- a split annotation on a function, a method and a class's `__init__`, a split return type, a comment inside an annotation and a multi-line string default all show the whole single-line signature through `inspect` and through `outline` nodes (the stubs);
- every signature in that module's outline has no newline and balanced brackets;
- a single-line rendering keeps Jedi's formatting;
- an unparseable rendering falls back to the declared signature, or is omitted without source;
- a CRLF rendering is made whole.

`git grep -n 'split("\\n")\[0\]' src/pyeye` finds no signature truncation.
