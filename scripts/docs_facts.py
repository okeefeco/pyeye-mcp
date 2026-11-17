"""Keep the docs' facts equal to the code's (#824): ``generate`` or ``check``.

    uv run python scripts/docs_facts.py generate   # rewrite blocks, pages, snapshot
    uv run python scripts/docs_facts.py check      # fail if anything is stale

The logic lives in ``pyeye.docs_facts``; see ``docs/reference/README.md``.
"""

import sys
from pathlib import Path

from pyeye.docs_facts.cli import main

if __name__ == "__main__":
    sys.exit(main(root=Path(__file__).parent.parent))
