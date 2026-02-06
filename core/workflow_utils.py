"""Shared workflow utilities: path normalization, video check, player selection."""

from pathlib import Path
from typing import Optional
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

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


def validate_track(track: Optional[TrackMetadata]) -> bool:
    if not track or not track.file_path:
        return False
    if not SecurityValidator.validate_path(track.file_path):
        return False
    return bool(SecurityValidator.validate_file_extension(track.file_path))


def is_video_file(file_path: Optional[str]) -> bool:
    if not file_path:
        return False
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


def select_player(track: Optional[TrackMetadata], use_moc: bool) -> str:
    if not track or not track.file_path:
        return "gstreamer"
    if is_video_file(track.file_path):
        return "gstreamer"
    return "moc" if use_moc else "gstreamer"
