"""Linux-native logging system with syslog/journald support.

This module provides structured logging that integrates with Linux logging
infrastructure, supporting both file-based logging and syslog/journald.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


class _SafeSysLogHandler(logging.Handler):
    """
    Wrapper around SysLogHandler that gracefully handles connection failures.
    
    This prevents logging errors from breaking the application when syslog/journald
    is unavailable or the socket connection fails.
    """
    
    def __init__(self, syslog_handler: logging.handlers.SysLogHandler):
        super().__init__()
        self.syslog_handler = syslog_handler
        self._failed = False
        # Copy properties from wrapped handler
        self.setLevel(syslog_handler.level)
        self.setFormatter(syslog_handler.formatter)
    
    def emit(self, record):
        """Emit a record, silently failing if syslog is unavailable."""
        if self._failed:
            return  # Don't try again if we've already failed
        
        try:
            self.syslog_handler.emit(record)
        except (OSError, FileNotFoundError, ConnectionError) as e:
            # Mark as failed and don't try again
            # This prevents spam of error messages
            self._failed = True
            # Silently ignore - syslog is not available
            pass
        except Exception:
            # For any other exception, also mark as failed
            self._failed = True
            pass
    
    def close(self):
        """Close the handler."""
        try:
            self.syslog_handler.close()
        except Exception:
            pass
        super().close()


class LinuxLogger:
    """
    Linux-native logger with syslog/journald integration.
    
    Supports:
    - File logging to XDG data directory
    - Syslog/journald integration
    - Structured logging with context
    - Environment variable control (MUSICPLAYER_DEBUG)
    """
    
    _instance: Optional['LinuxLogger'] = None
    _initialized: bool = False
    
    def __init__(self, use_syslog: bool = True, log_dir: Optional[Path] = None):
        """
        Initialize the logger.
        
        Args:
            use_syslog: If True, also log to syslog/journald
            log_dir: Directory for log files (defaults to XDG data dir)
        """
        if LinuxLogger._initialized:
            return
        
        self.logger = logging.getLogger('musicplayer')
        self.logger.setLevel(logging.DEBUG if os.getenv('MUSICPLAYER_DEBUG') else logging.INFO)
        
        # Prevent duplicate handlers
        if self.logger.handlers:
            return
        
        # Formatter with structured information
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console handler (stderr)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File handler
        if log_dir is None:
            # Use XDG data directory
            xdg_data = os.getenv('XDG_DATA_HOME', Path.home() / '.local' / 'share')
            log_dir = Path(xdg_data) / 'musicplayer' / 'logs'
        
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / 'musicplayer.log'
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Syslog/journald handler
        if use_syslog:
            try:
                # Try Unix socket first (journald)
                # Check if /dev/log exists before creating handler
                if os.path.exists('/dev/log') or os.path.exists('/run/systemd/journal/socket'):
                    syslog_handler = logging.handlers.SysLogHandler(
                        address='/dev/log',
                        facility=logging.handlers.SysLogHandler.LOG_USER
                    )
                    syslog_handler.setLevel(logging.INFO)
                    # Simpler format for syslog
                    syslog_formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s: %(message)s')
                    syslog_handler.setFormatter(syslog_formatter)
                    # Wrap in error-handling handler to catch emit failures
                    safe_syslog_handler = _SafeSysLogHandler(syslog_handler)
                    self.logger.addHandler(safe_syslog_handler)
            except (OSError, AttributeError, FileNotFoundError):
                # Fallback if syslog unavailable
                pass
        
        LinuxLogger._initialized = True
    
    @classmethod
    def get_logger(cls, name: str = 'musicplayer') -> logging.Logger:
        """
        Get a logger instance.
        
        Args:
            name: Logger name (creates child logger)
            
        Returns:
            Logger instance
        """
        if cls._instance is None:
            cls._instance = cls()
        
        if name == 'musicplayer':
            return cls._instance.logger
        else:
            return cls._instance.logger.getChild(name)
    
    @classmethod
    def set_level(cls, level: int):
        """Set logging level for the root logger."""
        if cls._instance is None:
            cls._instance = cls()
        cls._instance.logger.setLevel(level)


# Convenience functions
def get_logger(name: str = 'musicplayer') -> logging.Logger:
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

