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


if __name__ == "__main__":
    _configure_logging()

    from .server import mcp

    mcp.run()
