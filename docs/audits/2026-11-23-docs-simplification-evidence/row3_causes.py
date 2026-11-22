"""Row 3 evidence: why each uncovered.json entry left, and the fact counts at three points.

Usage (from a checkout of okeefeco/pyeye-mcp that has the pinned commits, with this
directory's row3_ledger.json): python row3_causes.py row3_ledger.json > row3_causes.json

A resolved ID still present in that commit's docs/facts/facts.json counts as
covered by prose (the fact still exists); one that isn't counts as its fact removed.
"""

import collections
import json
import subprocess
import sys

#: The three points REPORT.md row 3 cites, pinned.
POINTS = {
    "ledger created": "77584a66",
    "new section started": "088e4f9b",
    "pinned main": "55e35597",
}


def facts_at(commit):
    text = subprocess.run(
        ["git", "show", f"{commit}:docs/facts/facts.json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(text)["facts"]


with open(sys.argv[1], encoding="utf-8") as handle:
    ledger = json.load(handle)
detail, causes, cache = [], collections.Counter(), {}
for event in ledger["events"]:
    if not event["resolved"]:
        continue
    facts = cache.setdefault(event["commit"], facts_at(event["commit"]))
    for fact_id in event["resolved"]:
        cause = "covered (fact still exists)" if fact_id in facts else "fact removed"
        detail.append([event["commit"], event["section"], fact_id, cause])
        causes[f'{event["section"]}: {cause}'] += 1
print(
    json.dumps(
        {
            "by_section_and_cause": dict(causes),
            "facts_count": {
                label: {"commit": c, "facts": len(facts_at(c))} for label, c in POINTS.items()
            },
            "detail": detail,
        },
        indent=2,
        sort_keys=True,
    )
)
