"""The changed-fact list: the snapshot diffed against the merge base (§3, C4).

It is the scope of a change-triggered ``/docs-review`` (D6): which facts were
added, changed or removed in this PR, and which pages bind each one. CI prints
it as a job summary. It never fails: a removed fact still bound or named in
prose already fails ``check``, and a new uncovered fact is in the ledger.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - runs git with a fixed argument list
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import binding, docs
from .facts import Bindable
from .ledger import expand


@dataclass
class Changes:
    """Fact IDs by kind of change, and the pages binding each one.

    Attributes:
        added: Facts in the head snapshot only.
        changed: Facts whose value differs.
        removed: Facts in the base snapshot only.
        pages: Fact ID -> registered pages with a block showing it.
    """

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pages: dict[str, list[str]] = field(default_factory=dict)


def base_snapshot(root: Path, base: str, snapshot_path: str) -> dict[str, Any] | None:
    """The snapshot at git revision *base*, or None if it has none."""
    result = subprocess.run(  # nosec B603 B607 - fixed git command, no shell
        ["git", "show", f"{base}:{snapshot_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    facts: dict[str, Any] = json.loads(result.stdout)["facts"]
    return facts


def bound_pages(root: Path, facts: Mapping[str, Bindable]) -> dict[str, list[str]]:
    """Fact ID -> the registered pages whose blocks show it (a view shows its members)."""
    found: dict[str, set[str]] = {}
    for path, _entry in docs.registered_files(root):
        blocks, _problems = binding.parse((root / path).read_text(encoding="utf-8"))
        for fact_id in expand((b.fact_id for b in blocks), facts):
            found.setdefault(fact_id, set()).add(path)
        for block in blocks:  # a removed fact is no longer in *facts*; keep its ID
            if block.fact_id not in facts:
                found.setdefault(block.fact_id, set()).add(path)
    return {i: sorted(p) for i, p in sorted(found.items())}


def diff(
    base: Mapping[str, Any], head: Mapping[str, Any], pages: Mapping[str, list[str]]
) -> Changes:
    """Compare two snapshots; *pages* is :func:`bound_pages` for the head."""
    changes = Changes(
        added=sorted(set(head) - set(base)),
        changed=sorted(i for i in set(head) & set(base) if head[i] != base[i]),
        removed=sorted(set(base) - set(head)),
    )
    for fact_id in (*changes.added, *changes.changed, *changes.removed):
        if fact_id in pages:
            changes.pages[fact_id] = list(pages[fact_id])
    return changes


def summary(changes: Changes, base: str) -> str:
    """Markdown for the CI job summary."""
    lines = [f"### Docs facts changed against `{base}`", ""]
    if not (changes.added or changes.changed or changes.removed):
        return "\n".join([*lines, "No fact changed.", ""])
    for title, ids in (
        ("Added", changes.added),
        ("Changed", changes.changed),
        ("Removed", changes.removed),
    ):
        if not ids:
            continue
        lines.append(f"**{title}** ({len(ids)})")
        lines.append("")
        for fact_id in ids:
            where = changes.pages.get(fact_id)
            suffix = f" (bound in {', '.join(where)})" if where else ""
            lines.append(f"- `{fact_id}`{suffix}")
        lines.append("")
    lines.append("Pages binding a changed fact are the scope of a change-triggered `/docs-review`.")
    return "\n".join([*lines, ""])
