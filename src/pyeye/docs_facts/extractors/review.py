"""Architecture-review facts: the seed axes, their facets and the finding grades.

Read from :mod:`pyeye.architecture_review.taxonomy` (axes, descriptions, facets,
stakes) and :mod:`pyeye.architecture_review.ranking` (the grade vocabulary the
ranker tiers), the sources the ``architecture-review`` skill and its auditor
prompt document.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .. import static
from ..facts import Bindable, Fact, code, code_list, table, view

PREFIXES = ("review",)


def extract(root: Path) -> Iterator[Bindable]:
    """Yield a fact per axis and per grade, plus the views the skill binds.

    Read from the source, never imported (#1098, C19).
    """
    return _facts(
        static.Module(root, "pyeye.architecture_review.taxonomy"),
        static.Module(root, "pyeye.architecture_review.ranking"),
    )


def _facts(taxonomy: Any, ranking: Any) -> Iterator[Bindable]:
    axes: list[Fact] = []
    for name in taxonomy.SEED_AXES:
        fact = Fact(
            f"review.axis.{name}",
            {
                "description": taxonomy.AXIS_DESCRIPTIONS[name],
                "facets": list(taxonomy.AXIS_FACETS[name]),
                "stakes_bucket": taxonomy.AXIS_STAKES_BUCKET[name],
                "stakes_prior": taxonomy.AXIS_STAKES_PRIOR[name],
            },
            code(name),
        )
        axes.append(fact)
        yield fact
    yield view("review.axes", axes, code_list(taxonomy.SEED_AXES))
    yield view(
        "review.axes.table",
        axes,
        table(
            ["`axis` key", "What it covers"],
            [[f.markdown, f.value["description"]] for f in axes],
        ),
    )
    yield view(
        "review.facets.table",
        axes,
        table(
            ["`axis` key", "allowed `facet` values"],
            [[f.markdown, code_list(f.value["facets"])] for f in axes],
        ),
    )

    # The ranker's default bucket map, highest stakes first (#830): the order the
    # skill shows the human. A project can re-tier it; the skill says so.
    order = sorted(taxonomy._BUCKET_ORDER, key=taxonomy._BUCKET_ORDER.__getitem__, reverse=True)
    yield view(
        "review.buckets",
        axes,
        " > ".join(
            f"{code(bucket)}: "
            + ", ".join(f.markdown for f in axes if f.value["stakes_bucket"] == bucket)
            for bucket in order
        ),
    )

    grades = [Fact(f"review.grade.{g}", {"tier": t}, code(g)) for g, t in ranking._TIER.items()]
    yield from grades
    yield view("review.grades", grades, code_list(f.id.rsplit(".", 1)[1] for f in grades))
