#!/usr/bin/env python3
"""Post-commit nudge: flag commits that touch a contract surface.

Prototype for the decision-log handoff gap (see docs/decisions/DECISIONS.md):
the decision-log trigger is meant to fire at the commit checkpoint, but relies
on the agent remembering to surface it. This makes the signal *deterministic* —
git runs it on every commit, it inspects the just-committed diff, and prints a
ONE-LINE nudge **only** when it detects a contract surface. Trivial commits stay
silent (so it doesn't train you to ignore it).

It NEVER blocks and never writes anything — it only prints a suggestion. The
judgement of whether to actually log a decision stays with the human/agent.

What it detects (high-precision, low-noise):
  * public signature changes  — added/removed/changed `def`/`async def`/`class`
    whose name is public or a dunder (e.g. `__init__`), in src .py files
    (tests/docs excluded; private `_helper` names ignored).
  * new/changed config knobs   — added lines introducing a `PYEYE_*` env var.
  * output-shape contracts      — a dict key added to the return value of a
    function whose name implies an output contract (report/schema/export/
    stats/serialize/to_dict/to_json/metrics/summary).

Residual limitation (honest): output-shape detection is scoped to recognised
output-function names via the diff hunk header; a contract dict built in a
helper with an unrecognised name is still missed. It is a high-precision nudge,
not a complete gate — the judgement of whether to log stays human.

Usage:
    decision_log_nudge.py [<commit-ish>]   # defaults to HEAD
"""

from __future__ import annotations

import re
import subprocess
import sys

# A diff body line (+/-) declaring a def/class. Group 1 = the name.
_SIGNATURE = re.compile(r"^[+-]\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
# A def/class name anywhere (used to read the enclosing-scope from hunk headers).
_DEF_IN_CONTEXT = re.compile(r"(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
# An added line that introduces a PYEYE_* environment/config key.
_ENV_KEY = re.compile(r"^\+.*\b(PYEYE_[A-Z0-9_]+)\b")
# An added line introducing a quoted dict key (group 1 = key).
_DICT_KEY = re.compile(r"""^\+.*["']([A-Za-z_][\w.]*)["']\s*:""")
# Function names that imply an output/serialisation contract.
_OUTPUT_FUNC = re.compile(
    r"(report|schema|export|stats|serialize|serialise|to_dict|to_json|metrics|summary)",
    re.IGNORECASE,
)
# Paths whose changes should NOT trigger a nudge (per the decision-log skill:
# new test cases / docs are not contract surfaces).
_EXCLUDED_PREFIXES = ("tests/", "docs/")


def _is_contract_name(name: str) -> bool:
    """True for public names and dunders; False for private helpers.

    ``resolve`` / ``ProjectCache`` -> True. ``__init__`` (constructor contract)
    -> True. ``_helper`` / ``__mangled`` -> False.
    """
    if name.startswith("__") and name.endswith("__"):
        return True
    return not name.startswith("_")


def _commit_diff(ref: str) -> str:
    """Return the diff for *ref* with the commit message suppressed."""
    return subprocess.run(
        ["git", "show", "--format=", ref],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def scan(diff: str) -> dict[str, set[str]]:
    """Return detected contract surfaces grouped by kind.

    Tracks the current file via ``+++ b/<path>`` headers so excluded paths
    (tests/docs) contribute nothing.
    """
    signatures: set[str] = set()
    env_keys: set[str] = set()
    output_keys: set[str] = set()
    current_excluded = False
    enclosing: str | None = None  # nearest def/class name (from hunk headers)

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[len("+++ b/") :]
            current_excluded = path.startswith(_EXCLUDED_PREFIXES) or not path.endswith(".py")
            enclosing = None
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            # The hunk header's trailing context carries the enclosing def/class.
            ctx = line.split("@@")[-1]
            m = _DEF_IN_CONTEXT.search(ctx)
            enclosing = m.group(1) if m else None
            continue
        if current_excluded:
            continue
        sig = _SIGNATURE.match(line)
        if sig and _is_contract_name(sig.group(1)):
            signatures.add(sig.group(1))
        env = _ENV_KEY.match(line)
        if env:
            env_keys.add(env.group(1))
        key = _DICT_KEY.match(line)
        if key and enclosing and _OUTPUT_FUNC.search(enclosing):
            output_keys.add(key.group(1))

    found: dict[str, set[str]] = {}
    if signatures:
        found["public signature"] = signatures
    if env_keys:
        found["config/env key"] = env_keys
    if output_keys:
        found["output-shape key"] = output_keys
    return found


def main(argv: list[str]) -> int:
    """Scan the committed diff and print a one-line decision-log nudge.

    Always returns 0 so the post-commit hook never blocks a commit, and
    stays silent unless the diff touches a recognised contract surface.
    """
    ref = argv[1] if len(argv) > 1 else "HEAD"
    try:
        diff = _commit_diff(ref)
    except subprocess.CalledProcessError:
        return 0  # never block a commit over our own failure

    found = scan(diff)
    if not found:
        return 0  # silent on trivial commits

    parts = [f"{kind} ({', '.join(sorted(names))})" for kind, names in found.items()]
    print(
        f"decision-log: this commit touches a contract surface — {'; '.join(parts)}. "
        f"Consider proposing an entry (skill: decision-log). This is a suggestion, not a gate."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
