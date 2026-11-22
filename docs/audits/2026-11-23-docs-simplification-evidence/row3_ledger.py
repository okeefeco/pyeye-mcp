"""Row 3 evidence: every uncovered.json revision on a ref, as per-ID adds and removals.

Usage (in a checkout of okeefeco/pyeye-mcp): python row3_ledger.py 55e35597 > row3_ledger.json
"""

import json
import subprocess
import sys

ref = sys.argv[1]
TOP = subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
).stdout.strip()


def git(*a):
    return subprocess.run(
        ["git", "-C", TOP, *a], capture_output=True, text=True, check=True
    ).stdout  # paths from the repo root


commits = git(
    "log", "--reverse", "--format=%h|%ad|%s", "--date=short", ref, "--", "docs/facts/uncovered.json"
).splitlines()
prev = {"baseline": set(), "new": set()}
first_seen_commit, events = {}, []
for row in commits:
    h, date, subject = row.split("|", 2)
    d = json.loads(git("show", f"{h}:docs/facts/uncovered.json"))
    cur = {"baseline": set(d.get("baseline", [])), "new": {e["fact_id"] for e in d.get("new", [])}}
    for section in ("baseline", "new"):
        added, gone = cur[section] - prev[section], prev[section] - cur[section]
        for f in added:
            first_seen_commit.setdefault((section, f), (h, date))
        if added or gone:
            events.append(
                {
                    "commit": h,
                    "date": date,
                    "subject": subject[:100],
                    "section": section,
                    "added": sorted(added),
                    "resolved": sorted(gone),
                }
            )
    prev, last = cur, d
open_new = [
    {
        "fact_id": e["fact_id"],
        "first_seen": e.get("first_seen"),
        "entered": first_seen_commit.get(("new", e["fact_id"])),
    }
    for e in last.get("new", [])
]
print(
    json.dumps(
        {
            "ref": ref,
            "revisions": len(commits),
            "baseline_start": len(
                json.loads(git("show", f"{commits[0].split('|')[0]}:docs/facts/uncovered.json"))[
                    "baseline"
                ]
            ),
            "baseline_now": len(prev["baseline"]),
            "new_now": len(prev["new"]),
            "baseline_resolved_total": sum(
                len(e["resolved"]) for e in events if e["section"] == "baseline"
            ),
            "baseline_added_after_start": sum(
                len(e["added"]) for e in events[1:] if e["section"] == "baseline"
            ),
            "new_added_total": sum(len(e["added"]) for e in events if e["section"] == "new"),
            "new_resolved_total": sum(len(e["resolved"]) for e in events if e["section"] == "new"),
            "events": events,
            "open_new": open_new,
            "open_baseline": sorted(prev["baseline"]),
        },
        indent=2,
        sort_keys=True,
    )
)
