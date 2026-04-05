"""Logging configuration for the ABET Syllabus Generator.

Configures both console and file handlers:
- Console: INFO by default, DEBUG with --verbose, WARNING with --quiet
- File: always DEBUG level, writes to a configurable log file
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_file: str | None = None,
) -> None:
    """Configure logging for the application.

    Args:
        verbose: If True, console shows DEBUG level.
        quiet: If True, console shows only WARNING and above.
        log_file: Path to the log file. If None, file logging is disabled.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root_logger = logging.getLogger("abet_syllabus")
    root_logger.setLevel(logging.DEBUG)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    if verbose:
        console_handler.setLevel(logging.DEBUG)
    elif quiet:
        console_handler.setLevel(logging.WARNING)
    else:
        console_handler.setLevel(logging.INFO)

    console_fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # File handler (if requested)
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_fmt = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)
            file_handler.setFormatter(file_fmt)
            root_logger.addHandler(file_handler)
        except OSError:
            # If we can't create the log file, just skip file logging
            root_logger.warning("Could not create log file: %s", log_file)


def reset_logging() -> None:
    """Reset logging configuration (mainly for testing)."""
    global _configured
    root_logger = logging.getLogger("abet_syllabus")
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
    _configured = False
