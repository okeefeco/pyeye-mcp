---
date: "2026-11-23"
title: "A Jedi signature is shown only when its parameter names are the declared ones (#1125)"
issues: [1125, 437, 999, 1088, 1128]
anchors: ["pyeye.mcp.operations.inspect._build_signature", "pyeye.mcp.operations.inspect._declared_parameter_names", "pyeye.mcp.operations.inspect._signature_from_source_ast", "tests/test_forwarding_signatures.py"]
status: "active"
amends: []
supersedes: []
amended_by: []
superseded_by: []
---

## 2026-11-23 — A Jedi signature is shown only when its parameter names are the declared ones (#1125)

**Friction:** explorer's skills audit found a fresh agent misled by Scrapy's `LxmlLinkExtractor._extract_links(self, *args, **kwargs)`. pyeye showed `(self, response_url, response_encoding, base_url, /, *, response_url, response_encoding, base_url)`: Jedi follows `*args`/`**kwargs` into the call they're forwarded to and renders the callee's parameters. That rendering was invalid Python (each name positional-only and keyword-only) and dropped `selector`. Reproduced, a partial forwarder (`def partial(self, a, *args, **kw)`) and a function forwarder got valid but invented signatures. `_build_signature` takes Jedi's `get_signatures()[0]`. Its only guard was #437's: a rendered name that isn't the symbol's (a decorator's wrapper) falls back to the AST. #437 has no decision entry of its own; its rule lives in `_build_signature`'s docstring, so this entry records both.

**Decision:** assigned by coordinator-3 (2026-11-23), which ruled it a contract rule for signatures.

- **The rule:** a signature pyeye shows must match the source. Jedi's rendering is kept only when its parameter names, in order, equal the names the `def` declares (positional-only, regular, `*args`, keyword-only, `**kwargs`; `_declared_parameter_names`). The one tolerance: Jedi drops a classmethod's implicit first parameter, so the declared names minus their first also pass. Otherwise the declared signature is rendered from the AST (`_signature_from_source_ast`, #437's fallback).
- **Never invalid:** a rendering with a duplicated parameter name is never shown. Without source to fall back to (a builtin, a C extension), the signature is omitted, never an invalid one.
- **Order:** #999's restricted-signature filter first; then #437's wrapper-name check; then this. #1088's overloaded-function signature (the implementation's) is applied after `_build_signature` and is unaffected.
- **Unchanged:** a plain `def` keeps Jedi's formatting (`a: int=1`), as do staticmethods. Most signatures don't move.
- **Not here:** forwarding knowledge as a separately labelled hint (the issue allows it, but nothing needs it yet). Also #1128: a `@classmethod` gets no signature at all, pre-existing and separate.

**Anchor:** `pyeye.mcp.operations.inspect._build_signature` / `_declared_parameter_names`; `tests/test_forwarding_signatures.py`; #1125.

**Applies-to:**

- `pyeye.mcp.operations.inspect._build_signature` and `pyeye.mcp.operations.inspect._declared_parameter_names`, and through them every `signature` pyeye shows: `inspect`, and `outline` nodes, which use the same builder.

**Verify:** gold — `uv run pytest tests/test_forwarding_signatures.py` passes. It checks:

- **forwarders show their declared signatures** in `inspect` and `outline`: a method forwarding to a method (the issue's invalid case), a partial forwarder, a function forwarder;
- **unchanged:** a plain function and a staticmethod keep Jedi's rendering, and the forwarded-to callee is unaffected;
- **the guard:** a duplicated name with no source is omitted; distinct names with no source are kept; Jedi dropping an implicit first parameter is kept.
