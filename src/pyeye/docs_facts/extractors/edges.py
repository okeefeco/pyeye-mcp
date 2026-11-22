"""Edge facts: every edge the matrix knows, its status, kinds and ceiling.

Read from the source of the edge registry, :mod:`pyeye.mcp.operations.edges`,
the one table ``expand``, ``trace``, ``inspect`` and ``outline`` all consult. It
is never imported here (#1098, C19); the server's tool descriptions render the
same facts from the imported registry through :func:`registry_facts`.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import static
from ..facts import Bindable, Fact, code, code_list, table, text, view

PREFIXES = ("edge", "edges", "ceiling", "ceilings", "determinism")

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


_REGISTRY = "pyeye.mcp.operations.edges"


class _StaticRegistry:
    """The edge registry's names :func:`registry_facts` reads, from the source (#1098, C19).

    Constants are folded (:mod:`..static`); ``EDGE_RESOLVERS`` is its literal
    keys (the resolvers are never touched); :meth:`edge_status` is the
    registry's classification over the same declared sets.
    """

    def __init__(self, root: Path) -> None:
        self._source = static.Module(root, _REGISTRY)
        self.EDGE_RESOLVERS = dict.fromkeys(static.dict_keys(root, _REGISTRY, "EDGE_RESOLVERS"))

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._source, name)

    def edge_status(self, edge: str) -> str:
        """``edges.edge_status``, over the declared sets."""
        if edge in self._source._IMPLEMENTED_EDGES:
            return str(self._source.STATUS_IMPLEMENTED)
        if edge in self._source._NOT_YET_IMPLEMENTED_EDGES:
            return str(self._source.STATUS_NOT_YET_IMPLEMENTED)
        if edge in self._source._DEFERRED_REFERENCE_BACKEND_EDGES:
            return str(self._source.STATUS_DEFERRED_REFERENCE_BACKEND)
        return str(self._source.STATUS_UNKNOWN_EDGE)


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per edge and per ceiling, plus the group views and ``inspect``'s unmeasured set.

    Read from the source, never imported (#1098, C19).
    """
    yield from registry_facts(_StaticRegistry(root))
    unmeasured = inspect_unmeasured(root)
    yield Fact("edges.inspect_unmeasured", unmeasured, code_list(unmeasured))


def registry_facts(reg: Any) -> Iterator[Bindable]:
    """The edge and ceiling facts, from *reg*: the static registry, or the live one.

    ``extract`` passes the registry read from the source; the server's tool
    descriptions pass the imported module (:func:`..describe.live_facts`, #1098 Q1).
    """
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
        if name in reg.EDGE_DETERMINISM:
            value["determinism"] = reg.EDGE_DETERMINISM[name]
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
                code(fact.value["determinism"]),
            ]
        )
    yield view("edges.table", shown, table(["Edge", "Applies to", "Ceiling", "Determinism"], rows))

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

    # Determinism tiers (#452), in the order they're defined: most to least stable.
    tiers = []
    for tier, meaning in reg.DETERMINISM_MEANINGS.items():
        members = [f.id[5:] for f in shown if f.value["determinism"] == tier]
        tiers.append(
            Fact(f"determinism.{tier}", {"meaning": meaning, "edges": members}, text(meaning))
        )
    yield from tiers
    yield view(
        "determinism.table",
        tiers,
        table(
            ["Determinism", "Edges", "Guarantee"],
            [
                [code(t.id[12:]), ", ".join(code(e) for e in t.value["edges"]), t.markdown]
                for t in tiers
            ],
        ),
    )
