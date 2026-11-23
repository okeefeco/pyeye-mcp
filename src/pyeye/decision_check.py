"""``decisions check --resolve``: every Anchor and Applies-to reference resolves (#1182).

:mod:`pyeye.decisions` checks an entry's format and stays standard-library
only, so CI can run it with a bare Python. This module adds the part that
needs pyeye: for each ACTIVE entry (superseded and amended ones are history),
the references in its ``**Anchor:**`` and ``**Applies-to:**`` fields are
classified from the project layout (:mod:`pyeye.decision_sites`) and checked:

- a ``handle`` must resolve through pyeye's resolver (a re-export to its
  definition site), and a repo path (one with a ``/``) must exist; otherwise
  it is a problem, reported as ``entry:line``;
- an ``external`` that doesn't resolve is listed, never a problem: a private
  name of a dependency can't be proved stale here;
- a ``short_form`` (``JediAnalyzer.find_importers``, a bare ``server.py``)
  is a problem in an entry dated on or after *short_forms_fail_from*, and
  counted otherwise, so the remainder stays visible on every run.

``decisions check --resolve`` runs it in CI only: resolving this repo's
references took 22.6 s, too slow for every commit (#1182's measurement).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .decision_sites import (
    Resolver,
    Site,
    external_top_level_names,
    pyeye_resolver,
    resolve_sites,
    top_level_names,
)

#: The fields whose references are checked.
_CHECKED = re.compile(r"^\*\*(Anchor|Applies-to):\*\*")
#: Where a field's value ends: the next ``**Field:**`` line or a heading.
_NEXT_FIELD = re.compile(r"^\*\*[A-Z][\w -]*:\*\*|^#")


@dataclass
class ResolveReport:
    """What ``check --resolve`` found.

    Attributes:
        problems: Failures, as ``entry:line: ...`` messages.
        unresolved_externals: External references that didn't resolve, listed
            on every run but never a failure.
        grandfathered_short_forms: Short forms in entries dated before the gate
            date (all of them, without one), counted on every run.
        checked_entries: How many active entries were read.
    """

    problems: list[str] = field(default_factory=list)
    unresolved_externals: list[str] = field(default_factory=list)
    grandfathered_short_forms: int = 0
    checked_entries: int = 0


def _fields(text: str) -> list[tuple[str, int, str]]:
    """``(field name, first line, value)`` for each checked field in an entry file."""
    lines = text.split("\n")
    found: list[tuple[str, int, str]] = []
    i = 0
    while i < len(lines):
        match = _CHECKED.match(lines[i])
        if not match:
            i += 1
            continue
        end = i + 1
        while end < len(lines) and not _NEXT_FIELD.match(lines[end]):
            end += 1
        found.append((match.group(1), i + 1, "\n".join(lines[i:end])))
        i = end
    return found


def _judge(
    report: ResolveReport, where: str, field_name: str, site: Site, root: Path, gated: bool
) -> None:
    """Record what *site*, a reference in *field_name* at *where*, means."""
    ref = site.ref
    short = ref.kind == "short_form" or (ref.kind == "path" and "/" not in ref.text)
    if short:
        if gated:
            report.problems.append(
                f"{where}: {field_name} `{ref.text}` is a short form; write it in full "
                "from its package (e.g. `pkg.mod.Name`)"
            )
        else:
            report.grandfathered_short_forms += 1
    elif ref.kind == "path":
        if not (root / ref.text).is_file():
            report.problems.append(f"{where}: {field_name} `{ref.text}` doesn't exist")
    elif ref.kind == "external":
        if site.handle is None and site.reason != "external":
            report.unresolved_externals.append(f"{where}: {field_name} `{ref.text}`")
    elif site.handle is None and site.reason != "external":
        report.problems.append(
            f"{where}: {field_name} `{ref.text}` doesn't resolve ({site.reason})"
        )


def resolve_check(
    entries: list[Any],
    entries_dir: Path,
    root: Path,
    short_forms_fail_from: str | None,
    *,
    resolver: Resolver | None = None,
) -> ResolveReport:
    """Check the Anchor and Applies-to references of every active entry (#1182).

    Args:
        entries: The loaded entries (:func:`pyeye.decisions.load`).
        entries_dir: Where their files are, for line numbers.
        root: The project root references are resolved in.
        short_forms_fail_from: A short form fails in an entry dated on or
            after this ``YYYY-MM-DD``; ``None``: none fails, all are counted.
        resolver: Resolves handles; pyeye's own over *root* by default.

    Returns:
        The report: problems, unresolved externals, and the counts.
    """
    report = ResolveReport()
    tops = top_level_names(root)
    external = external_top_level_names(root)
    resolve = resolver if resolver is not None else pyeye_resolver(root)
    for entry in entries:
        if entry.status != "active":
            continue
        report.checked_entries += 1
        gated = short_forms_fail_from is not None and entry.date >= short_forms_fail_from
        text = (entries_dir / entry.name).read_text(encoding="utf-8")
        for field_name, first_line, value in _fields(text):
            for site in resolve_sites(value, resolve, first_line, tops=tops, external=external):
                where = f"{entry.name}:{site.ref.line}"
                _judge(report, where, field_name, site, root, gated)
    return report
