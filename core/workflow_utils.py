"""Shared workflow utilities: path normalization, video check, player selection."""

from pathlib import Path
from typing import Optional
from core.logging import get_logger

logger = get_logger(__name__)
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v"}


def normalize_path(file_path: Optional[str]) -> Optional[Path]:
    if not file_path:
        return None
    try:
        p = Path(file_path)
        return p.resolve() if p.exists() else p
    except (OSError, ValueError) as e:
        logger.debug("Failed to normalize path %s: %s", file_path, e)
        return None

def is_video_file(file_path: Optional[str]) -> bool:
    if not file_path:
        return False
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS
