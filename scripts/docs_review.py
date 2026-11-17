"""The internal ``/docs-review`` skill's mechanical steps (#829).

    uv run python scripts/docs_review.py scope --base origin/main     # change-triggered
    uv run python scripts/docs_review.py scope README.md docs/*.md    # on demand
    uv run python scripts/docs_review.py validate findings.json
    uv run python scripts/docs_review.py mark-fine README.md quick-start --date 2026-11-18
    uv run python scripts/docs_review.py dismiss findings.json --index 0 --reason fine --date …
    uv run python scripts/docs_review.py dismiss-uncovered env.X --reason "…" --date …
    uv run python scripts/docs_review.py move <key> <new fact ID>     # a renamed fact
    uv run python scripts/docs_review.py forget <key>                 # a removed fact

The logic lives in ``pyeye.docs_facts.review``; the skill is
``.claude/skills/docs-review/SKILL.md``. Nothing here applies a finding.
"""

import sys
from pathlib import Path

from pyeye.docs_facts.review import main

if __name__ == "__main__":
    sys.exit(main(root=Path(__file__).parent.parent))
