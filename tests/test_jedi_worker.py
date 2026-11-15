"""All Jedi work runs on one large-stack worker thread (#650).

On Windows with CPython 3.11, Jedi's ``follow_imports`` recursion inside stdlib
``io.py`` overflows the 1 MB main-thread C stack and kills the server. With a
large stack, Python's ``RecursionError`` fires first on every platform, and
the edge resolver reports the import as unresolved. These tests pin:

* the worker itself: one thread, a large stack, restored global stack size,
  nested hops, exceptions, cancellation, shutdown and restart;
* the wiring: every MCP tool that touches the analyzers runs on it, and the
  test says how to fix a new tool that doesn't;
* the regression: resolving ``io``'s imports on the worker returns, with
  ``_io.UnsupportedOperation`` reported as unresolved, both directly and
  through the ``trace`` tool (which walks into ``io`` today).
"""

from __future__ import annotations

import asyncio
import gc
import importlib
import inspect
import io
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from pyeye._module_sentinel import ModuleSentinel
from pyeye.analyzers.jedi_analyzer import JediAnalyzer
from pyeye.mcp import jedi_worker
from pyeye.mcp.jedi_worker import (
    WORKER_STACK_SIZE,
    WRAPPED_ATTR,
    on_jedi_worker,
    on_worker_thread,
    run_on_jedi_worker,
    worker_stack_size,
    worker_thread,
)
from pyeye.mcp.operations.edges import resolve_imports
from tests.utils.performance import PerformanceThresholds, assert_performance_threshold

server = importlib.import_module("pyeye.mcp.server")

#: Tools that never touch Jedi or the analyzers, so they stay on the main loop.
NOT_ON_WORKER = frozenset({"get_performance_metrics", "get_connection_diagnostics"})


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@contextmanager
def _gc_paused() -> Iterator[None]:
    """Run a block with the cyclic garbage collector off (#688).

    A test that recurses to the recursion limit must not let a finaliser run
    while the stack is that deep: the unraisable hook would then run at the
    limit too, fail inside ``traceback.format_exception``, and pytest would
    blame the test.  Collect first so nothing is pending, then pause gc and
    restore the previous state afterwards.
    """
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------


class TestWorker:
    async def test_work_runs_on_one_dedicated_thread(self) -> None:
        first = await run_on_jedi_worker(threading.current_thread)
        second = await run_on_jedi_worker(threading.current_thread)
        assert first is second is worker_thread()
        assert first is not threading.main_thread()
        assert first is not threading.current_thread()
        assert first.daemon

    async def test_thread_has_the_large_stack_and_global_size_is_restored(self) -> None:
        before = threading.stack_size()
        await run_on_jedi_worker(lambda: None)
        assert worker_stack_size() == WORKER_STACK_SIZE
        assert threading.stack_size() == before

    async def test_stack_size_falls_back_when_the_platform_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = threading.stack_size

        def limited(size: int | None = None) -> int:
            if size is not None and size > 8 * 1024 * 1024:
                raise ValueError("too large")
            return real() if size is None else real(size)

        monkeypatch.setattr(jedi_worker.threading, "stack_size", limited)
        await run_on_jedi_worker(lambda: None)
        assert worker_stack_size() == 8 * 1024 * 1024

    async def test_stack_size_platform_default_when_nothing_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        real = threading.stack_size

        def refuse(size: int | None = None) -> int:
            if size:
                raise ValueError("no")
            return real() if size is None else real(size)

        monkeypatch.setattr(jedi_worker.threading, "stack_size", refuse)
        assert await run_on_jedi_worker(lambda: 42) == 42
        assert worker_stack_size() == 0
        assert "platform default" in caplog.text

    async def test_sync_callables_coroutines_and_awaitables(self) -> None:
        async def coro() -> str:
            return "coro"

        assert await run_on_jedi_worker(lambda: "sync") == "sync"
        assert await run_on_jedi_worker(coro()) == "coro"
        assert await run_on_jedi_worker(coro) == "coro"  # callable returning a coroutine
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        future.set_result("future")
        # An awaitable bound to *this* loop is awaited on the worker's loop, so
        # only loop-free awaitables are allowed. A finished future is one.
        assert await run_on_jedi_worker(future) == "future"

    async def test_rejects_non_work(self) -> None:
        with pytest.raises(TypeError, match="coroutine or callable"):
            await run_on_jedi_worker(42)  # type: ignore[arg-type]

    async def test_nested_hops_run_in_place(self) -> None:
        async def outer() -> tuple[bool, threading.Thread]:
            inner_thread = await run_on_jedi_worker(threading.current_thread)
            return on_worker_thread(), inner_thread

        on_worker, inner = await run_on_jedi_worker(outer())
        assert on_worker is True
        assert inner is worker_thread()
        assert on_worker_thread() is False  # back on the caller's thread

    async def test_exceptions_propagate_unchanged(self) -> None:
        def boom() -> None:
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await run_on_jedi_worker(boom)

    async def test_recursion_error_propagates_without_killing_anything(self) -> None:
        def recurse(n: int) -> int:
            return recurse(n + 1) + 1

        with pytest.raises(RecursionError), _gc_paused():
            await run_on_jedi_worker(lambda: recurse(0))
        # The worker survives and keeps serving.
        assert await run_on_jedi_worker(lambda: "alive") == "alive"

    def test_gc_paused_restores_the_previous_gc_state(self) -> None:
        assert gc.isenabled()
        with _gc_paused():
            assert not gc.isenabled()
        assert gc.isenabled()
        with pytest.raises(RuntimeError), _gc_paused():
            raise RuntimeError("boom")
        assert gc.isenabled()
        gc.disable()
        try:
            with _gc_paused():
                pass
            assert not gc.isenabled()
        finally:
            gc.enable()

    async def test_cancelling_the_caller_cancels_the_worker_task(self) -> None:
        started = threading.Event()
        cancelled = threading.Event()

        async def slow() -> None:
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(run_on_jedi_worker(slow()))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(cancelled.wait, 5)

    async def test_shutdown_stops_the_thread_and_a_new_call_restarts_it(self) -> None:
        first = await run_on_jedi_worker(threading.current_thread)
        jedi_worker.shutdown()
        assert worker_thread() is None
        assert not first.is_alive()
        second = await run_on_jedi_worker(threading.current_thread)
        assert second is not first and second.is_alive()

    def test_shutdown_without_a_worker_is_a_no_op(self) -> None:
        jedi_worker.shutdown()
        jedi_worker.shutdown()
        assert worker_thread() is None

    async def test_decorator_wraps_async_and_sync_functions(self) -> None:
        async def async_tool(x: int) -> tuple[int, bool]:
            """Async doc."""
            return x * 2, on_worker_thread()

        def sync_tool(x: int) -> tuple[int, bool]:
            return x + 1, on_worker_thread()

        wrapped_async = on_jedi_worker(async_tool)
        wrapped_sync = on_jedi_worker(sync_tool)
        assert await wrapped_async(3) == (6, True)
        assert await wrapped_sync(3) == (4, True)
        assert wrapped_async.__name__ == "async_tool"
        assert wrapped_async.__doc__ == "Async doc."
        assert getattr(wrapped_async, WRAPPED_ATTR) is True
        assert inspect.iscoroutinefunction(wrapped_sync)

    async def test_hop_overhead(self) -> None:
        await run_on_jedi_worker(lambda: None)  # start the thread outside the timing
        calls = 200
        start = time.perf_counter()
        for _ in range(calls):
            await run_on_jedi_worker(lambda: None)
        per_call_ms = (time.perf_counter() - start) * 1000 / calls
        threshold = PerformanceThresholds(base=2.0, linux_ci=5.0, macos_ci=10.0, windows_ci=10.0)
        assert_performance_threshold(per_call_ms, threshold, "Jedi worker hop (per call)")


# ---------------------------------------------------------------------------
# Wiring: every analyzer-touching tool runs on the worker
# ---------------------------------------------------------------------------


def _is_wrapped(fn: Any) -> bool:
    while fn is not None:
        if getattr(fn, WRAPPED_ATTR, False):
            return True
        fn = getattr(fn, "__wrapped__", None)
    return False


def test_every_registered_tool_runs_on_the_worker() -> None:
    tools = server.mcp._tool_manager._tools
    assert {"resolve", "resolve_at", "inspect", "outline", "expand", "trace"} <= set(tools)
    assert "configure_packages" in tools
    unwrapped = sorted(
        name
        for name, tool in tools.items()
        if name not in NOT_ON_WORKER and not _is_wrapped(tool.fn)
    )
    assert not unwrapped, (
        f"MCP tools not running on the Jedi worker: {unwrapped}. Add @on_jedi_worker "
        "(from pyeye.mcp.jedi_worker) directly above the tool's `def`, innermost under "
        "the validation/metrics decorators. If the tool genuinely never touches Jedi or "
        "the analyzers, add it to NOT_ON_WORKER in this test instead (#650)."
    )


def test_metrics_tools_stay_off_the_worker() -> None:
    for name in NOT_ON_WORKER:
        assert not _is_wrapped(getattr(server, name)), name


async def test_plugin_tools_are_registered_on_the_worker() -> None:
    from mcp.server.mcpserver import MCPServer

    class FakePlugin:
        # Real plugins carry their root (AnalyzerPlugin.project_path); the tool
        # wrapper re-spells result paths under it (#717).
        project_path = Path.cwd()

        def name(self) -> str:
            return "fake"

        def register_tools(self) -> dict[str, Any]:
            async def find_things(scope: str = "main") -> dict[str, Any]:
                return {"scope": scope, "on_worker": on_worker_thread()}

            return {"find_things": find_things}

    fresh = MCPServer("test")
    server.register_plugin_tools(fresh, [FakePlugin()])  # type: ignore[list-item]
    tool = fresh._tool_manager._tools["find_things"]
    assert _is_wrapped(tool.fn)
    assert (await tool.fn(scope="all")) == {"scope": "all", "on_worker": True}


async def test_tool_bodies_run_on_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, bool] = {}

    async def fake_resolve(_identifier: str, _analyzer: Any) -> dict[str, Any]:
        seen["resolve"] = on_worker_thread()
        return {"found": False, "reason": "unresolved"}

    async def fake_inspect(_handle: str, _analyzer: Any) -> dict[str, Any]:
        seen["inspect"] = on_worker_thread()
        return {"found": False}

    def fake_get_analyzer(_project_path: str = ".") -> object:
        seen["get_analyzer"] = on_worker_thread()
        return object()

    monkeypatch.setattr(server, "_resolve_impl", fake_resolve)
    monkeypatch.setattr(server, "_inspect_impl", fake_inspect)
    monkeypatch.setattr(server, "get_analyzer", fake_get_analyzer)
    await server.resolve("x")
    await server.inspect("x")
    assert seen == {"resolve": True, "inspect": True, "get_analyzer": True}


async def test_recursion_error_escaping_a_tool_is_an_mcp_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def explode(_identifier: str, _analyzer: Any) -> dict[str, Any]:
        raise RecursionError("maximum recursion depth exceeded")

    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    monkeypatch.setattr(server, "_resolve_impl", explode)
    monkeypatch.setattr(server, "get_analyzer", lambda _project_path=".": object())
    # The RecursionError crosses the hop as an ordinary exception. The SDK wraps
    # it in UnexpectedToolError, and its protocol handler (_handle_call_tool)
    # turns that into an is_error CallToolResult for the client.
    with pytest.raises(UnexpectedToolError) as excinfo:
        await server.mcp.call_tool("resolve", {"identifier": "x"})
    assert isinstance(excinfo.value.__cause__, RecursionError)
    # The server keeps serving afterwards.
    assert await run_on_jedi_worker(lambda: "alive") == "alive"


@pytest.fixture
def small_project(tmp_path: Path) -> Path:
    _write(tmp_path / "pkg" / "__init__.py")
    _write(tmp_path / "pkg" / "a.py", "class A:\n    pass\n")
    _write(tmp_path / "pkg" / "b.py", "from pkg.a import A\n\n\nclass B(A):\n    pass\n")
    return tmp_path


async def test_different_tools_back_to_back_share_one_loop(small_project: Path) -> None:
    """No loop-bound primitive created by one tool trips another (#650 review)."""
    path = small_project.as_posix()
    resolved = await server.resolve("pkg.b.B", project_path=path)
    inspected = await server.inspect("pkg.b.B", project_path=path)
    expanded = await server.expand("pkg.b.B", "superclasses", project_path=path)
    outlined = await server.outline("pkg", project_path=path)
    traced = await server.trace("pkg.b", ["imports"], project_path=path)
    assert resolved["handle"] == inspected["handle"] == "pkg.b.B"
    assert [s["handle"] for s in expanded["stubs"]] == ["pkg.a.A"]
    assert outlined["found"] is not False
    assert "pkg.a.A" in traced["nodes"]


# ---------------------------------------------------------------------------
# The #650 regression: Jedi recursion inside stdlib io
# ---------------------------------------------------------------------------


async def test_io_imports_resolve_on_the_worker_and_report_the_stub_as_unresolved(
    tmp_path: Path,
) -> None:
    """``resolve_imports`` on ``io`` recurses ~1,500 frames on ``from _io import …``.

    Without the large stack this kills the process on Windows/CPython 3.11.
    On the worker it returns, and the import Jedi couldn't follow is reported
    honestly instead.
    """
    analyzer = JediAnalyzer(str(tmp_path))
    io_module = ModuleSentinel(Path(io.__file__), "io", analyzer)

    result = await run_on_jedi_worker(lambda: resolve_imports(io_module, analyzer))

    assert result is not None
    # The walk returned and stayed honest: the imports are measured (a list),
    # and ``from _io import UnsupportedOperation`` is no longer unresolved. A
    # stdlib import is placed by the resolver from its imported path (#544):
    # ``io.UnsupportedOperation``, which is ``io`` itself, a dropped self-edge.
    assert result.unresolved_imports is not None
    assert "_io.UnsupportedOperation" not in result.unresolved_imports


async def test_trace_into_io_through_the_tool_layer(tmp_path: Path) -> None:
    """End to end: a ``trace`` that reaches ``io`` through the tool layer returns.

    Since #621 trace walks a node only when ``expand`` resolves it.  While
    ``expand("io", ...)`` is not found, ``io`` is reported in ``unresolved_nodes``
    and not walked; once #623 makes stdlib modules resolvable, trace walks it
    and the worker's large stack turns Jedi's deep recursion into an unresolved
    import.  Either way the call must return, and must say which happened.
    """
    _write(tmp_path / "iopkg" / "__init__.py")
    _write(tmp_path / "iopkg" / "m.py", "import io\n\n\ndef f():\n    return io.StringIO()\n")

    traced = await server.trace(
        "iopkg.m", ["imports"], project_path=tmp_path.as_posix(), max_depth=2
    )

    assert "io" in traced["nodes"]
    walked_io = any(edge["from"] == "io" for edge in traced["edges"])
    assert "io" in traced["unresolved_nodes"] or walked_io


@pytest.mark.skipif(sys.platform != "win32", reason="the C stack overflow is Windows-only")
async def test_main_thread_stack_is_still_the_small_one_on_windows() -> None:
    """Sanity: the fix is the worker, not a process-wide stack change."""
    assert threading.stack_size() == 0
