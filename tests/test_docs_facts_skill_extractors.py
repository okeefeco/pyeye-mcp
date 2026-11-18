"""The review and duplication extractors read their facts from the code (#825)."""

from __future__ import annotations

from pathlib import Path

from pyeye import duplication as dup
from pyeye.architecture_review import ranking, taxonomy
from pyeye.docs_facts.extractors import duplication, review
from pyeye.docs_facts.facts import Fact, View, index

ROOT = Path(__file__).parent.parent


def _facts(extractor) -> dict:  # type: ignore[no-untyped-def]
    return index(extractor.extract(ROOT))


def test_every_seed_axis_is_a_fact_with_its_taxonomy() -> None:
    facts = _facts(review)
    for axis in taxonomy.SEED_AXES:
        fact = facts[f"review.axis.{axis}"]
        assert isinstance(fact, Fact)
        assert fact.value == {
            "description": taxonomy.AXIS_DESCRIPTIONS[axis],
            "facets": list(taxonomy.AXIS_FACETS[axis]),
            "stakes_bucket": taxonomy.AXIS_STAKES_BUCKET[axis],
            "stakes_prior": taxonomy.AXIS_STAKES_PRIOR[axis],
        }
    group = facts["review.axes"]
    assert isinstance(group, View)
    assert [m.rsplit(".", 1)[1] for m in group.members] == list(taxonomy.SEED_AXES)


def test_grades_are_the_rankers_vocabulary() -> None:
    facts = _facts(review)
    grades = {i.rsplit(".", 1)[1] for i in facts if i.startswith("review.grade.")}
    assert grades == set(ranking._TIER)
    assert {"mechanical_fact", "deterministic_single", "ambiguous", "no_signal"} == grades


def test_tables_render_one_row_per_axis() -> None:
    facts = _facts(review)
    for view_id in ("review.axes.table", "review.facets.table"):
        rows = facts[view_id].markdown.splitlines()[2:]
        assert len(rows) == len(taxonomy.SEED_AXES), view_id


def test_buckets_view_is_the_default_bucket_map_in_rank_order() -> None:
    """``review.buckets`` renders the ranker's default map, highest stakes first (#830)."""
    facts = _facts(review)
    group = facts["review.buckets"]
    assert isinstance(group, View)
    assert [m.rsplit(".", 1)[1] for m in group.members] == list(taxonomy.SEED_AXES)
    parts = group.markdown.split(" > ")
    order = sorted(taxonomy._BUCKET_ORDER, key=taxonomy._BUCKET_ORDER.__getitem__, reverse=True)
    assert [part.split(":", 1)[0] for part in parts] == [f"`{b}`" for b in order]
    for bucket, part in zip(order, parts, strict=True):
        axes = [a for a in taxonomy.SEED_AXES if taxonomy.AXIS_STAKES_BUCKET[a] == bucket]
        assert part == f"`{bucket}`: " + ", ".join(f"`{a}`" for a in axes)


def test_duplication_vocabulary_is_the_parsers() -> None:
    facts = _facts(duplication)
    commands = {i.rsplit(".", 1)[1] for i in facts if i.startswith("duplication.command.")}
    flags = {i.split(".", 2)[2] for i in facts if i.startswith("duplication.flag.")}
    assert commands == {"review", "dismiss"}
    assert {"root", "min-tokens", "reason", "review-after", "json"} <= flags
    assert "help" not in flags
    reason = facts["duplication.flag.reason"]
    assert isinstance(reason, Fact) and reason.value == {"commands": ["dismiss"]}


def test_duplication_defaults_and_reasons_are_the_codes() -> None:
    facts = _facts(duplication)
    assert facts["duplication.default.min_tokens"].value == dup.DEFAULT_MIN_TOKENS
    assert facts["duplication.default.max_occurrences"].value == dup.DEFAULT_MAX_OCCURRENCES
    assert facts["duplication.filter.function_line_share"].markdown == "50 %"
    assert facts["duplication.reasons"].markdown == ", ".join(
        f"`{r}`" for r in dup.DISMISSAL_REASONS
    )
