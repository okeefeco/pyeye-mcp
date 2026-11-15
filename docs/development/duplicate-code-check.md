# Duplicate-code check

<!-- Audience: Both -->

`scripts/duplicate_code_report.py` reports blocks of near-identical logic in the
MCP operations (`src/pyeye/mcp/operations/`) and `src/pyeye/canonicalization.py`.
It was added under #616 as a first step toward #495, after the 2026-11-15
duplication audit found capabilities implemented two to five times, with fixes
reaching only one copy (#629).

## What it does

- Each file is parsed and flattened into a stream of AST tokens: the node type,
  plus attribute names such as `.infer` or `.full_name`.
- Local variable names, literal values, docstrings, comments and imports are
  dropped. A copy whose variables were renamed still matches.
- Any run of at least 35 identical tokens that appears in two places is
  reported as a clone region, with both line ranges.

```bash
uv run python scripts/duplicate_code_report.py                 # default targets
uv run python scripts/duplicate_code_report.py --min-tokens 25 # more, noisier
uv run python scripts/duplicate_code_report.py path/to/file.py other/dir
```

### Why not pylint `duplicate-code`

pylint's similarity checker compares normalised *lines*. On these files it
found 1 block at a 4-line minimum and none at 6, because the copies that
drifted (the Jedi synthetic-import inference in `inspect`, `resolve` and
`canonicalization`, for example) rename their locals. The AST check finds all
three of those copies, needs no new dependency and runs in under a second.

## It is report-only

The check runs as the `duplicate-code-report` pre-commit hook. That means at
commit time, when a target file changes, and in CI's pre-commit job. It
**always exits 0**:

- Today's code has known duplicates. The #629 Phase 2 consolidation issues
  (#623–#627) will remove them. A blocking check would fail every PR until
  they land.
- The report is still printed (`verbose: true`), so new copies are visible in
  review.

`--fail-on-findings` makes the script exit 1 when it finds anything. Nothing
passes that flag today. Making the check blocking, or replacing it with a
baselined allow-list like the #614/#615 fitness tests, is a pending decision.

## Findings at introduction (2026-11-15, `main` @ `d615b3a`)

| Tokens | Region A | Region B | What it is |
|--------|----------|----------|------------|
| 54 | `resolve._resolve_external_dotted_name` | `canonicalization._resolve_via_external_inference` | Jedi synthetic-import inference (#623) |
| 39 | `inspect._find_jedi_name_for_handle` (synthetic-import fallback) | `resolve._resolve_external_dotted_name` | Same inference, third copy (#623) |
| 39 | `inspect._find_jedi_name_for_handle` (synthetic-import fallback) | `canonicalization._resolve_via_external_inference` | Same inference, third copy (#623) |
| 39 | `inspect._find_jedi_name_for_handle` (module-prefix walk) | `canonicalization.find_definition_name` | Handle→Jedi-name lookup (#623) |
| 37 | `edges._class_members` | `edges._module_members` | Same dedupe-and-append member loop |

The audit's other known copy, `typeref._attribute_target_position` against
`_ast_targets.attr_target_position`, sits outside the default targets.
Passing both files reports it (a 51-token clone region).

## Limits

- **It's crude.** It finds copied *code*, not copied *behaviour*. Two
  implementations of the same idea written differently aren't found. The #614
  cross-tool invariant tests cover that.
- Short copies under 35 tokens (a few lines) aren't reported by default.
  Lowering `--min-tokens` finds more of them, along with more incidental
  matches.
