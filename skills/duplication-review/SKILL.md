---
name: duplication-review
description: Use when looking for copied code in a Python codebase — "find duplicated code", "where is this logic copied", "duplication review", "what should we consolidate", "has this copy drifted", "the AI wrote the same thing in several places". Runs pyeye's exact-match clone detector over a caller-supplied scope and returns ranked clone FAMILIES as pointers (file, line ranges, qualnames, token counts), each labelled as a JUDGMENT with its threshold and filters. Dismissals persist in a committed state file. Does NOT judge convention divergence (that is architecture-review), and does NOT find the same behaviour written differently.
---

# Duplication Review

Find **copied code** in a Python scope, ranked so the biggest copies come first,
and let a human decide which to consolidate. A copy whose versions have drifted
apart is the failure this exists to catch: a fix that reached one copy and not
the other.

## What This Is (and Is NOT) — Read First

- **Every result is a judgment, not a fact.** "These two regions are the same
  code" depends on a tunable threshold and filters. The tool states both with
  every run; say them when you report, and read both regions before you
  recommend anything.
- **Exact match after normalisation.** Local names, literal values, docstrings,
  comments and imports are ignored, so a copy with renamed variables still
  matches. Code that does the same thing written differently is **not** found,
  and neither is a near-copy with lines inserted (an `await` added to an async
  twin breaks the match).
- **Pointers only.** The output never contains source text: only file paths,
  line ranges, `file::qualname` locations and token counts. Read the regions
  yourself (targeted reads) when you need to judge one.
- **Expect boilerplate.** Measured on django and pydantic (#495), about two in
  three to three in four of the top families were real copies worth
  consolidating, and almost none were unrelated code. The rest are idioms the
  detector can't tell from copies: backend-specific variants of one method,
  registration lists, families of one-line wrappers. Dismiss those (below).
- **Not convention divergence.** "Your code does X seven different ways" is
  [`architecture-review`](../architecture-review/SKILL.md).

## Scope Is Required

Pass one or more files or directories. Never default to the whole repository,
and **exclude vendored or frozen code** (a bundled copy of another library, a
`v1/` compatibility package): it is copied on purpose and would fill the top of
the list. To exclude a directory, list its siblings instead of its parent.

## Running It

`python -m pyeye.duplication` is the interface. Where pyeye was installed as a
Claude Code plugin, run it through the plugin's environment:

```bash
UV_PROJECT_ENVIRONMENT="${CLAUDE_PLUGIN_DATA}/.venv" \
  uv run --project "${CLAUDE_PLUGIN_ROOT}" --no-sync --frozen \
  python -m pyeye.duplication review src/mypkg --state .pyeye/duplication-review.json
```

Otherwise, any environment with `pyeye-mcp` installed: `python -m pyeye.duplication review …`.
Run it from the project root: locations are relative to `--root` (default: the
current directory), and the state file's keys use them. A scope outside
`--root` is rejected. A file that can't be parsed or decoded is skipped and
listed as `unparseable`; its source is never printed. Bad arguments or a bad
state file exit 2 with a one-line message, before anything is scanned. `dismiss`
exits 1 when `--family` names no family in the scope, which is known only after
the scan.

Commands: <!-- fact:begin duplication.commands -->`review`, `dismiss`<!-- fact:end -->. Flags: <!-- fact:begin duplication.flags -->`--root`, `--min-tokens`, `--max-occurrences`, `--state`, `--today`, `--json`, `--family`, `--reason`, `--date`, `--review-after`<!-- fact:end -->.

`review <scope…>`:

| Flag | Default | Meaning |
|------|---------|---------|
| `--root` | `.` | Locations are reported relative to it. |
| `--min-tokens` | <!-- fact:begin duplication.default.min_tokens -->`35`<!-- fact:end --> | Minimum clone length in normalised AST tokens. `25` finds more, mostly noise. |
| `--max-occurrences` | <!-- fact:begin duplication.default.max_occurrences -->`50`<!-- fact:end --> | A token window seen more often than this is paired with its next occurrence only, so the run stays linear on repeated data tables (all-pairs ran a machine out of memory). Every copy is still reported. |
| `--state` | none | Dismissal state file. Suggested: `.pyeye/duplication-review.json`, committed. |
| `--today` | none | Today's ISO date. Needed for `--review-after` dismissals to come due; nothing reads a clock. |
| `--json` | off | Machine-readable output. |

`dismiss <scope…> --state FILE --family ID --reason R --date YYYY-MM-DD [--review-after YYYY-MM-DD]`
records a family as a confirmed non-issue. Use the same scope, `--root`,
`--min-tokens` and `--max-occurrences` as the review that showed the family.

- `--family` — the family id the review printed.
- `--date` — the dismissal date, ISO `YYYY-MM-DD` (caller-supplied).
- `--review-after` — optional ISO date to re-surface it for review. No expiry by default.

`--reason` is one of: <!-- fact:begin duplication.reasons -->`benign-idiom`, `deliberate-twin`, `vendored`, `generated`, `other`<!-- fact:end -->.

## What a Result Means

Families are ranked by their longest clone. A family groups copies that connect:
all the copies between two classes are one family, a copy inside one class
stays with its methods, and a copy between a function and a class method is not
folded into the class. Two definitions with the same name in one file (an
`if`/`else` twin) are one location with two line ranges. Each family shows its sites (`a.py:10-30 (Cls.method)
<-> b.py:40-60 (Other.method)`) and a status:

- `new` — not dismissed.
- `resurfaced` — part of a dismissed family, with **new sites**: a member
  added, renamed or moved, or a new copy bridging two dismissed families. Only
  the new sites are shown; judge those.
- `review-due` — a dismissal whose `--review-after` date has come.

Filters, always on and stated in every run:

- **Function filter.** A clone counts only when more than <!-- fact:begin duplication.filter.function_line_share -->50 %<!-- fact:end --> of the lines of one
  of its regions are inside a `def`; module-level and class-body data drops out.
- **Signature/stub guard.** A clone is dropped when at least <!-- fact:begin duplication.filter.signature_line_share -->60 %<!-- fact:end --> of both
  regions' lines are decorators, signatures or stubs (`@overload`,
  `@abstractmethod`, or bodies of only `...`, `pass`, a docstring or
  `raise NotImplementedError`). A concrete method of an ABC or `Protocol` is
  real code and is kept.
- **Naming.** Each region is named after the function or class holding most of
  its code (counted in AST tokens, so comments and blank lines don't count). A
  copy that starts in the tail of the previous function is still named after the
  copied one, and a comment-only edit never changes a location.

## The Review Loop

1. **Run the review** over the scope, with the state file.
2. **For each family, top down:** read the longest pair's two regions (targeted
   reads), then decide:
   - **Consolidate** — a real copy. Say which version is canonical. Check
     whether the copies have **drifted** (one has a fix, a branch or an
     `else` the other lacks): that is the finding to lead with.
   - **Dismiss** — boilerplate or a deliberate copy. Record it with `dismiss`
     and the right `--reason`. Ask the human before dismissing; it's their call.
3. **Report** the families you looked at, the verdict on each, the drift you
   found, and the threshold and filters used. Never present a family as a fact.

## Dismissals

A dismissal is keyed on the family's sorted member locations plus the fact
`duplication` (the `architecture-review` non-issue key). Once dismissed:

- **Stays suppressed:** cosmetic edits, drift between the dismissed members, a
  member removed.
- **Re-surfaces:** a new member joins, a member is renamed or moved, or a new
  copy bridges two dismissed families. Only the
  new or changed members are shown.
- **Expiry:** none by default. With `--review-after`, it re-surfaces as
  `review-due` once the `--today` you pass reaches that date.

Each dismissal records its reason and date. Commit the state file so the whole
team shares the dismissals.

## Honest Limits

- No semantic duplication: the same behaviour written differently isn't found.
- No near-miss copies: inserted or deleted statements break a match.
- Copies shorter than `--min-tokens` aren't reported.
- A copy that starts inside a class body and runs into a method can be filtered
  out with the class-body data.
