"""The unified metrics store stays bounded and whole (#914).

On a dev box ``~/.pyeye/metrics/active_sessions.json`` had grown to 1.29 MB
of sessions that were never closed, most of them written by test runs. Every
MCP operation rewrites that file, so a call cost about 157 ms instead of 1 ms,
and an in-place write could be read half-written.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess  # nosec B404 - launches this interpreter only
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from filelock import FileLock

import pyeye.unified_metrics as um
from pyeye.unified_metrics import STALE_SESSION_AGE, UnifiedMetricsCollector


def _active(c: UnifiedMetricsCollector) -> dict:
    return json.loads(c.active_sessions_file.read_text(encoding="utf-8"))


def _completed(c: UnifiedMetricsCollector) -> list[dict]:
    if not c.completed_sessions_file.exists():
        return []
    return [json.loads(line) for line in c.completed_sessions_file.read_text().splitlines()]


# --- (d) one session per process, not per thread -----------------------------


def test_operations_on_other_threads_join_the_process_session(tmp_path: Path) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    sid = c.start_session(session_type="main")
    threads = [threading.Thread(target=c.record_mcp_operation, args=("inspect",)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    async def fan_out() -> None:
        await asyncio.gather(
            *(asyncio.to_thread(c.record_mcp_operation, "outline") for _ in range(4))
        )

    asyncio.run(fan_out())
    sessions = _active(c)
    assert list(sessions) == [sid]
    assert sessions[sid]["mcp_operations"] == {"inspect": 3, "outline": 4}


def test_an_operation_with_no_session_opens_one_for_the_process(tmp_path: Path) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    threads = [threading.Thread(target=c.record_mcp_operation, args=("resolve",)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    c.record_mcp_operation("resolve")
    sessions = _active(c)
    assert len(sessions) == 1
    assert next(iter(sessions.values()))["mcp_operations"] == {"resolve": 4}


def test_end_session_from_another_thread_ends_the_process_session(tmp_path: Path) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    c.start_session(session_type="main")
    c.record_mcp_operation("inspect")
    t = threading.Thread(target=c.end_session)
    t.start()
    t.join()
    assert _active(c) == {}
    assert [s["mcp_operations"] for s in _completed(c)] == [{"inspect": 1}]


# --- (b) whole writes; no write without the lock -----------------------------


def test_a_concurrent_reader_never_sees_a_partial_file(tmp_path: Path) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    c.start_session(session_type="main")
    # Make the file big enough that an in-place write would be observable.
    for i in range(200):
        c.record_mcp_operation(f"tool_{i}", duration_ms=1.0)

    torn: list[str] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            text = c.active_sessions_file.read_text(encoding="utf-8")
            try:
                json.loads(text)
            except json.JSONDecodeError:
                torn.append(text[:40])

    r = threading.Thread(target=reader)
    r.start()
    try:
        for _ in range(100):
            c.record_mcp_operation("inspect")
    finally:
        stop.set()
        r.join()
    assert torn == []


def test_a_lock_timeout_skips_the_update_instead_of_writing_unlocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    sid = c.start_session(session_type="main")
    before = c.active_sessions_file.read_bytes()
    monkeypatch.setattr(um, "_LOCK_TIMEOUT_S", 0.05)
    held = FileLock(f"{c.active_sessions_file}.lock")
    with held, caplog.at_level("WARNING", logger="pyeye.unified_metrics"):
        held_by_other_thread = threading.Thread(target=c.record_mcp_operation, args=("inspect",))
        held_by_other_thread.start()
        held_by_other_thread.join()
    assert c.active_sessions_file.read_bytes() == before
    assert "skipped" in caplog.text
    assert _active(c)[sid]["mcp_operations"] == {}


# --- (c) stale sessions are pruned at start-up --------------------------------


def _seed(
    c: UnifiedMetricsCollector, sid: str, last_activity: datetime | None, start: datetime
) -> None:
    def add(data: dict) -> None:
        data[sid] = {
            "session_id": sid,
            "session_type": "auto",
            "parent_session": None,
            "start_time": start.isoformat(),
            "end_time": None,
            "mcp_operations": {"inspect": 2},
            "grep_operations": 0,
            "total_operations": 2,
            "errors": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "memory_peak_mb": 0.0,
            "metadata": {},
        }
        if last_activity is not None:
            data[sid]["last_activity"] = last_activity.isoformat()

    c._update_json_atomic(c.active_sessions_file, add)


def test_start_up_moves_stale_sessions_to_completed_and_keeps_fresh_ones(tmp_path: Path) -> None:
    seeder = UnifiedMetricsCollector(storage_dir=tmp_path)
    now = datetime.now()
    old = now - STALE_SESSION_AGE - timedelta(hours=1)
    _seed(seeder, "stale-by-activity", last_activity=old, start=old - timedelta(hours=5))
    _seed(seeder, "stale-legacy", last_activity=None, start=old)  # written before #914
    _seed(seeder, "busy-long-running", last_activity=now, start=old - timedelta(days=3))
    _seed(seeder, "fresh", last_activity=now - timedelta(minutes=5), start=now)

    c = UnifiedMetricsCollector(storage_dir=tmp_path)  # a new process starting up

    assert sorted(_active(c)) == ["busy-long-running", "fresh"]
    completed = {s["session_id"]: s for s in _completed(c)}
    assert sorted(completed) == ["stale-by-activity", "stale-legacy"]
    assert completed["stale-by-activity"]["end_time"] == old.isoformat()
    assert completed["stale-legacy"]["end_time"] == old.isoformat()
    assert completed["stale-by-activity"]["statistics"]["mcp_operations_count"] == 2
    stats = json.loads(c.aggregated_stats_file.read_text())
    assert stats["total_sessions"] == 2


def test_start_up_with_nothing_stale_leaves_the_file_untouched(tmp_path: Path) -> None:
    seeder = UnifiedMetricsCollector(storage_dir=tmp_path)
    seeder.start_session(session_type="main")
    before = seeder.active_sessions_file.stat().st_mtime_ns
    UnifiedMetricsCollector(storage_dir=tmp_path)
    assert seeder.active_sessions_file.stat().st_mtime_ns == before


def test_every_update_refreshes_last_activity(tmp_path: Path) -> None:
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    sid = c.start_session(session_type="main")
    first = _active(c)[sid]["last_activity"]
    c.record_mcp_operation("inspect")
    assert _active(c)[sid]["last_activity"] >= first


def test_the_record_cost_does_not_grow_with_stale_history(tmp_path: Path) -> None:
    """The dev-box file held 121 stale sessions; a new process now sheds them."""
    seeder = UnifiedMetricsCollector(storage_dir=tmp_path)
    old = datetime.now() - STALE_SESSION_AGE - timedelta(hours=1)
    for i in range(121):
        _seed(seeder, f"auto_{i}", last_activity=old, start=old)
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    c.start_session(session_type="main")
    c.record_mcp_operation("inspect")
    assert len(_active(c)) == 1
    assert c.active_sessions_file.stat().st_size < 2_000


# --- (a) the test run never writes the real home store -----------------------


def test_the_test_run_stores_metrics_in_a_temporary_directory() -> None:
    configured = os.environ.get("PYEYE_METRICS_DIR")
    assert configured, "tests/conftest.py must set PYEYE_METRICS_DIR for the whole run"
    real_home_store = Path.home() / um.METRICS_DIR
    assert Path(configured) != real_home_store
    assert um.get_unified_collector().storage_dir == Path(configured)


def test_a_server_launched_as_a_subprocess_stores_there_too() -> None:
    """``python -m pyeye.mcp`` from a test inherits the redirect (it opens a session at start-up)."""
    store = Path(os.environ["PYEYE_METRICS_DIR"])
    before = set(json.loads((store / "active_sessions.json").read_text() or "{}"))
    proc = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments  # nosec B603
        [sys.executable, "-m", "pyeye.mcp"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    completed = [
        json.loads(line) for line in (store / "completed_sessions.jsonl").read_text().splitlines()
    ]
    pid_sessions = [s for s in completed if s["session_id"].startswith("mcp_server_")]
    assert pid_sessions, "the subprocess server's session should land in the redirected store"
    assert set(json.loads((store / "active_sessions.json").read_text())) <= before


def test_the_store_path_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYEYE_METRICS_DIR", (tmp_path / "custom").as_posix())
    assert UnifiedMetricsCollector().storage_dir == tmp_path / "custom"
    monkeypatch.delenv("PYEYE_METRICS_DIR")
    assert um.default_storage_dir() == Path.home() / um.METRICS_DIR


def test_a_file_held_open_elsewhere_skips_the_write_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Windows refuses ``os.replace`` over an open file; metrics must never break a tool call."""
    c = UnifiedMetricsCollector(storage_dir=tmp_path)
    sid = c.start_session(session_type="main")
    before = c.active_sessions_file.read_bytes()

    def refuse(*_args: object) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(um.os, "replace", refuse)
    monkeypatch.setattr(um.time, "sleep", lambda _s: None)
    with caplog.at_level("WARNING", logger="pyeye.unified_metrics"):
        c.record_mcp_operation("inspect")  # must not raise
    assert c.active_sessions_file.read_bytes() == before
    assert "stayed open elsewhere" in caplog.text
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".active_sessions")] == []
    assert sid in _active(c)
