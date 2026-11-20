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


def main() -> None:
    """Main entry point for the PyEye MCP server."""
    import atexit

    _configure_logging()

    # Import diagnostics early (before server import)
    from .connection_diagnostics import (
        log_connection_end,
        log_connection_start,
        setup_signal_handlers,
        start_heartbeat_monitor,
    )

    # Initialize connection diagnostics
    setup_signal_handlers()
    log_connection_start()

    # Start heartbeat monitor (logs every 30 seconds)
    start_heartbeat_monitor(interval_seconds=30)

    # Import server
    from .server import initialize_plugins, mcp

    # Cleanup on exit
    atexit.register(cleanup)

    # Initialize plugins for current directory
    initialize_plugins(".")

    logger = logging.getLogger(__name__)
    logger.info("Starting PyEye Server with file watching and connection diagnostics")

    # Run the server: the SDK's stdio path, plus tools.listChanged (#770)
    import anyio

    from .list_changed import run_stdio

    try:
        anyio.run(run_stdio, mcp)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        log_connection_end("keyboard_interrupt")
    except Exception as e:
        logger.error(f"Server crashed with error: {e}", exc_info=True)
        log_connection_end(f"crash: {type(e).__name__}")
        raise


if __name__ == "__main__":
    main()
