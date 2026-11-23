"""Entry point for running Pyeye MCP server.

Usage:
    python -m pyeye.mcp

Environment variables:
    PYEYE_LOG_FILE  Path to log file.  All processes append to the same file;
                    PID is included in every log line for filtering.
                    If not set, logs go to stderr only.
    PYEYE_LOG_LEVEL Log level (DEBUG, INFO, WARNING, ERROR). Default: INFO.
"""

import logging
import os
import sys
import threading
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer


def _configure_logging() -> None:
    """Set up logging based on environment variables.

    When ``PYEYE_LOG_FILE`` is set, appends to that file.  Multiple
    processes can safely append — each line includes the PID.
    """
    log_level_str = os.environ.get("PYEYE_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    fmt = "%(asctime)s [PID %(process)d] %(name)s %(levelname)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = []

    # Always add stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    handlers.append(stderr_handler)

    # Add file handler if PYEYE_LOG_FILE is set
    log_file = os.environ.get("PYEYE_LOG_FILE")
    if log_file:
        from pathlib import Path

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        handlers.append(file_handler)

        print(f"pyeye: logging to {log_file}", file=sys.stderr)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    logger = logging.getLogger("pyeye")
    logger.info("PyEye MCP server starting (PID %d)", os.getpid())
    logger.info("Python %s", sys.version.split()[0])
    logger.info("Log level: %s", log_level_str)


def _log_shutdown_diagnostics(logger: logging.Logger) -> None:
    """Log the connection and error summary at shutdown."""
    from .connection_diagnostics import get_diagnostics
    from .error_tracker import get_error_tracker

    diagnostics = get_diagnostics()
    error_tracker = get_error_tracker()

    logger.info("=" * 60)
    logger.info("SHUTDOWN DIAGNOSTICS")
    logger.info("=" * 60)

    conn_summary = diagnostics.get_summary()
    logger.info(f"Connection uptime: {conn_summary['uptime_seconds']:.1f} seconds")
    logger.info(f"Total connection events: {conn_summary['total_events']}")
    logger.info(f"Final idle time: {conn_summary['idle_seconds']:.1f} seconds")

    error_summary = error_tracker.get_error_summary()
    logger.info(f"Total errors: {error_summary['total_errors']}")
    logger.info(f"Error types: {error_summary['error_counts_by_type']}")

    pattern_warning = error_tracker.check_error_pattern()
    if pattern_warning:
        logger.warning(f"Error pattern detected: {pattern_warning}")

    logger.info("=" * 60)


def _shutdown_jedi_worker() -> None:
    """Stop the Jedi worker thread (#650) before tearing projects down."""
    from .jedi_worker import shutdown

    shutdown()


def _cleanup_projects(logger: logging.Logger) -> None:
    """Clean up all projects and their file watchers."""
    from .server import get_project_manager

    get_project_manager().cleanup_all()
    logger.info("Cleaned up all projects and watchers")


def _log_normal_shutdown() -> None:
    """Record the end of the connection."""
    from .connection_diagnostics import log_connection_end

    log_connection_end("normal_shutdown")


def cleanup() -> None:
    """Clean up all projects and watchers on exit (registered with atexit).

    Each step runs independently: a failure is logged and the remaining steps
    still run, so a broken step can never skip the Jedi worker or file-watcher
    teardown (#791).
    """
    logger = logging.getLogger(__name__)
    steps = (
        ("shutdown diagnostics", lambda: _log_shutdown_diagnostics(logger)),
        ("Jedi worker", _shutdown_jedi_worker),
        ("projects and watchers", lambda: _cleanup_projects(logger)),
        ("connection end", _log_normal_shutdown),
    )
    for name, step in steps:
        try:
            step()
        except Exception:
            logger.exception("Shutdown cleanup step failed: %s", name)


#: How long the shutdown cleanup may run before the process exits anyway (#1124).
SHUTDOWN_DEADLINE_SECONDS = 10.0

_shutdown_started = threading.Event()


def request_shutdown(signum: int) -> None:
    """Shut the server down on a signal, once (#1124).

    Called from the signal handler on the main thread, which is inside the
    event loop. The MCP SDK's stdin reader is a thread that cancellation can't
    interrupt, so the loop can't be unwound until the client writes; instead a
    helper thread cleans up and ends the process. A second signal while that
    runs is ignored: the deadline already bounds it.
    """
    if _shutdown_started.is_set():
        return
    _shutdown_started.set()
    threading.Thread(target=_terminate, args=(signum,), daemon=True, name="pyeye-shutdown").start()


def _terminate(signum: int) -> None:
    """Run :func:`cleanup` and exit 0; exit by the deadline even if cleanup hangs."""
    deadline = threading.Timer(SHUTDOWN_DEADLINE_SECONDS, lambda: os._exit(0))
    deadline.daemon = True
    deadline.start()
    logging.getLogger(__name__).info("Shutting down on signal %d", signum)
    cleanup()
    deadline.cancel()
    # os._exit: the interpreter's own exit would wait on the blocked stdin read.
    os._exit(0)


def main() -> None:
    """Main entry point for the PyEye MCP server."""
    import atexit

    _configure_logging()

    # Import diagnostics early (before server import)
    from .connection_diagnostics import (
        log_connection_start,
        setup_signal_handlers,
        start_heartbeat_monitor,
    )

    # Initialize connection diagnostics
    setup_signal_handlers(on_terminate=request_shutdown)
    log_connection_start()

    # Start heartbeat monitor (logs every 30 seconds)
    start_heartbeat_monitor(interval_seconds=30)

    # Import server
    from .server import mcp, prepare_plugins

    # Cleanup on exit
    atexit.register(cleanup)

    # Plugins for the current directory: registry reset now; framework
    # detection in the background once serving starts (#1143).
    prepare_plugins(".")

    logger = logging.getLogger(__name__)
    logger.info("Starting PyEye Server with file watching and connection diagnostics")

    # Run the server: the SDK's stdio path, plus tools.listChanged (#770)
    import anyio

    serve_then_clean_up(lambda: anyio.run(serve_detecting_plugins, mcp, "."))


async def serve_detecting_plugins(
    server: "MCPServer",
    project_path: str,
    transport: "Callable[[MCPServer], Awaitable[None]] | None" = None,
) -> None:
    """Serve *server*, detecting *project_path*'s frameworks in the background (#1143).

    Detection walks files, so it runs on a daemon thread while *transport*
    (default: :func:`~pyeye.mcp.list_changed.run_stdio`) serves: the server
    answers, and notices a closed stdin, from the start. When detection ends,
    the detected plugins' tools are registered on the event loop and announced
    with a tools-changed event. A detection still running when serving ends
    is abandoned with the process.
    """
    import anyio
    import anyio.from_thread
    import anyio.lowlevel

    from .list_changed import ToolsChangedNotifier, run_stdio
    from .server import commit_plugins, detect_plugins

    notifier = ToolsChangedNotifier(server).install()
    token = anyio.lowlevel.current_token()
    logger = logging.getLogger(__name__)

    async def commit(detected: list) -> None:
        if commit_plugins(project_path, detected):
            await notifier.announce()

    def detect() -> None:
        try:
            detected = detect_plugins(project_path)
        except Exception:
            logger.exception("Plugin detection failed")
            return
        try:
            anyio.from_thread.run(commit, detected, token=token)
        except Exception:  # serving ended first: the loop is gone
            logger.debug("Plugin detection finished after the server stopped", exc_info=True)

    threading.Thread(target=detect, daemon=True, name="pyeye-plugin-detection").start()
    await (transport or run_stdio)(server)


def serve_then_clean_up(serve: Callable[[], None]) -> None:
    """Run *serve*, then :func:`cleanup` before the interpreter starts to exit (#1124).

    *serve* returns when stdin reaches EOF (the client went away). Cleanup runs
    here, not only from ``atexit``: the interpreter joins every non-daemon
    thread BEFORE it runs ``atexit`` handlers, so any non-daemon thread still
    running would hang the exit. watchdog 7.0-7.1.0's Windows reader thread was
    one (gorakhargosh/watchdog#1470; pyeye requires 7.1.1 since #1146).
    """
    import atexit

    from .connection_diagnostics import log_connection_end

    logger = logging.getLogger(__name__)
    try:
        serve()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        log_connection_end("keyboard_interrupt")
    except Exception as e:
        logger.error(f"Server crashed with error: {e}", exc_info=True)
        log_connection_end(f"crash: {type(e).__name__}")
        raise
    finally:
        atexit.unregister(cleanup)
        cleanup()


if __name__ == "__main__":
    main()
