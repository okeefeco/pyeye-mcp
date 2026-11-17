"""Edge facts: every edge the matrix knows, its status, kinds and ceiling.

Read from the edge registry in :mod:`pyeye.mcp.operations.edges`, the one table
``expand``, ``trace``, ``inspect`` and ``outline`` all consult.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ...mcp.operations import edges as reg
from ..facts import Bindable, Fact, code, code_list, table, text, view

PREFIXES = ("edge", "edges", "ceiling", "ceilings")


def extract(root: Path) -> Iterator[Bindable]:  # noqa: ARG001 - reads the live registry
    """Yield a fact per edge and per ceiling, plus the group views."""
    implemented = sorted(reg.EDGE_RESOLVERS)
    known = (
        set(implemented) | reg._NOT_YET_IMPLEMENTED_EDGES | reg._DEFERRED_REFERENCE_BACKEND_EDGES
    )
    by_status: dict[str, list[Fact]] = {}
    for name in sorted(known):
        status = reg.edge_status(name)
        value: dict[str, object] = {"status": status}
        if name in reg.EDGE_APPLIES_TO:
            value["applies_to"] = sorted(reg.EDGE_APPLIES_TO[name])
        if name in reg.EDGE_CEILINGS:
            value["ceiling"] = reg.EDGE_CEILINGS[name]
        elif name in reg.EXACT_EDGES:
            value["ceiling"] = None
        fact = Fact(f"edge.{name}", value, code(name))
        by_status.setdefault(status, []).append(fact)
        yield fact

    # Display order for the implemented list follows the resolver table.
    resolver_order = {n: i for i, n in enumerate(reg.EDGE_RESOLVERS)}
    shown = sorted(
        by_status.get(reg.STATUS_IMPLEMENTED, []), key=lambda f: resolver_order[f.id[5:]]
    )
    yield view("edges.implemented", shown, code_list(f.id[5:] for f in shown))
    deferred = by_status.get(reg.STATUS_DEFERRED_REFERENCE_BACKEND, [])
    yield view("edges.deferred", deferred, code_list(f.id[5:] for f in deferred))

    rows = []
    for fact in shown:
        kinds = fact.value["applies_to"]
        ceiling = fact.value.get("ceiling")
        rows.append(
            [
                code(fact.id[5:]),
                ", ".join(kinds),
                code(ceiling) if ceiling else "exact",
            ]
        )
    yield view("edges.table", shown, table(["Edge", "Applies to", "Ceiling"], rows))

    ceilings = [
        Fact(f"ceiling.{cid}", {"meaning": meaning}, text(meaning))
        for cid, meaning in sorted(reg.CEILING_MEANINGS.items())
    ]
    yield from ceilings
    yield view(
        "ceilings.table",
        ceilings,
        table(["Ceiling", "Complete over"], [[code(c.id[8:]), c.markdown] for c in ceilings]),
    )
