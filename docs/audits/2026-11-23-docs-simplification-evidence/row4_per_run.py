"""Row 4 evidence, per run: findings, needs_decision, categories, anchor kinds and rule IDs.

Usage (from this directory): python row4_per_run.py [findings-copy] > row4_per_run.json
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
#: Each run directory, labelled by the PRs (or check) it fed.
LABELS = {
    "v2.2.0-prerelease": "v2.2.0 pre-release check (#1018 line)",
    "830-readme-contrib-skills": "#866 README + #876 DOCUMENTATION/CONTRIBUTING + #881 skills",
    "830-guides-api-architecture": "#877 api/architecture + #880 guides",
    "830-history-pages": "#869 history pages",
}
top = Path(sys.argv[1] if len(sys.argv) > 1 else "findings-copy")
out, all_rules = {}, collections.Counter()
for run, label in LABELS.items():
    cat, kind, rules, n, nd = (
        collections.Counter(),
        collections.Counter(),
        collections.Counter(),
        0,
        0,
    )
    for f in sorted((top / run).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("findings", [])
        for x in items:
            if not (
                isinstance(x, dict)
                and x.get("category") in CATEGORIES
                and isinstance(x.get("anchor"), dict)
            ):
                continue
            n += 1
            nd += bool(x.get("needs_decision"))
            k = x["anchor"].get("kind")
            cat[x["category"]] += 1
            kind[k] += 1
            if k in ("claims_rule", "audience_rule", "style_rule") and x["anchor"].get("id"):
                rules[x["anchor"]["id"]] += 1
    all_rules.update(rules)
    out[label] = {
        "findings": n,
        "needs_decision": nd,
        "by_category": {c: cat.get(c, 0) for c in CATEGORIES},
        "by_anchor_kind": {k: kind.get(k, 0) for k in ANCHOR_KINDS},
        "rule_ids": dict(rules.most_common()),
    }
out["_all_rule_ids_used"] = dict(all_rules.most_common())
print(json.dumps(out, indent=2, sort_keys=True))
