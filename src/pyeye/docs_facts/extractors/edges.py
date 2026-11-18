"""Edge facts: every edge the matrix knows, its status, kinds and ceiling.

Read from the edge registry in :mod:`pyeye.mcp.operations.edges`, the one table
``expand``, ``trace``, ``inspect`` and ``outline`` all consult.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from ..facts import Bindable, Fact, code, code_list, table, text, view

PREFIXES = ("edge", "edges", "ceiling", "ceilings")

#: The response linter holds the set of edges ``inspect``'s ``edge_counts`` must
#: never show; the live-response check and the docs rule read the same set (#396).
LINTER = "tests/conformance/response_linter.py"
_UNMEASURED = "_PHASE4_UNMEASURED_EDGES"


def inspect_unmeasured(root: Path) -> list[str]:
    """The edges ``inspect`` doesn't measure, read from the linter's source.

    Parsed, not imported: ``tests`` isn't an installed package.

    Raises:
        ValueError: If the linter no longer assigns the set as a literal.
    """
    tree = ast.parse((root / LINTER).read_text(encoding="utf-8"))
    for node in tree.body:
        target: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        value = getattr(node, "value", None)
        if not (isinstance(target, ast.Name) and target.id == _UNMEASURED):
            continue
        if isinstance(value, ast.Call) and len(value.args) == 1:
            value = value.args[0]
        try:
            return sorted(ast.literal_eval(value))  # type: ignore[arg-type]
        except ValueError:
            break
    raise ValueError(f"{LINTER} no longer assigns {_UNMEASURED} as a literal set")


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per edge and per ceiling, plus the group views and ``inspect``'s unmeasured set."""
    yield from extract_code()
    unmeasured = inspect_unmeasured(root)
    yield Fact("edges.inspect_unmeasured", unmeasured, code_list(unmeasured))


def extract_code() -> Iterator[Bindable]:
    """The edge and ceiling facts, from the installed code alone; reads no file (#851).

    The server fills its tool descriptions from these while it loads
    (:mod:`pyeye.docs_facts.describe`), in every install: a wheel has no
    ``tests/`` and no repo, so a file read here would stop the server starting.
    """
    # Imported here, not at module level: ``pyeye.mcp``'s package ``__init__``
    # imports the server, which fills its tool descriptions from this extractor
    # while it loads (#827). A module-level import would make that a cycle.
    from ...mcp.operations import edges as reg

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
    # The edges that report ``unparseable_files`` (#729, #874), in resolver order.
    unparseable = [f for f in shown if f.id[5:] in reg.UNPARSEABLE_FILE_EDGES]
    yield view("edges.unparseable", unparseable, code_list(f.id[5:] for f in unparseable))

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
