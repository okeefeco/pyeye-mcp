---
date: "2026-11-18"
title: "Load-time facts come from the installed code only, never from repo files; CI imports a built wheel outside the repo (#851)"
issues: [851, 827, 837]
anchors: ["pyeye.docs_facts.describe.load_time_facts", "pyeye.docs_facts.extractors.edges.extract_code", "pyeye.docs_facts.extractors.scopes.extract_code", "tests/test_docs_facts_describe.py", ".github/workflows/ci.yml"]
status: "amended"
amends: ["2026-11-17-827-tool-descriptions-fill-fact-slots-from-load-time-extractors.md"]
supersedes: []
amended_by: ["2026-11-23-1098-the-server-describes-its-live-code-docs-facts-reads-the-source.md"]
superseded_by: []
---

## 2026-11-18 — Load-time facts come from the installed code only, never from repo files; CI imports a built wheel outside the repo (#851)

**Friction:** #827 fills tool descriptions while `pyeye.mcp.server` loads, from the `edges` and `scopes` extractors' full `extract(root)`, with `root` being the current directory. #837 then added an `edges` fact read from `tests/conformance/response_linter.py`. From then on, `import pyeye.mcp.server` raised `FileNotFoundError` whenever that file wasn't under the cwd:

- in every wheel install, which has no `tests/`;
- in a checkout started from any other directory.

Only the Claude Code plugin, which runs from the repo root, kept working. Nothing tested an import outside the repo.

**Decision:**

- **A code-only entry point.** Each load-time extractor has `extract_code()`, which takes no root and reads no file. `describe.load_time_facts` calls only that. `extract(root)` is `extract_code()` plus any facts read from repo files; for `edges` that is `edges.inspect_unmeasured`, which belongs to the docs checks. The registry still calls `extract(root)`.
- **Two gates.**
  - **Fast:** tests that `extract_code` takes no parameters, that `load_time_facts()` works from an empty directory, and that `python -I -c "import pyeye.mcp.server"` succeeds from an empty directory.
  - **The real install:** the required `type-check` job, which runs on `merge_group`, builds the wheel, installs it into a clean venv, and imports the server isolated from an empty directory. It lives in an existing required job, so no ruleset change is needed.

**Anchor:** `pyeye.docs_facts.describe.load_time_facts`; `pyeye.docs_facts.extractors.edges.extract_code`; `pyeye.docs_facts.extractors.scopes.extract_code`; #851, #827, #837.
**Applies-to:**

- the code-only path: `pyeye.docs_facts.describe.load_time_facts`, `pyeye.docs_facts.extractors.edges.extract_code`, `pyeye.docs_facts.extractors.scopes.extract_code`;
- every future load-time extractor listed in `pyeye.docs_facts.describe.LOAD_TIME_EXTRACTORS`;
- the gate: `.github/workflows/ci.yml` job `type-check`, step "Import the installed wheel outside the repo".

**Verify:** gold.

- `uv run pytest tests/test_docs_facts_describe.py -k "no_root or no_repo or outside_the_repo"` passes.
- CI's `type-check` step passes.
- A wheel built from `main` at `f8cc2126` fails that same step with `FileNotFoundError: 'tests/conformance/response_linter.py'`.
