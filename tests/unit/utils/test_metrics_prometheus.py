"""The Prometheus export is valid text format, checked by the real parser (#402).

``prometheus_client`` is a dev-only dependency: it parses the export here and
must never be imported by pyeye's runtime.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
from prometheus_client.parser import text_string_to_metric_families

from pyeye.metrics import MetricsCollector

_SRC = Path(__file__).parents[3] / "src" / "pyeye"


@pytest.fixture
def export() -> str:
    collector = MetricsCollector()
    for value in (10.0, 30.0):
        collector.metrics["resolve"].add_value(value)
    collector.metrics["expand"].add_value(5.0)
    collector.metrics['we"ird\\op'].add_value(1.0)
    collector.record_cache_hit()
    return collector.export_prometheus()


def _families(text: str) -> dict:
    families = list(text_string_to_metric_families(text))
    names = [f.name for f in families]
    # Every family is one contiguous group: a split family parses twice.
    assert len(names) == len(set(names)), names
    return {f.name: f for f in families}


def test_durations_are_a_summary_with_sum_and_count(export: str) -> None:
    family = _families(export)["pyeye_operation_duration_ms"]

    assert family.type == "summary"
    resolve = [s for s in family.samples if s.labels.get("operation") == "resolve"]
    quantiles = sorted(s.labels["quantile"] for s in resolve if "quantile" in s.labels)
    assert quantiles == ["0.5", "0.95", "0.99"]
    by_name = {s.name: s.value for s in resolve if "quantile" not in s.labels}
    assert by_name == {
        "pyeye_operation_duration_ms_sum": 40.0,
        "pyeye_operation_duration_ms_count": 2.0,
    }


def test_operation_count_is_its_own_counter_family(export: str) -> None:
    family = _families(export)["pyeye_operation_count"]

    assert family.type == "counter"
    counts = {s.labels["operation"]: s.value for s in family.samples}
    assert counts["resolve"] == 2.0 and counts["expand"] == 1.0


def test_label_values_are_escaped(export: str) -> None:
    family = _families(export)["pyeye_operation_count"]

    assert 'we"ird\\op' in {s.labels["operation"] for s in family.samples}


def test_memory_gauge_has_no_space_before_its_labels(export: str) -> None:
    family = _families(export)["pyeye_memory_mb"]

    assert family.type == "gauge"
    assert [s.labels for s in family.samples] == [{"type": "rss"}]
    # The parser tolerates "name {labels}"; the format doesn't.
    assert not [line for line in export.splitlines() if re.match(r"^[a-zA-Z_:][\w:]* \{", line)]


def test_every_line_ends_with_a_newline(export: str) -> None:
    assert export.endswith("\n") and not export.endswith("\n\n")


def test_the_runtime_never_imports_prometheus_client() -> None:
    """prometheus_client is test-only: no module under src/pyeye imports it."""
    importers = []
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            )
            if any(n == "prometheus_client" or n.startswith("prometheus_client.") for n in names):
                importers.append(path.relative_to(_SRC).as_posix())
    assert importers == []
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pyeye.mcp.server, sys; print('prometheus_client' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert loaded.stdout.strip().splitlines()[-1] == "False"


def test_the_artifact_cache_eviction_causes_are_counter_families(export: str) -> None:
    """#401: cap pressure and staleness are separate series; the total keeps its name."""
    families = _families(export)

    for name in (
        "pyeye_artifact_cache_evictions",
        "pyeye_artifact_cache_cap_evictions",
        "pyeye_artifact_cache_stale_evictions",
    ):
        assert families[name].type == "counter", name
        assert families[name].documentation, name
        assert len(families[name].samples) == 1, name
    total = families["pyeye_artifact_cache_evictions"].samples[0].value
    parts = sum(
        families[name].samples[0].value
        for name in ("pyeye_artifact_cache_cap_evictions", "pyeye_artifact_cache_stale_evictions")
    )
    assert total == parts
