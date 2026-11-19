# Duplicate-code check

<!-- Audience: Both -->

`scripts/duplicate_code_report.py` reports blocks of near-identical logic in the
MCP operations (`src/pyeye/mcp/operations/`) and `src/pyeye/canonicalization.py`.
It was added under #616 as a first step toward #495, after the 2026-11-15
duplication audit found capabilities implemented two to five times, with fixes
reaching only one copy (#629).

## What it does

The detector lives in `pyeye.duplication` (#495). This script is the repository's
ratchet over it. The same core powers the user-facing `duplication-review`
skill (`python -m pyeye.duplication review`), which adds filters, families and
dismissals. The ratchet uses none of those: every exact-match clone counts.

- Each file is parsed and flattened into a stream of AST tokens: the node type,
  plus attribute names such as `.infer` or `.full_name`.
- Local variable names, literal values, docstrings, comments and imports are
  dropped. A copy whose variables were renamed still matches.
- Any run of at least <!-- fact:begin duplication.default.min_tokens -->`35`<!-- fact:end -->
  identical tokens (by default; `--min-tokens` changes it) that appears in two
  places is reported as a clone region, with both line ranges.
- A token window that appears more than
  <!-- fact:begin duplication.default.max_occurrences -->`50`<!-- fact:end --> times is paired with its next
  occurrence only (#495), so the pair loop stays linear on repeated data such as
  large literal tables. In #495, all-pairs on one emoji table in `rich` ran out of memory.
  Every copy is still reported, so a copy past the cap fails the ratchet like a
  2-way one.
- A target file that can't be parsed fails the ratchet (it would hide its
  copies). Directories are walked with `filtered_rglob` (#517, #810), like
  every project scan: virtual environments and nested checkouts are skipped.

```bash
uv run python scripts/duplicate_code_report.py                 # default targets
uv run python scripts/duplicate_code_report.py --min-tokens 25 # more, noisier
uv run python scripts/duplicate_code_report.py path/to/file.py other/dir
```

### Why not pylint `duplicate-code`

pylint's similarity checker compares normalised *lines*. On these files, at
introduction (2026-11-15, `d615b3a`), it found 1 block at a 4-line minimum and
none at 6, because the copies that
drifted (the Jedi synthetic-import inference in `inspect`, `resolve` and
`canonicalization`, for example) rename their locals. The AST check finds all
three of those copies and needs no new dependency.

## It is a blocking ratchet

It runs as the `duplicate-code-report` pre-commit hook (at commit time when a
target file changes, and in CI's pre-commit job) and as a pytest test
(`tests/test_duplicate_code_report.py::test_repo_matches_the_baseline_exactly`),
so CI enforces it whatever files a PR touches.

Since #636 it is a **blocking ratchet**, with the same rules as the #614/#615
fitness tests:

- Each clone is keyed by its **site**: the sorted pair of `file::qualname` for
  the innermost function or class around each region. Moving code up or down a
  file doesn't change it; line numbers are never part of the key.
- `BASELINE` in `scripts/duplicate_code_report.py` lists the known sites, each
  with the issue expected to remove it.
- A site that isn't in `BASELINE` **fails**: consolidate the copy rather than
  adding an entry.
- A baselined site that no longer occurs **also fails**, until its entry is
  deleted. The baseline only shrinks.

Modes:

```bash
uv run python scripts/duplicate_code_report.py                     # the ratchet (default, blocking)
uv run python scripts/duplicate_code_report.py --report-only       # print, always exit 0
uv run python scripts/duplicate_code_report.py --fail-on-findings  # exit 1 on ANY clone, baselined or not
```

## Baseline (#636, 2026-11-15)

By the time the check became blocking, #623 had removed four of the five
original regions. Two sites remained; #674 (#626) then removed the
`edges.resolve_imported_by` / `edges.superclass_bases` copy, and #714 the
`edges._class_members` / `edges._module_members` one (#686): `_class_members`
now dedupes on the emitted handle. That left the baseline empty; `BASELINE` in
the script is the current list.

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
Passing both files reports it (a 51-token clone region at introduction).

## Limits

- **It's crude.** It finds copied *code*, not copied *behaviour*. Two
  implementations of the same idea written differently aren't found. The #614
  cross-tool invariant tests cover that.
- Short copies under <!-- fact:begin duplication.default.min_tokens -->`35`<!-- fact:end -->
  tokens (a few lines) aren't reported by default.
  Lowering `--min-tokens` finds more of them, along with more incidental
  matches.
