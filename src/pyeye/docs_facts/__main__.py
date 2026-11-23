"""``python -m pyeye.docs_facts generate|check|changed|architecture``: docs-facts on any repository (#1162).

The shipped entry point, so a skill can run docs-facts on a user's repository
from the plugin's environment, as it runs ``python -m pyeye.decisions`` (#1093)::

    uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_runtime.py" python -m pyeye.docs_facts check

The repository is the working directory unless ``--root`` names one. Its config
(``[tool.pyeye.docs_facts]`` or ``.pyeye.json``) says what to check; with none,
the command says there's nothing to check. ``architecture plan|validate|report``
is the architecture review engine (#1178). pyeye's own ``scripts/docs_facts.py``
runs the same :func:`~.cli.main` with this repository as its root.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
