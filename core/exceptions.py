"""Custom exception hierarchy for the music player application.

This module provides a structured exception hierarchy for consistent
error handling across the application.
"""


class MusicPlayerError(Exception):
    """Base exception for all music player errors."""

    pass


class PlayerError(MusicPlayerError):
    """Errors related to audio playback."""

    pass


class MOCError(MusicPlayerError):
    """Errors related to MOC integration."""

    pass


class PlaylistError(MusicPlayerError):
    """Errors related to playlist operations."""

    pass


class ConfigurationError(MusicPlayerError):
    """Errors related to configuration."""

    pass


class MetadataError(MusicPlayerError):
    """Errors related to metadata operations."""

    pass


class BluetoothError(MusicPlayerError):
    """Errors related to Bluetooth operations."""

    pass


class SecurityError(MusicPlayerError):
    """Errors related to security validation."""

    pass
