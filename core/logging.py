"""Linux-native logging system with syslog/journald support.

This module provides structured logging that integrates with Linux logging
infrastructure, supporting both file-based logging and syslog/journald.
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
# None


class LinuxLogger:
    """
    Linux-native logger with file and console output.

    Supports:
    - File logging to XDG data directory
    - Console output for warnings and errors
    - Structured logging with context
    - Environment variable control (MUSICPLAYER_DEBUG)
    """

    _instance: Optional["LinuxLogger"] = None
    _initialized: bool = False

    def __init__(self, log_dir: Optional[Path] = None):
        """
        Initialize the logger.

        Args:
            log_dir: Directory for log files (defaults to XDG data dir)
        """
        if LinuxLogger._initialized:
            return

        self.logger = logging.getLogger("musicplayer")
        self.logger.setLevel(
            logging.DEBUG if os.getenv("MUSICPLAYER_DEBUG") else logging.INFO
        )

        # Prevent duplicate handlers
        if self.logger.handlers:
            return

        # Formatter with structured information
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler (stderr)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler
        if log_dir is None:
            # Use XDG data directory
            xdg_data = os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")
            log_dir = Path(xdg_data) / "musicplayer" / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "musicplayer.log"

        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Note: Syslog/journald handler disabled due to unreliable socket connections
        # on some Linux systems (socket can become stale causing "Bad file descriptor"
        # errors). File logging provides sufficient persistence for debugging.

        LinuxLogger._initialized = True

    @classmethod
    def get_logger(cls, name: str = "musicplayer") -> logging.Logger:
        """
        Get a logger instance.

        Args:
            name: Logger name (creates child logger)

        Returns:
            Logger instance
        """
        if cls._instance is None:
            cls._instance = cls()

        if name == "musicplayer":
            return cls._instance.logger
        else:
            return cls._instance.logger.getChild(name)

    @classmethod
    def set_level(cls, level: int) -> None:
        """
        Set logging level for the root logger.

        Args:
            level: Logging level (logging.DEBUG, logging.INFO, etc.)
        """
        if cls._instance is None:
            cls._instance = cls()
        cls._instance.logger.setLevel(level)


# Convenience functions
def get_logger(name: str = "musicplayer") -> logging.Logger:
    """Get a logger instance."""
    return LinuxLogger.get_logger(name)


def debug(msg: str, *args, **kwargs):
    """Log a debug message."""
    logger = get_logger()
    logger.debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    """Log an info message."""
    logger = get_logger()
    logger.info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """Log a warning message."""
    logger = get_logger()
    logger.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """Log an error message."""
    logger = get_logger()
    logger.error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """Log a critical message."""
    logger = get_logger()
    logger.critical(msg, *args, **kwargs)


def exception(msg: str, *args, exc_info=True, **kwargs):
    """Log an exception with traceback."""
    logger = get_logger()
    logger.error(msg, *args, exc_info=exc_info, **kwargs)
