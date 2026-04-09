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


def main() -> None:
    """Main entry point for the PyEye MCP server."""
    import atexit

    _configure_logging()

    # Import diagnostics early (before server import)
    from .connection_diagnostics import (
        get_diagnostics,
        log_connection_end,
        log_connection_start,
        setup_signal_handlers,
        start_heartbeat_monitor,
    )
    from .error_tracker import get_error_tracker

    # Initialize connection diagnostics
    setup_signal_handlers()
    log_connection_start()

    # Start heartbeat monitor (logs every 30 seconds)
    start_heartbeat_monitor(interval_seconds=30)

    # Import server
    from .server import ensure_unified_session, get_project_manager, initialize_plugins, mcp

    # Initialize unified metrics session
    ensure_unified_session()

    # Cleanup on exit
    def cleanup() -> None:
        """Clean up all projects and watchers on exit."""
        import logging

        logger = logging.getLogger(__name__)
        diagnostics = get_diagnostics()
        error_tracker = get_error_tracker()

        # Log final diagnostic summary
        logger.info("=" * 60)
        logger.info("SHUTDOWN DIAGNOSTICS")
        logger.info("=" * 60)

        # Connection diagnostics
        conn_summary = diagnostics.get_summary()
        logger.info(f"Connection uptime: {conn_summary['uptime_seconds']:.1f} seconds")
        logger.info(f"Total connection events: {conn_summary['total_events']}")
        logger.info(f"Final idle time: {conn_summary['idle_seconds']:.1f} seconds")

        # Error diagnostics
        error_summary = error_tracker.get_error_summary()
        logger.info(f"Total errors: {error_summary['total_errors']}")
        logger.info(f"Error types: {error_summary['error_counts_by_type']}")

        # Check for patterns
        pattern_warning = error_tracker.check_error_pattern()
        if pattern_warning:
            logger.warning(f"Error pattern detected: {pattern_warning}")

        logger.info("=" * 60)

        # End unified metrics session
        from .server import get_unified_collector

        collector = get_unified_collector()
        collector.end_session()

        # Cleanup projects
        manager = get_project_manager()
        manager.cleanup_all()
        logger.info("Cleaned up all projects and watchers")

        # Log connection end
        log_connection_end("normal_shutdown")

    atexit.register(cleanup)

    # Initialize plugins for current directory
    initialize_plugins(".")

    logger = logging.getLogger(__name__)
    logger.info("Starting PyEye Server with file watching and connection diagnostics")

    # Run the server
    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        log_connection_end("keyboard_interrupt")
    except Exception as e:
        logger.error(f"Server crashed with error: {e}", exc_info=True)
        log_connection_end(f"crash: {type(e).__name__}")
        raise


if __name__ == "__main__":
    main()
