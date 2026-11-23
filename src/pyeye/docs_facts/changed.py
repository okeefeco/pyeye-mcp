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
from .facts import Bindable, View, memberships
from .ledger import expand


@dataclass
class Changes:
    """Fact IDs by kind of change, and the pages binding each one.

    Attributes:
        added: Facts in the head snapshot only.
        changed: Facts whose value differs.
        removed: Facts in the base snapshot only.
        grown: Views that gained a member. A new member of a bound view counts
            as covered at once, so this is what sends the view's pages to a
            change-triggered review (D6, #1108).
        shrunk: Views that lost a member, from the base snapshot's view
            memberships (#1114).
        pages: Fact or view ID -> registered pages with a block showing it. A
            removed fact maps to the pages of the views that held it.
    """

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    grown: list[str] = field(default_factory=list)
    shrunk: list[str] = field(default_factory=list)
    pages: dict[str, list[str]] = field(default_factory=dict)


def base_snapshot(
    root: Path, base: str, snapshot_path: str, section: str = "facts"
) -> dict[str, Any] | None:
    """A section of the snapshot at git revision *base*, or None if it has no such file.

    *section* is ``facts`` (each fact's value) or ``views`` (each view's members,
    #1114); a snapshot from before the views were kept has none, so it reads empty.
    """
    result = subprocess.run(  # nosec B603 B607 - fixed git command, no shell
        ["git", "show", f"{base}:{snapshot_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    found: dict[str, Any] = data["facts"] if section == "facts" else data.get(section, {})
    return found


def base_views(root: Path, base: str, snapshot_path: str) -> dict[str, list[str]]:
    """The snapshot's view memberships at git revision *base* (#1114).

    Empty when *base* has no such file, or predates the memberships being kept:
    a loss can't be seen then, only a gain.
    """
    return base_snapshot(root, base, snapshot_path, "views") or {}


def bound_pages(
    root: Path, facts: Mapping[str, Bindable], entries: tuple[docs.DocEntry, ...] | None = None
) -> dict[str, list[str]]:
    """Fact or view ID -> the registered pages whose blocks show it.

    A view shows its members, so each member maps to the view's pages too.
    *entries* is the doc registry (default: *root*'s own, :func:`~.docs.for_repo`).
    """
    found: dict[str, set[str]] = {}
    for path, _entry in docs.registered_files(root, entries):
        blocks, _problems = binding.parse((root / path).read_text(encoding="utf-8"))
        for fact_id in expand((b.fact_id for b in blocks), facts):
            found.setdefault(fact_id, set()).add(path)
        for block in blocks:  # the block's own ID: a view, or a removed fact
            if block.fact_id not in facts or isinstance(facts[block.fact_id], View):
                found.setdefault(block.fact_id, set()).add(path)
    return {i: sorted(p) for i, p in sorted(found.items())}


def diff(
    base: Mapping[str, Any],
    head: Mapping[str, Any],
    pages: Mapping[str, list[str]],
    facts: Mapping[str, Bindable] | None = None,
    *,
    base_views: Mapping[str, list[str]] | None = None,
    head_views: Mapping[str, list[str]] | None = None,
) -> Changes:
    """Compare two snapshots; *pages* is :func:`bound_pages` for the head.

    The views come from each side's snapshot (#1114): *head_views* (default:
    from *facts*, the head's facts) and *base_views* (default: none). A view
    the base doesn't record gained the members that were added.
    """
    added = set(head) - set(base)
    heads = dict(head_views) if head_views is not None else memberships(facts or {})
    bases = dict(base_views or {})
    grown = {
        v
        for v, members in heads.items()
        if (set(members) - set(bases[v]) if v in bases else added & set(members))
    }
    shrunk = {v for v, members in bases.items() if set(members) - set(heads.get(v, ()))}
    changes = Changes(
        added=sorted(added),
        changed=sorted(i for i in set(head) & set(base) if head[i] != base[i]),
        removed=sorted(set(base) - set(head)),
        grown=sorted(grown),
        shrunk=sorted(shrunk),
    )
    for fact_id in (*changes.added, *changes.changed, *changes.removed, *grown, *shrunk):
        if fact_id in pages:
            changes.pages[fact_id] = list(pages[fact_id])
    for fact_id in changes.removed:  # a gone member: the pages of the views that held it
        held = {p for v in shrunk if fact_id in bases[v] for p in pages.get(v, ())}
        if held:
            changes.pages[fact_id] = sorted(held | set(changes.pages.get(fact_id, ())))
    return changes


def summary(changes: Changes, base: str) -> str:
    """Markdown for the CI job summary."""
    lines = [f"### Docs facts changed against `{base}`", ""]
    if not (changes.added or changes.changed or changes.removed or changes.grown or changes.shrunk):
        return "\n".join([*lines, "No fact changed.", ""])
    for title, ids in (
        ("Added", changes.added),
        ("Changed", changes.changed),
        ("Removed", changes.removed),
        ("Views with a new member", changes.grown),
        ("Views that lost a member", changes.shrunk),
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
