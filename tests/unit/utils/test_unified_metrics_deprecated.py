"""The unified metrics store is removed; what's left is deprecated (#943).

Designer's ruling, for 2.x (patch-compatible, #628 option (a)):
``get_unified_collector`` warns and returns a collector that accepts the old
calls and records nothing; ``scripts/unified_metrics.py`` prints the
deprecation and exits 0; ``PYEYE_ISSUE`` and ``PYEYE_PARENT_SESSION`` are
accepted and ignored. All of it is deleted under #749.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - launches this interpreter only
import sys
import warnings
from pathlib import Path

import pytest

from pyeye import settings as settings_module
from pyeye.unified_metrics import get_unified_collector

_REPO = Path(__file__).resolve().parents[3]


def test_get_unified_collector_warns() -> None:
    with pytest.warns(DeprecationWarning, match="unified metrics store was removed"):
        get_unified_collector()


def test_the_collector_accepts_the_old_calls_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        collector = get_unified_collector(storage_dir=tmp_path / "store")
    sid = collector.start_session(session_type="main", metadata={"issue": "1"})
    collector.record_mcp_operation(tool_name="inspect", success=True, duration_ms=1.0)
    collector.record_mcp_operation("resolve", sid, False, 2.0)
    collector.record_grep_operation(sid)
    collector.update_cache_stats(hits=1, misses=2, session_id=sid)
    assert collector.end_session(sid) == {}
    assert collector.get_active_sessions() == {}
    assert collector.get_session_tree() == {}
    assert collector.get_aggregated_report(days=7, include_sessions=True) == {}
    assert collector.cleanup_old_sessions(days=30) == 0
    assert collector.prune_stale_sessions() == 0
    assert list(tmp_path.iterdir()) == []  # no store, no ~/.pyeye


def test_the_script_prints_the_deprecation_and_exits_0(tmp_path: Path) -> None:
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    for args in ([], ["status"], ["report", "--days", "7"], ["dashboard"], ["cleanup"]):
        proc = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments  # nosec B603
            [sys.executable, str(_REPO / "scripts" / "unified_metrics.py"), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=env,
        )
        assert proc.returncode == 0, (args, proc.stderr)
        assert "deprecated" in proc.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["PYEYE_ISSUE", "PYEYE_PARENT_SESSION"])
def test_the_session_label_env_vars_are_deprecated_no_ops(name: str) -> None:
    assert "nothing records sessions" in settings_module.DEPRECATED_ENV_VARS[name]
