"""Run all Jedi work on one large-stack worker thread (#650).

Jedi's ``goto(follow_imports=True)`` can recurse about 1,500 frames inside some
stdlib modules (``io.py`` → ``_io``, ``weakref.py`` → ``_weakref``). On Linux,
macOS and CPython 3.12+, Python raises ``RecursionError`` first, and the
per-goto ``except Exception`` reports the import as unresolved. On Windows with
CPython 3.11, the main thread's 1 MB C stack overflows first, and the server
process dies.

The fix is a stack, not a recursion limit: every MCP tool that touches the
analyzers runs on ONE dedicated thread created with a large stack. There,
Python's recursion limit always fires before the C stack runs out, on every
platform. (Raising the recursion limit would make the overflow *more* likely.)

The thread runs its own asyncio event loop, because the operations are
coroutines that await file globbing and ``asyncio.to_thread`` work and create
loop-bound locks (``LazyNamespaceLoader``). Running whole coroutines there
keeps every await working and every loop-bound primitive on one loop.
Operations interleave at their awaits exactly as they did on the main loop,
and only this thread ever calls into Jedi.

Use :func:`on_jedi_worker` on a tool function (the server does), or
``await run_on_jedi_worker(coro)`` to run one piece of work there, e.g. in a
test that exercises stdlib internals.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

#: Stack size for the worker thread. Generous: ~1,500 Jedi frames need far less,
#: and the memory is reserved, not committed, until used.
WORKER_STACK_SIZE = 64 * 1024 * 1024

_THREAD_NAME = "pyeye-jedi-worker"

P = ParamSpec("P")
T = TypeVar("T")


class _JediWorker:
    """One daemon thread running an event loop, created with a large stack."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        #: The stack size the running thread was created with (0 = platform default).
        self.stack_size: int = 0

    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the worker loop, starting the thread on first use."""
        with self._lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def run() -> None:
                asyncio.set_event_loop(loop)
                loop.call_soon(ready.set)
                try:
                    loop.run_forever()
                finally:
                    loop.close()

            previous = threading.stack_size()
            size = _set_large_stack_size()
            try:
                thread = threading.Thread(target=run, name=_THREAD_NAME, daemon=True)
                thread.start()
            finally:
                # The stack size is process-wide for NEW threads: restore it so
                # only this thread gets the big stack.
                threading.stack_size(previous)
            ready.wait()
            self._loop, self._thread, self.stack_size = loop, thread, size
            logger.debug("Started %s with a %d-byte stack", _THREAD_NAME, size)
            return loop

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop the worker loop and join its thread (idempotent)."""
        with self._lock:
            loop, thread = self._loop, self._thread
            self._loop = self._thread = None
            self.stack_size = 0
        if loop is None or thread is None:
            return
        if thread.is_alive():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout)


def _set_large_stack_size() -> int:
    """Set ``threading.stack_size`` as large as allowed, up to ``WORKER_STACK_SIZE``."""
    size = WORKER_STACK_SIZE
    while size >= 4 * 1024 * 1024:
        try:
            threading.stack_size(size)
            return size
        except (ValueError, RuntimeError):  # platform limit
            size //= 2
    logger.warning("Could not enlarge the Jedi worker stack; using the platform default")
    return 0


_worker = _JediWorker()


def worker_thread() -> threading.Thread | None:
    """The worker thread, or ``None`` before the first call or after shutdown."""
    return _worker.thread


def worker_stack_size() -> int:
    """The stack size the current worker thread was created with."""
    return _worker.stack_size


def on_worker_thread() -> bool:
    """Whether the caller is running on the Jedi worker thread."""
    thread = _worker.thread
    return thread is not None and threading.current_thread() is thread


def shutdown() -> None:
    """Stop the worker. The next :func:`run_on_jedi_worker` starts a fresh one."""
    _worker.shutdown()


async def run_on_jedi_worker(work: Awaitable[T] | Callable[[], T]) -> T:
    """Run *work* on the Jedi worker thread and return its result.

    *work* is a coroutine, or a zero-argument callable (sync, or returning an
    awaitable). Exceptions propagate unchanged, ``RecursionError`` included.
    Cancelling the caller cancels the worker-side task at its next await; a
    synchronous Jedi call already running finishes first and its result is
    dropped. Called from the worker thread itself, it runs *work* in place, so
    nested hops can't deadlock.
    """
    coro = _as_coroutine(work)
    if on_worker_thread():
        return await coro
    future = asyncio.run_coroutine_threadsafe(coro, _worker.loop())
    return await asyncio.wrap_future(future)


async def _call(fn: Callable[[], Any]) -> Any:
    result = fn()
    if inspect.isawaitable(result):
        return await result
    return result


def _as_coroutine(work: Awaitable[T] | Callable[[], T]) -> Coroutine[Any, Any, T]:
    if inspect.iscoroutine(work):
        return work
    if inspect.isawaitable(work):

        async def _await() -> T:
            return await work

        return _await()
    if callable(work):
        return _call(work)
    raise TypeError(f"run_on_jedi_worker needs a coroutine or callable, got {work!r}")


#: Marker attribute set on every wrapped tool, checked by the wiring test.
WRAPPED_ATTR = "__pyeye_jedi_worker__"


def on_jedi_worker(func: Callable[P, Any]) -> Callable[P, Any]:
    """Decorate a tool so its whole body runs on the Jedi worker thread.

    Works for async and sync tools; the wrapper is always async (the MCP SDK
    awaits it). Place it innermost, directly above ``def``, so validation,
    metrics and tracking stay outside the hop and measure the whole call.
    """
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            return await run_on_jedi_worker(func(*args, **kwargs))

    else:

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            return await run_on_jedi_worker(functools.partial(func, *args, **kwargs))

    setattr(wrapper, WRAPPED_ATTR, True)
    return wrapper
