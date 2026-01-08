"""Shared workflow utilities for consistent logic patterns across the application.

This module provides centralized utilities for common operations like:
- Player selection logic
- Track validation
- Path normalization
- State checking
- Error recovery patterns
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from pathlib import Path
from typing import Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

logger = get_logger(__name__)


# ============================================================================
# Constants
# ============================================================================
# Video container extensions - these get video+audio playback
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v"}


# ============================================================================
# Module-Level Functions
# ============================================================================
def normalize_path(file_path: Optional[str]) -> Optional[Path]:
    """Normalize file path consistently across the application.

    Args:
        file_path: File path as string (can be None).

    Returns:
        Normalized Path object, or None if input is None or invalid.
    """
    if not file_path:
        return None

    try:
        path = Path(file_path)
        # Resolve to absolute path if possible
        if path.exists():
            return path.resolve()
        return path
    except (OSError, ValueError) as e:
        logger.debug("Failed to normalize path %s: %s", file_path, e)
        return None


def validate_track(track: Optional[TrackMetadata]) -> bool:
    """Validate track for playback.

    Args:
        track: Track metadata to validate.

    Returns:
        True if track is valid for playback, False otherwise.
    """
    if not track:
        return False

    if not track.file_path:
        logger.debug("Track has no file_path")
        return False

    # Validate path security
    validated_path = SecurityValidator.validate_path(track.file_path)
    if not validated_path:
        logger.debug("Track path failed security validation: %s", track.file_path)
        return False

    # Validate file extension
    if not SecurityValidator.validate_file_extension(str(validated_path)):
        logger.debug("Track has invalid file extension: %s", track.file_path)
        return False

    return True


def is_video_file(file_path: Optional[str]) -> bool:
    """Check if file is a video container format.

    Args:
        file_path: Path to the file.

    Returns:
        True if file is a video container, False otherwise.
    """
    if not file_path:
        return False

    path = Path(file_path)
    return path.suffix.lower() in VIDEO_EXTENSIONS


def select_player(track: Optional[TrackMetadata], use_moc: bool) -> str:
    """Select appropriate player for track.

    Args:
        track: Track metadata.
        use_moc: Whether MOC is available and should be used for audio files.

    Returns:
        Player identifier: 'moc' for audio files (if MOC available), 'gstreamer' for video files.
    """
    if not track or not track.file_path:
        return "gstreamer"  # Default fallback

    if is_video_file(track.file_path):
        return "gstreamer"

    # Audio files: use MOC if available, otherwise GStreamer
    if use_moc:
        return "moc"

    return "gstreamer"


def get_file_extension(file_path: Optional[str]) -> Optional[str]:
    """Get file extension in lowercase.

    Args:
        file_path: Path to the file.

    Returns:
        File extension (including dot) in lowercase, or None if invalid.
    """
    if not file_path:
        return None

    try:
        path = Path(file_path)
        return path.suffix.lower()
    except (OSError, ValueError):
        return None
