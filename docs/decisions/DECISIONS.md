# Decision Log

Contract- or invariant-significant, friction-driven decisions. Each one is a small, verifiable fact: **Friction · Decision · Anchor** (stable references) **· Applies-to** (every governed site; recommended) **· Verify** (checkable, or honestly labelled).

**One file per decision** lives in [`entries/`](entries/), named `YYYY-MM-DD-<issue>-<slug>.md`. There is no committed index (#679). List and filter the entries from their front matter instead:

```bash
python scripts/decisions.py index                     # every entry, newest first
python scripts/decisions.py index --active            # hide superseded entries
python scripts/decisions.py index --symbol resolve_handle
python scripts/decisions.py index --issue 626
python scripts/decisions.py check                     # validate (also runs in CI)
```

Read the index first, then open the one to three entries that matter. An entry's `status` is `active`, `amended` or `superseded`. Its `amends` / `supersedes` / `amended_by` / `superseded_by` front matter links to the related entry files.

New entries are written with the `decision-log` skill (`skills/decision-log/SKILL.md`). This file is a static header and should almost never change.
