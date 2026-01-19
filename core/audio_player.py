"""GStreamer-based media player for video files.

This module provides playback for video container formats (MP4, MKV, WebM, etc.).
For audio-only files, the application uses MOC (Music On Console) via moc_controller.py
for better audio codec support and lower resource usage.

The AudioPlayer class handles:
- Video container playback (with audio tracks)
- Video-specific features (video output, codec handling)
- Position tracking and seeking for video files
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.audio_effects import AudioEffects
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.workflow_utils import is_video_file

logger = get_logger(__name__)


# ============================================================================
# Type Definitions
# ============================================================================
class PlaybackState(Enum):
    """State machine for playback operations."""

    STOPPED = "stopped"  # No track loaded or stopped
    LOADING = "loading"  # Track is being loaded
    PAUSED = "paused"  # Track loaded but paused
    PLAYING = "playing"  # Track is playing
    SEEKING = "seeking"  # Seek operation in progress


# ============================================================================
# Constants
# ============================================================================
# GStreamer playbin flags
GST_FLAG_VIDEO = 0x01
GST_FLAG_AUDIO = 0x02
GST_FLAG_SOFT_VOLUME = 0x10

# Update intervals (milliseconds)
DURATION_UPDATE_INTERVAL = 1000  # Poll less frequently - rely on DURATION_CHANGED message
POSITION_UPDATE_INTERVAL = 500


# ============================================================================
# Classes
# ============================================================================
class AudioPlayer:
    """
    GStreamer-based media player for video container formats.

    Note: This player is primarily used for video files. Audio-only playback
    is handled by MOC (Music On Console) via moc_controller.py for better
    codec support and performance.

    Supports video containers with embedded audio tracks (MP4, MKV, WebM, etc.).
    """

    def __init__(self):
        if not Gst.is_initialized():
            Gst.init(None)

        self.playbin: Optional[Gst.Element] = None
        self.current_track: Optional[TrackMetadata] = None
        self.volume: float = 1.0
        self.position: float = 0.0
        self.duration: float = 0.0

        # Explicit state machine (replaces is_playing boolean)
        self._playback_state: PlaybackState = PlaybackState.STOPPED

        # Timeout callback IDs for cleanup
        self._position_timeout_id: Optional[int] = None
        self._duration_timeout_id: Optional[int] = None

        # Callbacks removed - state updates handled via polling/events in PlaybackController

        # Audio effects
        self.audio_effects = AudioEffects()

        self._setup_pipeline()

    def _setup_pipeline(self):
        """Set up the GStreamer playbin pipeline."""
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if not self.playbin:
            raise RuntimeError("Failed to create GStreamer playbin")

        # Create audio effects pipeline
        # Build: source -> equalizer -> replaygain -> sink
        audio_pipeline = Gst.Bin.new("audio_effects")

        # Create equalizer if available
        equalizer = self.audio_effects.create_equalizer()
        replaygain = self.audio_effects.create_replaygain()

        # Create audio sink
        audio_sink = Gst.ElementFactory.make("autoaudiosink", "audiosink")

        if equalizer and replaygain and audio_sink:
            # Chain: equalizer -> replaygain -> sink
            audio_pipeline.add(equalizer)
            audio_pipeline.add(replaygain)
            audio_pipeline.add(audio_sink)

            # Link elements
            equalizer.link(replaygain)
            replaygain.link(audio_sink)

            # Add ghost pads
            audio_pipeline.add_pad(Gst.GhostPad.new("sink", equalizer.get_static_pad("sink")))

            self.playbin.set_property("audio-sink", audio_pipeline)
            logger.debug("Audio player: Audio effects pipeline created")
        elif audio_sink:
            # Fallback: just use audio sink without effects
            self.playbin.set_property("audio-sink", audio_sink)

        # Use autovideosink for video output
        video_sink = Gst.ElementFactory.make("autovideosink", "videosink")
        if video_sink:
            self.playbin.set_property("video-sink", video_sink)

        # Set initial volume
        self.playbin.set_property("volume", self.volume)

        # Set up message bus
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _on_message(self, bus: Gst.Bus, message: Gst.Message) -> bool:
        """
        Handle GStreamer bus messages.

        Args:
            bus: GStreamer message bus
            message: GStreamer message

        Returns:
            True to continue receiving messages
        """
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error("Playback error: %s", err.message)
            if debug:
                logger.debug("GStreamer debug: %s", debug)
            self._log_codec_help(err.message, debug or "")
            self._stop()

        elif msg_type == Gst.MessageType.EOS:
            self._playback_state = PlaybackState.STOPPED
            # Stop position updates
            if self._position_timeout_id is not None:
                try:
                    GLib.source_remove(self._position_timeout_id)
                except (ValueError, TypeError):
                    pass
                self._position_timeout_id = None
            # Send final position update (position = duration) to show "00:00" left
            if self.duration > 0:
                self.position = self.duration
                # Position changed - PlaybackController will poll for updates
            # Track finished - PlaybackController will poll for updates

        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.playbin:
                _, new_state, _ = message.parse_state_changed()

                if new_state == Gst.State.PLAYING:
                    # Transition from SEEKING, PAUSED, or LOADING to PLAYING is valid
                    if self._playback_state in (
                        PlaybackState.SEEKING,
                        PlaybackState.PAUSED,
                        PlaybackState.LOADING,
                    ):
                        self._playback_state = PlaybackState.PLAYING
                    # Remove any existing duration timeout before adding a new one
                    if self._duration_timeout_id is not None:
                        try:
                            GLib.source_remove(self._duration_timeout_id)
                        except (ValueError, TypeError):
                            pass
                    # Only start duration polling if we don't have duration yet
                    # Rely primarily on DURATION_CHANGED message, polling is just a fallback
                    if self.duration <= 0:
                        self._duration_timeout_id = GLib.timeout_add(
                            DURATION_UPDATE_INTERVAL, self._update_duration
                        )
                elif new_state == Gst.State.PAUSED:
                    # Transition from SEEKING, PLAYING, or LOADING to PAUSED is valid
                    if self._playback_state in (
                        PlaybackState.SEEKING,
                        PlaybackState.PLAYING,
                        PlaybackState.LOADING,
                    ):
                        self._playback_state = PlaybackState.PAUSED
                    # Remove duration timeout when paused
                    if self._duration_timeout_id is not None:
                        try:
                            GLib.source_remove(self._duration_timeout_id)
                        except (ValueError, TypeError):
                            pass  # Source already removed or invalid
                        self._duration_timeout_id = None
                elif new_state == Gst.State.NULL:
                    self._playback_state = PlaybackState.STOPPED
                    # Remove duration timeout when stopped
                    if self._duration_timeout_id is not None:
                        try:
                            GLib.source_remove(self._duration_timeout_id)
                        except (ValueError, TypeError):
                            pass  # Source already removed or invalid
                        self._duration_timeout_id = None

            # State changed - PlaybackController will poll for updates

        elif msg_type == Gst.MessageType.DURATION_CHANGED:
            self._update_duration()

        return True

    def _log_codec_help(self, error: str, debug: str) -> None:
        """
        Log helpful messages for missing codecs.

        Args:
            error: Error message from GStreamer
            debug: Debug information from GStreamer
        """
        combined = (error + debug).lower()

        if "flac" in combined:
            logger.warning("Missing FLAC support: emerge -av media-plugins/gst-plugins-flac")
        elif "h264" in combined or "avc" in combined:
            logger.warning("Missing H.264 support: emerge -av media-plugins/gst-plugins-openh264")
        elif "missing" in combined or "decoder" in combined:
            logger.warning(
                "Missing codec: emerge -av media-libs/gst-plugins-good media-libs/gst-plugins-bad"
            )

    def _update_duration(self) -> bool:
        """Update track duration - called periodically until duration is found."""
        # Only query if we're not playing to avoid interfering with playback
        # During playback, rely on DURATION_CHANGED message instead
        if self.playbin and self._playback_state != PlaybackState.PLAYING:
            success, duration = self.playbin.query_duration(Gst.Format.TIME)
            if success and duration > 0:
                self.duration = duration / Gst.SECOND
                # Once we have duration, stop polling
                if self._duration_timeout_id is not None:
                    try:
                        GLib.source_remove(self._duration_timeout_id)
                    except (ValueError, TypeError):
                        pass
                    self._duration_timeout_id = None
                return False  # Stop the timeout
        # If playing, stop polling and rely on DURATION_CHANGED message
        if self._playback_state == PlaybackState.PLAYING and self._duration_timeout_id is not None:
            try:
                GLib.source_remove(self._duration_timeout_id)
            except (ValueError, TypeError):
                pass
            self._duration_timeout_id = None
            return False
        return True  # Keep polling if not playing and no duration yet

    def _update_position(self) -> bool:
        """Update playback position (called periodically)."""
        if self.playbin and self._playback_state == PlaybackState.PLAYING:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
                # Position changed - PlaybackController will poll for updates
            return True
        # Not playing - return False to stop timeout, and clear the ID
        # This prevents warnings when we try to remove it manually later
        self._position_timeout_id = None
        return False

    def load_track(self, track: TrackMetadata) -> bool:
        """Load a track for playback."""
        if not track or not track.file_path:
            return False

        if not Path(track.file_path).exists():
            logger.error("File not found: %s", track.file_path)
            return False

        # Set state to loading
        self._playback_state = PlaybackState.LOADING

        # Stop current playback
        self._stop()

        # Configure video flag based on file type
        is_video = is_video_file(track.file_path)
        try:
            if is_video:
                # Video + Audio + Soft Volume
                self.playbin.set_property(
                    "flags", GST_FLAG_VIDEO | GST_FLAG_AUDIO | GST_FLAG_SOFT_VOLUME
                )
            else:
                # Audio + Soft Volume (no video)
                self.playbin.set_property("flags", GST_FLAG_AUDIO | GST_FLAG_SOFT_VOLUME)
        except (AttributeError, TypeError):
            # Ignore errors setting flags (playbin might not support this property)
            pass

        self.current_track = track

        # Set URI
        file_uri = "file://" + str(Path(track.file_path).resolve())
        self.playbin.set_property("uri", file_uri)

        # Use track duration if available
        if track.duration:
            self.duration = track.duration

        # Prepare playback
        ret = self.playbin.set_state(Gst.State.PAUSED)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to load track: %s", track.file_path)
            self._playback_state = PlaybackState.STOPPED
            return False

        # Track loaded successfully, now paused
        self._playback_state = PlaybackState.PAUSED

        # Track loaded - PlaybackController will poll for updates

        return True

    def play(self) -> bool:
        """Start or resume playback."""
        if not self.playbin or not self.current_track:
            return False

        # Allow play from PAUSED, STOPPED, or LOADING states
        # SEEKING state will transition naturally via STATE_CHANGED message
        if self._playback_state not in (
            PlaybackState.PAUSED,
            PlaybackState.STOPPED,
            PlaybackState.LOADING,
        ):
            return False

        ret = self.playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            logger.error("Failed to start playback")
            return False

        # State will be updated by STATE_CHANGED message
        # Remove any existing position timeout before adding a new one
        if self._position_timeout_id is not None and self._position_timeout_id > 0:
            try:
                GLib.source_remove(self._position_timeout_id)
            except (ValueError, TypeError):
                # Source was already removed (e.g., callback returned False)
                pass
        self._position_timeout_id = GLib.timeout_add(
            POSITION_UPDATE_INTERVAL, self._update_position
        )
        return True

    def pause(self) -> None:
        """Pause playback."""
        # Allow pause from PLAYING or SEEKING states
        if self.playbin and self._playback_state in (PlaybackState.PLAYING, PlaybackState.SEEKING):
            self.playbin.set_state(Gst.State.PAUSED)
            # State will be updated by STATE_CHANGED message

    def stop(self) -> None:
        """Stop playback."""
        self._stop()

    def _stop(self):
        """Internal stop."""
        # Remove timeout callbacks
        # Note: Timeout may have already been removed if callback returned False
        if self._position_timeout_id is not None and self._position_timeout_id > 0:
            try:
                GLib.source_remove(self._position_timeout_id)
            except (ValueError, TypeError):
                # Source was already removed (e.g., callback returned False)
                pass
            self._position_timeout_id = None
        if self._duration_timeout_id is not None and self._duration_timeout_id > 0:
            try:
                GLib.source_remove(self._duration_timeout_id)
            except (ValueError, TypeError):
                # Source was already removed (e.g., callback returned False)
                pass
            self._duration_timeout_id = None

        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
        self.position = 0.0
        self._playback_state = PlaybackState.STOPPED

    def seek(self, position: float) -> None:
        """
        Seek to position in seconds.

        Uses explicit state machine to prevent race conditions with position updates.

        Args:
            position: Position in seconds (will be clamped to valid range)
        """
        if not self.playbin or self.duration <= 0:
            return

        # Only allow seek if we have a loaded track (not STOPPED or LOADING)
        if self._playback_state in (PlaybackState.STOPPED, PlaybackState.LOADING):
            return

        # Set seeking state to prevent position updates from interfering
        self._playback_state = PlaybackState.SEEKING

        try:
            # Clamp position to valid range
            position = max(0.0, min(position, self.duration))
            success = self.playbin.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                int(position * Gst.SECOND),
            )
            if success:
                self.position = position
            else:
                logger.warning("Seek failed for position %.2fs", position)
        finally:
            # Don't restore state here - let STATE_CHANGED message handle it
            # This prevents race conditions where we restore to wrong state
            # State restored by STATE_CHANGED message
            pass

    def set_volume(self, volume: float) -> None:
        """
        Set volume (0.0 to 1.0).

        NOTE: This method is not used in the application. System volume is
        controlled separately via the SystemVolume class. This method is kept
        for potential future use or API compatibility.

        Args:
            volume: Volume level from 0.0 to 1.0 (will be clamped)
        """
        self.volume = max(0.0, min(1.0, volume))
        if self.playbin:
            self.playbin.set_property("volume", self.volume)

    def get_volume(self) -> float:
        """
        Get current volume.

        NOTE: This method is not used in the application. System volume is
        controlled separately via the SystemVolume class. This method is kept
        for potential future use or API compatibility.
        """
        return self.volume

    def get_position(self) -> float:
        """Get current position in seconds."""
        if self.playbin and self._playback_state == PlaybackState.PLAYING:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
        return self.position

    @property
    def is_playing(self) -> bool:
        """Check if currently playing (backward compatibility)."""
        return self._playback_state == PlaybackState.PLAYING

    def get_duration(self) -> float:
        """Get track duration in seconds."""
        if self.current_track and self.current_track.duration:
            return self.current_track.duration
        return self.duration

    def cleanup(self) -> None:
        """
        Clean up resources.

        Stops playback, removes signal watches, and releases GStreamer elements.
        Should be called when the player is no longer needed.
        """
        self._stop()

        # Clean up audio effects
        self.audio_effects.cleanup()

        # Remove bus signal watch if playbin exists
        if self.playbin:
            try:
                bus = self.playbin.get_bus()
                if bus:
                    bus.remove_signal_watch()
            except (AttributeError, RuntimeError):
                # Bus may already be destroyed
                pass

            self.playbin.set_state(Gst.State.NULL)
            self.playbin = None
