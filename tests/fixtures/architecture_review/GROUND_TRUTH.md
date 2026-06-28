# GROUND_TRUTH — planted-stakes oracle

This file is the **oracle** for the architecture-review audit fixture. The code
under analysis lives in `app/` (this file is deliberately **outside** that
subtree so it is never part of the audited package). Each entry below records a
KNOWN planted architectural divergence: its axis, stakes, blast radius, the
divergence itself (clusters + prevalence counts), and the expected auditor
behavior.

Axis keys are drawn from the 7 seed axes: `layering`, `module_boundaries`,
`dependency_acquisition`, `error_handling`, `validation_placement`,
`naming_api_shape`, `cross_cutting`.

## Import graph (so blast radius is real)

- **HUB:** `app/core/config.py` — imported by `core/database.py`,
  `handlers/{user,order,payment,report}_handler.py`,
  `services/{user,order,report}_service.py`, and `security/permission_check.py`.
  High `imported_by` (~9 importers).
- **LEAF:** `app/security/permission_check.py` — imported by **zero** other
  modules in `app/`. Low `imported_by` (0 importers).

This HUB/LEAF split is what makes the Plant 2 ↔ Plant 3 proxy-inversion real.

---

## Plant 1 — Prevalence-trap error handling

- **Axis:** `error_handling`
- **Stakes:** **high** — silently swallowing exceptions hides real failures
  (data loss, false success) and is hard to debug in production.
- **Blast:** spread across the `handlers/` siblings (medium structural reach;
  not the ranking point here).
- **Divergence (clusters + prevalence):**
  - **MAJORITY = 3 of 4 — SWALLOW (the WRONG pattern):**
    - `app/handlers/user_handler.py` — `except Exception: return None` and a
      bare `except: return []`.
    - `app/handlers/order_handler.py` — `except Exception: return {}`.
    - `app/handlers/payment_handler.py` — `except Exception: return False`.
  - **MINORITY = 1 of 4 — PROPAGATE (the CORRECT pattern):**
    - `app/handlers/report_handler.py` — no swallow; wrap-and-reraise
      (`raise ReportError(...) from exc`).
- **THE MAJORITY IS THE WRONG PATTERN.** This is the prevalence trap.
- **Expected auditor behavior:** report the divergence **NEUTRALLY**. Must
  **NOT** recommend the majority (swallow) just because it is the majority.
  Prevalence is described, not used as the decision rule.

---

## Plant 2 — High-stakes validation-placement on a LEAF  ⟵ proxy-inversion pair (A)

- **Axis:** `validation_placement`
- **Stakes:** **HIGH** — this is a security/correctness boundary
  (authorization + money parsing). Misplaced/missing validation here can allow
  unauthorized transfers and unvalidated amounts/targets.
- **Blast:** **LOW** — `app/security/permission_check.py` is a LEAF, imported by
  **0** other modules in `app/`.
- **Divergence:** `authorize_transfer` (the boundary) does **no** input
  validation; validation is scattered deep in `_apply_transfer` (after parsing
  unvalidated input) and is **incomplete** (`target_account` is never
  validated; non-admins are silently allowed for "small" amounts). The rest of
  the app validates at the boundary; this leaf does not.
- **Expected auditor behavior:** flag as a real, high-priority finding despite
  the low blast radius — **stakes**, not reach, drive its rank.

---

## Plant 3 — Low-stakes naming on a HUB  ⟵ proxy-inversion pair (B)

- **Axis:** `naming_api_shape`
- **Stakes:** **LOW** — purely cosmetic naming inconsistency; no
  correctness/security impact.
- **Blast:** **HIGH** — `app/core/config.py` is the HUB, imported by ~9 modules.
- **Divergence:** the same kind of read-only config accessor is spelled three
  different ways in `app/core/config.py`: `get_setting` / `get_retries` (get_*),
  `fetch_timeout` (fetch_*), `retrieve_database_url` (retrieve_*).
- **Expected auditor behavior:** report neutrally as low-severity. Its high
  blast must **not** float it above Plant 2.

### Proxy-inversion pair (Plant 2 ↔ Plant 3) — expected ranking

Blast-radius **alone** would rank **Plant 3 (hub, high blast)** above **Plant 2
(leaf, low blast)**. The **axis-stakes prior inverts this**: `validation_placement`
(HIGH stakes) outranks `naming_api_shape` (LOW stakes).

> **Expected final ranking: Plant 2 (validation_placement) ranks ABOVE Plant 3
> (naming_api_shape)** — even though Plant 3 has the higher blast radius.

This is the central bet-3 test: stakes beat blast as the ranking proxy.

---

## Plant 4 — Module-global dependency acquisition

- **Axis:** `dependency_acquisition`
- **Stakes:** **medium** — import-time singletons and mutable module globals
  hurt testability and create hidden coupling, but are not directly a
  security/correctness defect.
- **Blast:** medium — `app/core/database.py` is imported by the handlers.
- **Divergence (clusters):**
  - **MODULE-GLOBAL SINGLETON:** `app/core/database.py` constructs `DB =
    Database().connect()` at import time and exposes a mutable global `_client`
    via `get_client()` / `reset_client()`. `handlers/user_handler.py` and
    `handlers/order_handler.py` import the `DB` global directly;
    `handlers/payment_handler.py` calls `get_client()`.
  - **PARAMETER INJECTION:** `app/services/report_service.py` `load_report(...,
    db)` takes its database dependency as an argument.
- **Expected auditor behavior:** report the divergence neutrally (global-
  singleton vs injection) with evidence; injection is generally preferable but
  describe both clusters rather than just asserting the majority.

---

## Plant 5 — Ambiguous result-shape fork (NO ANCHOR → empty recommendation)

- **Axis:** `naming_api_shape` (result-shape / API contract)
- **Stakes:** **low–medium** — inconsistent result shapes add friction but
  there is no correctness defect.
- **Blast:** spread across the `services/` layer.
- **Divergence (clusters):** the SAME conceptual "operation result" is returned
  three different ways:
  - **dict:** `app/services/user_service.py` → `{"ok": ..., "data": ...,
    "error": ...}`.
  - **`@dataclass`:** `app/services/order_service.py` → `OrderResult(...)`.
  - **tuple:** `app/services/report_service.py` → `(ok, data, error)`.
- **NO ANCHOR:** there is no documented decision and no stdlib idiom that
  settles which shape is correct.
- **Expected auditor behavior:** present **clusters + evidence** and emit
  **recommendation = NONE / null** ("you decide"). This is the
  **empty-recommendation** fixture — a genuine fork with no deciding anchor.

---

## Summary table

| Plant | Short name | File(s) | Axis | Stakes | Blast | Expected behavior |
|------:|-----------|---------|------|:------:|:-----:|-------------------|
| 1 | Prevalence-trap error handling | `app/handlers/{user,order,payment}_handler.py` (swallow ×3) vs `report_handler.py` (propagate ×1) | `error_handling` | high | medium | Neutral; **do NOT recommend the majority** |
| 2 | High-stakes validation on a LEAF | `app/security/permission_check.py` | `validation_placement` | **high** | **low** | High-priority finding; **ranks ABOVE Plant 3** |
| 3 | Low-stakes naming on a HUB | `app/core/config.py` | `naming_api_shape` | **low** | **high** | Low severity; **ranks BELOW Plant 2** |
| 4 | Module-global dep acquisition | `app/core/database.py` (global) vs `app/services/report_service.py` (injection) | `dependency_acquisition` | medium | medium | Neutral; describe both clusters |
| 5 | Ambiguous result-shape fork | `app/services/{user,order,report}_service.py` (dict / dataclass / tuple) | `naming_api_shape` | low–med | medium | Clusters + evidence; **recommendation = NONE** |

**Proxy-inversion pair:** Plants **2** and **3**. Expected ranking (bucketed-lexicographic,
spec §11): **Plant 2 (validation_placement, `high` bucket) > Plant 3 (naming_api_shape, `low`
bucket)** despite Plant 3's higher blast — the stakes bucket dominates; blast only orders within
a bucket. (Verified: with the explicit `AXIS_STAKES_BUCKET` map, Plant 2 ranks above Plant 3 even
at blast 0 vs blast 9.)

---

## Promotion-chain dogfood targets (the confident path)

These designate the inputs used to dogfood the gate / cross-derivation guard **live** (the
divergence plants above are all `ambiguous`, so they exercise detection + ranking, not the
confident path). See the dogfood report `docs/superpowers/notes/2026-06-29-architecture-review-dogfood.md`.

- **Gate-promote target — genuine universals (N/N).** Within `app/handlers/` every public entry
  function is `handle_*` (6/6); within `app/services/` every function is `load_*` (4/4). These are
  counting facts → `deterministic_single`. Expected: stable across N auditor re-runs.
  **Live finding:** the handle-set + grade reproduce identically across 3 runs, but the shipped
  reproduction gate **downgrades them anyway** because `findings_equivalent` keys on the claim
  *string* and LLM phrasing varies run-to-run — a real defect (spec §10 says "phrasing ignored";
  the impl doesn't). Tracked as **#498**. So this target proves the gate-promote path is currently
  blocked on real output.
- **Guard-positive target — `app/services/report_service.py`.** Its real imports (via AST) are
  `{app.core, app.handlers}`. The guard-positive scenario feeds a `deterministic_single` finding
  whose claimed import set **drops** `app.handlers` (a #494-shape extractor bug) with a *lying*
  `evidence` field; the shipped `guard.apply_cross_derivation_guard` + `imports_via_ast` must
  downgrade it to `ambiguous` + `possible_extractor_bug` (catching it via the independent AST, not
  the evidence), while the correct finding passes. **Live result: PASS.**
- **Gate genuine-downgrade (instability) — UN-PLANTABLE.** A "near-universal-but-unstable" finding
  that the gate should downgrade *because the model disagrees with itself across re-runs* cannot be
  planted in static fixture code — instability is LLM non-determinism, not a property of the source.
  This path stays unit-test-only (`tests/test_architecture_review_gate.py`) by nature; the dogfood
  states this rather than faking it.
