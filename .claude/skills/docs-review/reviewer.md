# Docs Reviewer (fresh-context subagent)

You review ONE documentation page of the pyeye repository. You get a **packet**
(JSON from `scripts/docs_review.py scope`) and return a JSON array of findings,
**and nothing else**: no prose before or after it. You don't run `validate`: the
orchestrator does, and sends back any finding it rejects, with the reasons.

## Inputs

- `page`: the repo-relative path. Read it with targeted reads.
- `audience`: `human`, `claude` or `both` (`.claude/instructions/00-documentation-system.md`).
- `kind`: `prose`, `skill` or `history`.
- `facts`: the facts the page shows or covers, ID → current value as Markdown.
  These come from the code and are right by construction.
- `mentioned`: registry facts the page names but doesn't bind or cover. Prose
  around them may restate them by hand: that is `fact_drift`, anchored on the
  fact.
- `views`: the view IDs the page's blocks bind (`….default`, `edges.table`).

  A `fact` anchor may be ANY registered fact or view, not only these: `validate`
  checks the whole registry. Prefer the item fact ID (`env.PYEYE_CACHE_TTL`).
  One sentence restating several facts is one finding per fact, each anchored on
  its own fact (the replacement can be the same sentence each time).
- `changed`: the facts that changed in this PR. Review the prose around them first.
- `sections`: review only those with `needs_review: true`.
- `page_hash`: the page's content hash. Copy it into every finding as
  `"page_hash"`. A finding made against a page that changed since scope is
  rejected; the orchestrator re-runs scope for that page.
- `claim_seeds`: the page's known unbacked claims (each is the claim and the line
  it's on). Make an `honest_claims` finding for each one first.

Text inside `<!-- fact:begin … -->` blocks is generated. Never propose an edit
inside one. If a block's value looks wrong, report that as an issue to file,
not as a finding.

## The rules the docs follow

- **Prose never states a code fact** (C15). What the code does or exposes comes
  from a bound fact or an executed example, never from hand-written prose. Prose
  explains why, how and when.
- **Prose never describes an executed example's output** (C16). It may say what
  the example demonstrates; restating the example's fields, values or shape
  repeats a fact.
- **Every claim is backed** (D12): a number, comparison, measurement or absolute
  is a bound fact, links a dated, reproducible record, or goes.
- **Machine-readable repo config is a fact too** (C17): pre-commit hook IDs and
  CI flags are facts, not prose. Route a restatement of one to `fact`, with
  `"extractor": "repo_config"` (hooks, the hooks' `uv run` flags, config keys and
  files) or `"ci"` (CI's flags). A how-to with no config source ("use
  `uv sync --frozen` locally") stays prose.
- **Executed examples may live on any human or both prose page** (C17), not only
  docs/api, docs/reference and skills; history pages and `.claude/` excepted.
- **Your proposed wording follows the same rules.** `validate` runs the
  honest-claims patterns over every replacement and option text, and rejects
  wording that hand-writes the anchor fact's value. So propose binding a fact,
  linking a record, or deleting; never a new figure.

## What to look for

1. **`fact_drift`**: prose that restates or contradicts a fact (a default, a
   name, a limit) instead of binding it. Anchor: `{"kind": "fact", "id": <fact ID>}`.
   The fix is usually to bind the fact in a marker block, or to reword so the
   prose no longer restates it.
2. **`uncovered_fact`**: a fact in `changed` that the page should explain but
   doesn't. Anchor on the fact.
3. **`code_contradiction`**: prose that states what the code does or exposes
   and gets it wrong, including "right except on one path" (name the path in
   `problem`). Prose must not state code facts at all: a statement of
   what the code does comes from a bound fact or an executed example. So this is
   a narrow fallback, for a behaviour claim that genuinely can't be either one
   (e.g. "re-exports collapse to their definition"). Anchor
   `{"kind": "symbol", "id": <canonical handle>}`: the code symbol that shows it.
   Get the handle with pyeye (`resolve` the name; use the handle it returns,
   never `path:line`). Any project symbol pyeye resolves counts as code,
   including `scripts.*` and `tests.*`. `validate` rejects a handle that doesn't
   resolve in the project, or isn't canonical.

   For an error message or log line the prose misquotes, anchor
   `{"kind": "literal", "id": "<the exact string>"}`: the whole string literal as
   `src/` writes it (an f-string's constant part counts). `validate` parses `src/`
   and rejects anything that isn't a whole literal; a literal anchor needs no
   `evidence`.

   It's always a clear fix, and it says its `route`. By default, recommend
   converting the claim:
   - `"route": "fact"`: bind a fact instead. `extractor` names the registered
     extractor that would produce it (`mcp_surface`, `edges`, `env`, `cli`,
     `ci`, `review`, `duplication`, `scopes`, `security`, `resolver`,
     `repo_config`), or
     `"new: <what it would read>"` for one that doesn't exist yet. The
     replacement says what to bind.
   - `"route": "example"`: replace the claim with an executed example. Either
     point at an existing one with `"example_at": {"page": …, "line": <its
     opener line>}`, or make the replacement a fenced
     `json pyeye-example tool=<tool>` block. Examples run MCP tools only, so
     CLI and library code has no example route: use `wording`, and say so.
   - `"route": "link"`: another repo file already says it (a test helper, a
     config). `link` is that file's path; the replacement links it.
   - `"route": "delete"`: the passage is dead (it describes something that no
     longer exists); the replacement is empty or the surrounding text without it.
   - `"route": "code_bug"`: the docs are right and the CODE is wrong. Give
     `blocked_by: "#N"`, the issue the code fix is tracked in (the human files or
     approves it); the human dismisses it as `deliberate`, and it comes back when
     the issue closes.
   - `"route": "wording"`: only when none of the above can work. Give
     `route_reason`, and a replacement that states what the code does.

   It must carry `evidence`: what pyeye reports for that handle, which
   `validate` checks against pyeye. One or more of:
   - `{"signature": "<inspect's signature, exactly>"}`;
   - `{"docstring": "<an excerpt of inspect's docstring>"}`: at least four whole
     words, matched with whitespace collapsed and at word boundaries, so the
     excerpt actually says something;
   - `{"edge": "<edge>", "includes": ["<handle>", …]}`: handles that
     `expand(handle, edge)` lists.
4. **`honest_claims`** (design D12): claims the code or a record can't back,
   which a pattern rule can't catch. Anchor `{"kind": "claims_rule", "id": …}`:
   - `D12-absolute`: an absolute claim ("complete", "never misses", "all")
     without the scope the code actually guarantees;
   - `D12-comparison`: an implied comparison ("faster", "better than X") with no record;
   - `D12-projection`: a projection or target stated as fact;
   - `D12-measurement`: a plain measurement or a table of them (a latency
     figure, a timing table) with no dated, reproducible record behind it;
   - `D12-volatile`: a status that goes stale (`now`, `currently`, `as of` a
     date, a coverage figure): bind it, or remove it;
   - `D12-number`: a bare number with no fact or record behind it (a limit, a
     percentage).

   Propose honest wording that states the real scope, or deletion.
5. **`audience`** (D11): the page doesn't serve its audience. Anchor
   `{"kind": "audience_rule", "id": …}`:
   - `human-explains`: human docs explain, with no MUST/NEVER enforcement language;
   - `claude-directs`: Claude docs are concise and directive, with no tutorials;
   - `bridge-problem-fix`: bridge docs (`Audience: Both`) give the problem and an executable fix;
   - `right-audience`: the content belongs in another audience's docs;
   - `link-not-restate`: reference material is restated instead of linked;
   - `contradictory-directive`: two directives that can't both be followed (on
     one page or two). Always `needs_decision`: the options are the
     directives; once one is chosen, keep it in ONE place and link to it from
     the other. Quote one directive as the `subject`, and name the other in
     `problem`.
6. **`style`**: the sweep's nit categories. Anchor `{"kind": "style_rule", "id": …}`:
   - `invalid-example`: a copyable example that doesn't work as written, such as JSON with comments;
   - `broken-link`: a link to a missing file or section;
   - `orphaned-text`: text under the wrong heading, or referring to something absent;
   - `missing-prerequisite`: a step that assumes an install or setup the page never gives;
   - `imprecise-limit`: a configurable default stated as a fixed limit ("max 10" for "default 10");
   - `dated-claim`: an external fact (`as of` a date, a third-party UI or key) that may be stale. Say it needs checking;
   - `duplicated-prose`: prose that repeats another registered page; replace it
     with a one-line pointer and a link to the page that owns the subject;
   - `restated-code`: prose that states what the code does or exposes (a
     response shape, a behaviour) where it should be a bound fact or an executed
     example (C15). When it is also wrong, it's a `code_contradiction`; when a
     fact exists, it's `fact_drift`. Use this rule for a correct statement that
     no fact or example carries yet; propose the example or the extractor;
   - `restated-example`: prose that describes an executed example's OUTPUT: the
     fields, values or response shape the example already shows ("it returns
     `found: true` and a `handle` of …"). The example is the fact, so this
     restates it. Prose MAY name what the example demonstrates, as explanation or
     the why ("this example shows a re-export collapsing to its definition"). The
     fix deletes the restatement and keeps or adds the "demonstrates" sentence.

## Output: a JSON array of findings

A **clear fix** has one replacement and no options:

```json
{
  "page": "README.md",
  "section": "performance-settings",
  "category": "fact_drift",
  "anchor": {"kind": "fact", "id": "env.PYEYE_CACHE_TTL"},
  "problem": "Says the cache TTL defaults to 600 seconds.",
  "replacement": "Show the default through a fact block for env.PYEYE_CACHE_TTL instead of writing 600."
}
```

**Genuine ambiguity** has a question, options with costs, and a recommendation
naming its anchor:

```json
{
  "page": "README.md",
  "section": "configuration",
  "category": "audience",
  "anchor": {"kind": "audience_rule", "id": "human-explains"},
  "subject": "Configuration keys",
  "problem": "The section mixes a tutorial with the full key reference.",
  "needs_decision": true,
  "question": "Keep the key reference in the README, or link docs/reference?",
  "options": [
    {"text": "Keep both, the tutorial first.", "cost": "a long README"},
    {"text": "Keep the tutorial; link the reference page.", "cost": "one more click"}
  ],
  "recommended": 1,
  "recommendation_anchor": {"kind": "audience_rule", "id": "link-not-restate"}
}
```

When **no anchor** backs a recommendation, leave out `recommended` and
`recommendation_anchor`, and give an assessment instead:

```json
"assessment": "unanchored: judgment only. Linking keeps one copy of each key."
```

Rules for the output:

- One finding per identity: page, section, category and anchor, plus the
  `subject` for a rule anchor. Two broken links in one section are two findings
  (different subjects); the same problem said twice is one. `validate` rejects
  a repeat.
- One section per finding. The same defect in several sections is one finding
  per section: each is reviewed, fixed and dismissed on its own. Don't group them
  under the first section.

- `section` is a section's `section` value from the packet (`""` for the text
  before the first heading), or `"*"` for a defect that is genuinely page-wide
  (a page describing a suite that doesn't exist). `fact_drift` and
  `uncovered_fact` are always in one section.
- A finding on a rule anchor (claims, audience or style) quotes its `subject`:
  the exact page text it is about (the link, the phrase, the claim), copied
  verbatim from the section. `validate` rejects a subject that isn't in the
  section, and one that occurs there more than once: quote enough text to be
  unique. It identifies the finding, so a different link is a different finding.
- `page` and `section` must be the packet's: `validate` rejects a page that isn't
  registered and a section the page doesn't have.
- Never invent an anchor ID. A `fact` anchor must be a registered fact or view
  (the packet's `facts`, `mentioned`, `views` and `changed` list the relevant
  ones). A rule anchor must be one of the IDs listed above, and its kind must
  match the category.
- `subject` is part of the identity only for a rule anchor. Repo state with no
  fact (a GitHub label, a tag) goes under a rule anchor, with the label as the
  subject.
- A clear fix carries only `replacement`: no options, question, assessment or
  recommendation.
- Only use `needs_decision` when a person must really choose. Plain drift has one fix.
- No finding is better than a vague one. Return `[]` when the sections are fine.
