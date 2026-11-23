---
name: architecture-review
description: Use when reviewing a Python codebase's architecture against what it has recorded — "review the architecture", "audit conventions", "does this area follow our decisions", "where does this code disagree with itself", "find inconsistent error-handling/layering/validation patterns". Reviews ONE area against its architecture facts, CHECK rules and decision entries, and reports adherence, deviation, decisions needed and ambiguity, each anchored. A resolved item becomes a decision entry (and, where it can be checked, a CHECK line), so each run leaves less to judge. Needs a docs-facts config with the structure kind; without recorded architecture it says so. Does NOT find duplicated code (that is duplication-review) and does NOT map the architecture (that is /arch-facts).
---

# Architecture Review

Review **one area** of a codebase against its **recorded architecture**: the
architecture facts pyeye extracted, the `CHECK` rules on its architecture pages,
and its decision entries. Every finding is one of four outcomes, each anchored,
and the maintainer decides what happens next. Each decision becomes a record
the next run checks, so the review leaves less to judge every time.

## What This Is (and Is NOT) — Read First

- **It compares the code with records, never with itself alone.** A deviation
  always names the rule, decision or convention it deviates from. Where no
  record covers a pattern, the finding asks for a decision; it never picks one.
- **The tool never decides.** Nothing is written, no rule and no decision entry,
  without the maintainer.
- **It needs recorded architecture.** It reads the repository's docs-facts
  snapshot: the `structure` kind's facts (`/arch-facts` makes them). Without
  them, the plan says "no recorded architecture for this area; run /arch-facts
  first", and you stop there.
- **Not duplication.** Copied code is [`duplication-review`](../duplication-review/SKILL.md).

## The Four Outcomes

| Outcome | Means | Rests on | Way forward |
|---|---|---|---|
| **adherence** | the code follows a recorded rule, decision or convention | that record | none: a confirmation |
| **deviation** | the code contradicts one | that record | a recommendation |
| **decision_needed** | no record covers it, and one pattern is clearly the norm | the evidence (a fact or a symbol) | the question, and one proposed decision |
| **ambiguity** | no record covers it, and several patterns compete | the evidence | the question, 2–3 options with costs, and a recommendation on an anchor or an "unanchored: judgment only" assessment |

## Running It

The engine is `python -m pyeye.docs_facts architecture`. Run it from the
repository root. Through the plugin:

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT}" ]; then  # the plugin's environment
  CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}" CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" \
    uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py" \
    python -m pyeye.docs_facts architecture plan AREA
else  # pyeye's own repository, where this is a project skill: the checkout's environment
  uv run --project "$(git rev-parse --show-toplevel)" --frozen \
    python -m pyeye.docs_facts architecture plan AREA
fi
```

Otherwise, any environment with `pyeye-mcp` installed:
`python -m pyeye.docs_facts architecture …`. Every command prints JSON.

| Command | Does |
|---|---|
| `plan AREA [--decisions-dir D] [--convention PATH ...]` | The area's packet: its facts, the rules in scope (already run), the candidate decisions, and the mechanical findings. |
| `validate FINDINGS --packet PACKET` | Each invalid finding's problems; exit 1 when any. |
| `report FINDINGS --packet PACKET` | The ranked report, with the mechanical findings and the valid reviewer ones. |

**`AREA`** is an area ID from the `structure` kind's `areas` (inline or a data
file), or else a module prefix (`pkg.core` covers `pkg.core` and
`pkg.core.*`). It is required: never review the whole repository at once.

**`--convention PATH`**: for a repository with no decision entries, its
convention document (`AGENTS.md`, `CONTRIBUTING.md`) is the prose anchor.
Pass it, repeatable.

## The Review Loop

1. **Plan.** Run `plan AREA` and save the packet to a scratch file. If its
   `notes` say there's no recorded architecture, tell the user and stop.
2. **Dispatch the reviewer**, one fresh subagent for the area, with
   [`reviewer.md`](reviewer.md) and the packet. It reads the packet's facts and
   the candidate decisions, uses pyeye for evidence with targeted reads only,
   and returns a JSON array of findings, nothing else.
3. **Validate.** You run it, never the reviewer: write the findings to a
   scratch file and run `validate FINDINGS --packet PACKET`. A finding with
   problems goes back to the reviewer with the problems quoted; never fix it
   up yourself.
4. **Report.** Run `report` and present it to the user verbatim, in its order:
   1. **rule deviations**;
   2. **deviations from decisions and conventions**;
   3. **decisions needed**;
   4. **ambiguities**;
   5. **adherence**, as a count, with the findings on request.

   Then what the review couldn't settle: unverified rules, unresolved
   decision sites, unassigned modules and coverage gaps. Show each finding's
   evidence as the report gives it; don't re-narrate it.
5. **The user decides**, item by item:
   - **a deviation:** fix the code, or decide the record changes (then codify
     the new decision, step 6);
   - **a decision needed or an ambiguity:** their answer, including "both
     patterns are acceptable here", is codified (step 6);
   - **deferred:** nothing is recorded. The item comes back on the next run.

There are **no dismissals.** Every resolution is a decision entry, and the next
run reports adherence to it instead of asking again.

## Codify (always on the user's decision)

1. **Write the decision entry** through the [`decision-log`](../decision-log/SKILL.md)
   skill's flow, which applies in full: its gates, fields and file convention.
   Pull the question, the evidence and the chosen option from the finding
   verbatim. Its `Applies-to` must name the sites the decision governs, by
   canonical handle (the finding's evidence, and the rest of the area it
   covers): that is how the next run's plan finds it as a candidate.
2. **Draft a `CHECK` line** when the decision is one an existing rule kind can
   check. Today that is `CHECK no-import: A -> B` ("modules under A never
   import B at runtime"). Show the line and the architecture page it belongs on
   (a registered page holding the area's other `CHECK` lines). Add it only when
   the user confirms. From then on `docs_facts check` enforces it on every
   commit, and the review reports adherence or deviation mechanically.
3. A decision no existing rule kind can express stays a decision entry: future
   reviews check it. Don't invent a rule kind.

## Honesty Invariants

- **No deviation without a record.** An unanchored "this looks wrong" is a
  decision needed or an ambiguity, never a deviation.
- **Prevalence is evidence, never correctness.** "Most sites do X" can make a
  decision needed; it never makes the minority a deviation.
- **Rule outcomes are mechanical.** The plan runs the `CHECK` lines; nobody
  re-judges them. An unmeasured module leaves a rule unverified, never passing.
- **An unresolved site is reported.** A decision site pyeye can't resolve is
  listed, never treated as "not in this area".

## Failure Modes

- **No area given** → ask for one.
- **No docs-facts config** → `plan` exits 1, "nothing to check". The repository
  hasn't set up docs-facts: say so.
- **No recorded architecture** → the plan's note; suggest `/arch-facts`.
- **pyeye unavailable** to the reviewer → it can still judge from the packet's
  facts, but can't check evidence handles; `validate` will reject unresolved
  ones. Say the review is reduced.
- **The reviewer returns non-JSON** → a contract violation: re-dispatch.
