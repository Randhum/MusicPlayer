"""Linux-native logging: file + stderr, XDG data dir, MUSICPLAYER_DEBUG for level."""

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional


class LinuxLogger:
    _instance: Optional["LinuxLogger"] = None
    _initialized: bool = False

    def __init__(self, log_dir: Optional[Path] = None):
        if LinuxLogger._initialized:
            return
        self.logger = logging.getLogger("musicplayer")
        self.logger.setLevel(
            logging.DEBUG if os.getenv("MUSICPLAYER_DEBUG") else logging.INFO
        )
        if self.logger.handlers:
            return
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.WARNING)
        console.setFormatter(fmt)
        self.logger.addHandler(console)
        if log_dir is None:
            xdg = os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")
            log_dir = Path(xdg) / "musicplayer" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "musicplayer.log", maxBytes=10 * 1024 * 1024, backupCount=5
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        self.logger.addHandler(fh)
        LinuxLogger._initialized = True

    @classmethod
    def get_logger(cls, name: str = "musicplayer") -> logging.Logger:
        if cls._instance is None:
            cls._instance = cls()
        return (
            cls._instance.logger
            if name == "musicplayer"
            else cls._instance.logger.getChild(name)
        )

    @classmethod
    def set_level(cls, level: int) -> None:
        if cls._instance is None:
            cls._instance = cls()
        cls._instance.logger.setLevel(level)


def get_logger(name: str = "musicplayer") -> logging.Logger:
    return LinuxLogger.get_logger(name)
