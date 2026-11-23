# Structured verification on real codebases (2026-11-23)

The first run of the release-pass verification step (#1140, `docs/RELEASE.md` step 2). It used the `pyeye-verify` procedure on the two release-pass scenarios from `pyeye-scenarios`. The baseline records it created are `.claude/skills/pyeye-scenarios/baselines/poetry.md` and `scrapy.md`.

- **Code under test:** pyeye `main` at `f58d0b86`. The probes ran on a fresh server built from `f053174e` (`2.2.1.dev75+gf053174ea`); the commits between it and `f58d0b86` change only docs-facts generation. The task-trial agents ran `claude --plugin-dir` on a clone at `f58d0b86`. After #1166 merged, the Scrapy probes were re-run directly from a checkout at `596c8bd6` (`2.2.1.dev101+g596c8bd60`).
- **Scenarios:**
  - Poetry 2.5.2 (`4934abbd`), a `src/`-layout project;
  - Scrapy 2.20.0 (`4a421e45`), a plain tree.

  Both were provisioned at their pins, and copies outside the pyeye repository were used for the agent runs.
- **Machine:** dev01 (Linux, 8 GB), Claude Code 2.1.319, each agent memory-capped, at most two at a time.

## Verdict

**Pass.** There are no regressions: no earlier baseline existed for either scenario, and the probes that cover earlier fixes all hold. The round-trip probe found 0 misses on both, and both task trials were as accurate as their controls.

- **One defect found: #1159.** It was reproduced on `main` and filed, then fixed by #1166 the same day. It is verified fixed on `596c8bd6` (`2.2.1.dev101+g596c8bd60`), where the Scrapy probes were re-run and are all ✅.
- **The token cost of pyeye:** the skill + pyeye arm used **1.2× (Scrapy) to 2.9× (Poetry) the tokens** of the grep-only control, for equal accuracy. That is the measure #1130's guidance ("find with grep, prove with pyeye") is judged by.

## Probes

| Scenario | Probes | Round-trip | Notes |
|----------|--------|------------|-------|
| poetry | 8 ✅ | `poetry.installation.executor`: 0 of 39 miss | ✅ #1126 holds: `Hexdigest(md5: str \| None, sha256: str \| None, blake2_256: str \| None)` |
| scrapy | 5 ✅ (on `596c8bd6`) | `scrapy.spidermiddlewares.referer`: 0 of 22 miss | ✅ #1125 holds. #1133 is explained (below). Row 4 was ❌ on `f053174e` (#1159); it is ✅ after #1166 |

- **#1133 (already closed as not reproduced; this run agrees):** `expand("scrapy.spidermiddlewares.referer", "imports")` reports `warn` as `_warnings.warn`. That's the canonical definition site of `from warnings import warn` in typeshed, not a stdlib module's imports attributed to `referer`. `unresolved_imports` is `[]`.
- **#1159 (found by this run, fixed by #1166 the same day):** a parameter annotation that spans lines truncated the rendered signature at its first line. On `f053174e`, Scrapy's `Request` stub showed `Request(url: str, callback: CallbackT | None=None, method: str="GET", headers: Mapping[str, Any]`, with no closing paren. It was reproduced on `main` with a minimal function and class before filing; the cause was `_build_signature` keeping only the first line of Jedi's render. **Verified fixed** on `596c8bd6`: both `Request` and `Response` now render whole, on one line.

## Agent-consumption rubric: 8/8 pass

- **Absence vs zero:** `inspect(Hexdigest)` measures `superclasses: 0` and leaves `callers` out of `edge_counts`.
- **No content leakage:** every probe returned handles and locations, never source.
- **Honest limits:** `expand(Factory, "callers")` refuses with `deferred_reference_backend`.
- **Right altitude:** `expand(hashlib, "imported_by", max_stubs=3)` flags the cut (`truncated`, `max_stubs`, `total: 10`).
- **Canonical handles:** `scrapy.Spider` collapses to `scrapy.spiders.Spider`, and `poetry.utils.env.Env` to `…base_env.Env`.
- **Static-surface honesty:** every edge carried its ceiling (`static_imports`, `static_calls`, `literal_subclassing`, `on_disk_modules`).
- **Cross-repo correctness:** neither scenario spans repositories. Within each, the round-trip probe found 0 `disagree` and 0 `handle mismatch`.
- **Determinism:** a repeated `imported_by` gave the same stubs in the same order.

## Task trials

| Scenario | Arm | Correct | Turns | Tokens | Time |
|----------|-----|---------|-------|--------|------|
| poetry | grep-only control | yes | 4 | 89,625 | 21 s |
| poetry | `python-explore` + pyeye | yes | 11 | 258,506 | 33 s |
| scrapy | grep-only control | yes | 8 | 209,335 | 32 s |
| scrapy | `python-explore` + pyeye | yes | 10 | 245,611 | 32 s |

- **Accuracy is equal.** Both arms found every fact in the ground truth, and both Poetry arms also named the near-duplicate `EditableBuilder._get_file_hash`.
- **What pyeye added is proof, not discovery.** In Scrapy, `callees` on `LxmlLinkExtractor._link_allowed`, with 0 unresolved call sites, showed which helper is used. In Poetry, the skill agent took the callers from the LSP, since pyeye defers them (#333), and checked each call site with `resolve_at`.
- **Cost:** the skill arm used about 1.2× (Scrapy) and 2.9× (Poetry) the tokens. That fits the skills audit, which put loading the skill at about 35–45k tokens per task.
- The guidance change from that audit (#1130: find with grep, prove with pyeye) is in this build. The transcripts weren't reviewed, so whether it removed the guessing the audit saw isn't measured here.

## Actions

- Filed **#1159**, fixed by #1166 and verified fixed on `596c8bd6`.
- Recorded the first `poetry` and `scrapy` baselines.
- #1133 needs nothing more: it was already closed as not reproduced, and this run agrees.
