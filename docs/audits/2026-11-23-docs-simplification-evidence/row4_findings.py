"""Row 4 evidence: per-category and per-anchor-kind counts over the committed findings files.

Usage (from this directory): python row4_findings.py [findings-copy] > row4_findings.json

Reads every ``findings-copy/<run>/*.json``. Keeps only JSON lists of objects with a
closed /docs-review category and an anchor object. Groups by ``<run>``: one
directory per /docs-review run (see REPORT.md, row 4). The files are the review
sessions' own findings, copied byte for byte (``findings-copy.sha256``).
"""

import collections
import json
import sys
from pathlib import Path

CATEGORIES = (
    "fact_drift",
    "uncovered_fact",
    "code_contradiction",
    "honest_claims",
    "audience",
    "style",
)
ANCHOR_KINDS = ("fact", "symbol", "literal", "claims_rule", "audience_rule", "style_rule", "task")
top = Path(sys.argv[1] if len(sys.argv) > 1 else "findings-copy")
files = sorted(top.glob("*/*.json"))
by_cat, by_kind, by_session, skipped = (
    collections.Counter(),
    collections.Counter(),
    collections.defaultdict(collections.Counter),
    [],
)
cat_kind, page_level, needs_decision, n_files, total, rule_ids = (
    collections.Counter(),
    0,
    0,
    0,
    0,
    collections.Counter(),
)
for f in files:
    rel = f.relative_to(top).as_posix()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        skipped.append((rel, f"unreadable: {e}"))
        continue
    items = (
        data if isinstance(data, list) else data.get("findings") if isinstance(data, dict) else None
    )
    if not isinstance(items, list):
        skipped.append((rel, "not a findings list"))
        continue
    good = [
        x
        for x in items
        if isinstance(x, dict)
        and x.get("category") in CATEGORIES
        and isinstance(x.get("anchor"), dict)
    ]
    if not good:
        skipped.append((rel, "no review-shaped findings"))
        continue
    n_files += 1
    session = f.parent.name
    for x in good:
        total += 1
        k = x["anchor"].get("kind")
        by_cat[x["category"]] += 1
        by_kind[k] += 1
        cat_kind[(x["category"], k)] += 1
        by_session[session][x["category"]] += 1
        if x.get("section") == "*" or x.get("page_level"):
            page_level += 1
        if x.get("needs_decision"):
            needs_decision += 1
        if k in ("claims_rule", "audience_rule", "style_rule") and x["anchor"].get("id"):
            rule_ids[x["anchor"]["id"]] += 1
print(
    json.dumps(
        {
            "files_found": len(files),
            "files_used": n_files,
            "findings": total,
            "by_category": {c: by_cat.get(c, 0) for c in CATEGORIES},
            "by_anchor_kind": {k: by_kind.get(k, 0) for k in ANCHOR_KINDS}
            | {f"OTHER:{k}": n for k, n in by_kind.items() if k not in ANCHOR_KINDS},
            "category_x_anchor": {f"{c}/{k}": n for (c, k), n in sorted(cat_kind.items())},
            "page_level": page_level,
            "needs_decision": needs_decision,
            "rule_ids": dict(rule_ids.most_common()),
            "by_session": {s: dict(c) for s, c in sorted(by_session.items())},
            "skipped": skipped,
        },
        indent=2,
        sort_keys=True,
    )
)
