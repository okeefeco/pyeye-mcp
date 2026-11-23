"""Give a temporary repository a docs-facts config (#1107).

docs-facts reads every repository's setup from its config, pyeye's included;
there is no built-in one to patch. A test that needs a registry writes it here,
as ``.pyeye.json``'s ``docs_facts`` section.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pyeye.docs_facts.docs import DocEntry


def doc_table(entry: DocEntry) -> dict[str, Any]:
    """*entry* as a config ``docs`` table."""
    table: dict[str, Any] = {"path": entry.path, "audience": entry.audience, "kind": entry.kind}
    if entry.allow:
        table["allow"] = {rule: list(messages) for rule, messages in entry.allow.items()}
    if entry.covers:
        table["covers"] = list(entry.covers)
    if entry.site is not None:
        table["site"] = entry.site
    return table


def write_config(
    root: Path, docs: Iterable[DocEntry], changelog: str | None = "CHANGELOG.md", **keys: Any
) -> Path:
    """Write *root*'s ``.pyeye.json`` with *docs*, *changelog* and any other *keys*."""
    section: dict[str, Any] = {"docs": [doc_table(e) for e in docs], **keys}
    if changelog is not None:
        section["changelog"] = changelog
    (root / ".pyeye.json").write_text(json.dumps({"docs_facts": section}), encoding="utf-8")
    return root
