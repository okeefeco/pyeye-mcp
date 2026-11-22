"""Row 1 evidence: the removed-name rule as it runs at a pinned commit, and a plain-word variant.

Usage: python row1_removed.py <checkout root> > row1_removed.json
(imports that checkout's own pyeye; REPORT.md ran it on a checkout of 55e35597)
"""

import collections
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "src"))
from pyeye.docs_facts import docs, registry, removed  # noqa: E402
from pyeye.docs_facts.cli import _LIVE_KINDS, CHANGELOG  # noqa: E402

facts = registry.build(root)
entries = removed.load(root)
live = removed.live_names(facts)
major = removed.current_major((root / CHANGELOG).read_text(encoding="utf-8"))
generated = set(docs.REFERENCE_PAGES)
pages = [
    (p, e) for p, e in docs.registered_files(root) if p not in generated and e.kind in _LIVE_KINDS
]


def scan(ents):
    out = []
    for path, _e in pages:
        out += removed.mentions(path, (root / path).read_text(encoding="utf-8"), ents, live, major)
    return out


real = scan(entries)
as_word = scan([dataclasses.replace(e, match="word") for e in entries])
by_level = collections.Counter(e.match for e in entries)
level_of = {e.name: e.match for e in entries}
allow = {
    p: list(e.allow.get(removed.RULE_ID, ())) for p, e in pages if e.allow.get(removed.RULE_ID)
}


def summary(ms):
    return {
        "mentions": len(ms),
        "marked_pass": sum(not m.fails for m in ms),
        "failing": sum(m.fails for m in ms),
        "by_level": dict(collections.Counter(level_of[m.name] for m in ms)),
    }


extra = sorted(
    {(m.path, m.line, m.name, level_of[m.name], m.marked) for m in as_word}
    - {(m.path, m.line, m.name, level_of[m.name], m.marked) for m in real}
)
print(
    json.dumps(
        {
            "commit": subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()[:8],
            "live_pages_scanned": len(pages),
            "removed_entries": len(entries),
            "entries_by_match": dict(by_level),
            "entries_live_again_not_scanned": sorted(e.name for e in entries if e.name in live),
            "current_major": major,
            "real_rule": summary(real),
            "real_mentions": [
                (m.path, m.line, m.name, level_of[m.name], "marked" if m.marked else "UNMARKED")
                for m in real
            ],
            "allow_lists": {
                "pages": len(allow),
                "entries": sum(map(len, allow.values())),
                "per_page": allow,
            },
            "all_word_variant": summary(as_word),
            "only_under_all_word": [
                {"path": p, "line": line, "name": n, "real_level": lvl, "marked": mk}
                for p, line, n, lvl, mk in extra
            ],
        },
        indent=2,
        sort_keys=True,
    )
)
