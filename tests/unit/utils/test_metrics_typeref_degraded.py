"""The typeref degraded-path counts are visible in the performance metrics (#331).

``typeref`` counts which annotation shapes fall back to ``{raw: ...}``. The
counts are reported by ``get_performance_report`` and ``export_prometheus``
as a snapshot: reading them never resets them.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from prometheus_client.parser import text_string_to_metric_families

from pyeye.mcp.operations import typeref
from pyeye.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def _clean_counts() -> Iterator[None]:
    typeref.degraded_counts.clear()
    yield
    typeref.degraded_counts.clear()


def _bump(*kinds: str) -> None:
    for kind in kinds:
        typeref._bump_degraded(kind)


def _degraded_family(text: str):  # type: ignore[no-untyped-def]
    families = [
        f for f in text_string_to_metric_families(text) if f.name == "pyeye_typeref_degraded"
    ]
    assert len(families) == 1
    return families[0]


def test_the_report_has_the_degraded_counts_by_kind() -> None:
    _bump("Callable", "Callable", "Literal")

    report = MetricsCollector().get_performance_report()

    assert report["typeref_degraded"] == {"Callable": 2, "Literal": 1}


def test_reading_the_report_does_not_reset_the_counts() -> None:
    _bump("Annotated")
    collector = MetricsCollector()

    collector.get_performance_report()
    collector.export_prometheus()

    assert collector.get_performance_report()["typeref_degraded"] == {"Annotated": 1}
    assert typeref.degraded_counts == {"Annotated": 1}


def test_the_report_section_is_a_copy() -> None:
    _bump("Call")

    MetricsCollector().get_performance_report()["typeref_degraded"]["Call"] = 99

    assert typeref.degraded_counts == {"Call": 1}


def test_no_degraded_shapes_is_an_empty_section() -> None:
    assert MetricsCollector().get_performance_report()["typeref_degraded"] == {}


def test_prometheus_has_one_counter_family_labelled_by_kind() -> None:
    _bump("Callable", "Callable", 'od"d\\kind')

    family = _degraded_family(MetricsCollector().export_prometheus())

    assert family.type == "counter"
    assert {s.labels["kind"]: s.value for s in family.samples} == {
        "Callable": 2.0,
        'od"d\\kind': 1.0,
    }
    assert {s.name for s in family.samples} == {"pyeye_typeref_degraded_total"}


def test_prometheus_family_without_counts_has_no_samples() -> None:
    export = MetricsCollector().export_prometheus()

    assert _degraded_family(export).samples == []
    assert export.endswith("\n") and not export.endswith("\n\n")


def test_the_snapshot_accessor_copies_without_resetting() -> None:
    _bump("Literal")

    snapshot = typeref.degraded_counts_snapshot()
    snapshot["Literal"] = 5

    assert typeref.degraded_counts_snapshot() == {"Literal": 1}
    assert typeref.get_and_reset_degraded_counts() == {"Literal": 1}
    assert typeref.degraded_counts_snapshot() == {}
