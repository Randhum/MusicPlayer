"""Centralized application state management - single source of truth."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from enum import Enum
from typing import List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)


class PlaybackState(Enum):
    """State machine for playback operations."""

    STOPPED = "stopped"  # No track loaded or stopped
    LOADING = "loading"  # Track is being loaded
    PAUSED = "paused"  # Track loaded but paused
    PLAYING = "playing"  # Track is playing
    SEEKING = "seeking"  # Seek operation in progress


class AppState:
    """
    Single source of truth for application state.

    All state changes go through this class, which publishes events
    via EventBus to notify subscribers of changes.
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize application state.

        Args:
            event_bus: EventBus instance for publishing state changes
        """
        self._event_bus = event_bus

        # Playlist state
        self._playlist: List[TrackMetadata] = []
        self._current_index: int = -1

        # Playback state
        self._playback_state: PlaybackState = PlaybackState.STOPPED
        self._active_backend: str = "none"  # "none", "moc", "internal", "bt_sink"
        self._position: float = 0.0
        self._duration: float = 0.0
        self._current_track: Optional[TrackMetadata] = None

        # Playback options
        self._shuffle_enabled: bool = False
        self._loop_mode: int = 0  # 0=forward, 1=track, 2=playlist
        self._autonext_enabled: bool = True

        # Volume
        self._volume: float = 1.0

    # ============================================================================
    # Playlist Properties
    # ============================================================================

    @property
    def playlist(self) -> List[TrackMetadata]:
        """Get the current playlist (read-only copy)."""
        return self._playlist.copy()

    @property
    def current_index(self) -> int:
        """Get the current track index."""
        return self._current_index

    @property
    def current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track."""
        # Return stored reference to ensure consistency
        # The stored reference is updated by set_current_index and set_playlist
        return self._current_track
        return None

    def set_playlist(
        self, tracks: List[TrackMetadata], current_index: int = -1
    ) -> None:
        """
        Set the playlist and current index.

        Args:
            tracks: List of tracks
            current_index: Current track index (-1 for none)
        """
        self._playlist = tracks
        # Clamp current_index to valid range
        if current_index < -1 or current_index >= len(tracks):
            current_index = -1
        self._current_index = current_index

        # Update current_track if index is valid
        if 0 <= current_index < len(tracks):
            self._current_track = tracks[current_index]
        else:
            self._current_track = None

        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {"tracks": self._playlist, "index": current_index},
        )

    def set_current_index(self, index: int) -> None:
        """
        Set the current track index.

        Args:
            index: Track index (-1 for none)
        """
        if index < -1 or index >= len(self._playlist):
            index = -1

        old_index = self._current_index
        old_track = self._current_track
        self._current_index = index

        # Update current_track
        if 0 <= index < len(self._playlist):
            new_track = self._playlist[index]
            self._current_track = new_track
        else:
            new_track = None
            self._current_track = None

        if old_index != index:
            self._event_bus.publish(
                EventBus.CURRENT_INDEX_CHANGED, {"index": index, "old_index": old_index}
            )
            # Always publish TRACK_CHANGED when index changes to ensure labels update
            # Even if the track object reference is the same, the index changed so UI should update
            if new_track:
                self._event_bus.publish(
                    EventBus.TRACK_CHANGED, {"track": new_track}
                )
            elif old_track:
                # Track was cleared
                self._event_bus.publish(EventBus.TRACK_CHANGED, {"track": None})

    def add_track(self, track: TrackMetadata, position: Optional[int] = None) -> None:
        """
        Add a track to the playlist.

        Args:
            track: Track to add
            position: Insert position (None appends to end)
        """
        if position is None:
            self._playlist.append(track)
        else:
            self._playlist.insert(position, track)
            # Adjust current_index if needed
            if position <= self._current_index:
                self._current_index += 1
                # Update current_track reference
                if 0 <= self._current_index < len(self._playlist):
                    self._current_track = self._playlist[self._current_index]

        self._event_bus.publish(
            EventBus.PLAYLIST_TRACK_ADDED,
            {"track": track, "position": position or len(self._playlist) - 1},
        )
        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {"tracks": self._playlist, "index": self._current_index},
        )

    def add_tracks(
        self, tracks: List[TrackMetadata], position: Optional[int] = None
    ) -> None:
        """
        Add multiple tracks to the playlist (batch operation).

        Args:
            tracks: List of tracks to add
            position: Insert position (None appends to end)
        """
        if not tracks:
            return

        if position is None:
            # Append all tracks
            self._playlist.extend(tracks)
        else:
            # Insert all tracks at position
            for i, track in enumerate(tracks):
                self._playlist.insert(position + i, track)
            # Adjust current_index if needed
            if position <= self._current_index:
                self._current_index += len(tracks)
                # Update current_track reference
                if 0 <= self._current_index < len(self._playlist):
                    self._current_track = self._playlist[self._current_index]

        # Publish events once for the batch operation
        # Note: We don't publish individual PLAYLIST_TRACK_ADDED events for each track
        # to avoid flooding the event bus. The PLAYLIST_CHANGED event is sufficient.
        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {"tracks": self._playlist, "index": self._current_index},
        )

    def remove_track(self, index: int) -> None:
        """
        Remove a track from the playlist.

        Args:
            index: Index of track to remove
        """
        if not (0 <= index < len(self._playlist)):
            return

        removed_track = self._playlist.pop(index)

        # Adjust current_index if needed
        if index < self._current_index:
            self._current_index -= 1
            # Update current_track reference
            if 0 <= self._current_index < len(self._playlist):
                self._current_track = self._playlist[self._current_index]
        elif index == self._current_index:
            self._current_index = -1
            self._current_track = None

        self._event_bus.publish(
            EventBus.PLAYLIST_TRACK_REMOVED, {"index": index, "track": removed_track}
        )
        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {"tracks": self._playlist, "index": self._current_index},
        )

    def move_track(self, from_index: int, to_index: int) -> None:
        """
        Move a track from one position to another.

        Args:
            from_index: Source position
            to_index: Destination position
        """
        if not (
            0 <= from_index < len(self._playlist)
            and 0 <= to_index < len(self._playlist)
        ):
            return

        track = self._playlist.pop(from_index)
        # When moving down (from_index < to_index), adjust insert position
        # because pop() shifted all elements after from_index down by 1
        if from_index < to_index:
            insert_index = to_index - 1
        else:
            insert_index = to_index
        self._playlist.insert(insert_index, track)

        # Update current_index
        if self._current_index == from_index:
            self._current_index = to_index
            # Update current_track reference
            if 0 <= self._current_index < len(self._playlist):
                self._current_track = self._playlist[self._current_index]
        elif from_index < self._current_index <= to_index:
            self._current_index -= 1
            # Update current_track reference
            if 0 <= self._current_index < len(self._playlist):
                self._current_track = self._playlist[self._current_index]
        elif to_index <= self._current_index < from_index:
            self._current_index += 1
            # Update current_track reference
            if 0 <= self._current_index < len(self._playlist):
                self._current_track = self._playlist[self._current_index]

        self._event_bus.publish(
            EventBus.PLAYLIST_TRACK_MOVED,
            {"from_index": from_index, "to_index": to_index},
        )
        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {"tracks": self._playlist, "index": self._current_index},
        )

    def clear_playlist(self) -> None:
        """Clear the playlist."""
        self._playlist.clear()
        self._current_index = -1
        self._current_track = None
        self._event_bus.publish(EventBus.PLAYLIST_CLEARED, {})
        self._event_bus.publish(EventBus.PLAYLIST_CHANGED, {"tracks": [], "index": -1})

    # ============================================================================
    # Playback State Properties
    # ============================================================================

    @property
    def playback_state(self) -> PlaybackState:
        """Get the current playback state."""
        return self._playback_state

    @property
    def active_backend(self) -> str:
        """Get the active playback backend."""
        return self._active_backend

    @property
    def position(self) -> float:
        """Get the current playback position in seconds."""
        return self._position

    @property
    def duration(self) -> float:
        """Get the current track duration in seconds."""
        return self._duration

    def set_playback_state(self, state: PlaybackState) -> None:
        """
        Set the playback state.

        Args:
            state: New playback state
        """
        old_state = self._playback_state
        self._playback_state = state

        # Publish appropriate event based on state change
        if state == PlaybackState.PLAYING and old_state != PlaybackState.PLAYING:
            self._event_bus.publish(
                EventBus.PLAYBACK_STARTED, {"track": self._current_track}
            )
        elif state == PlaybackState.PAUSED and old_state == PlaybackState.PLAYING:
            self._event_bus.publish(EventBus.PLAYBACK_PAUSED, {})
        elif state == PlaybackState.STOPPED and old_state != PlaybackState.STOPPED:
            self._event_bus.publish(EventBus.PLAYBACK_STOPPED, {})

    def set_active_backend(self, backend: str) -> None:
        """
        Set the active playback backend.

        Args:
            backend: Backend name ("none", "moc", "internal", "bt_sink")
        """
        self._active_backend = backend

    def set_position(self, position: float) -> None:
        """
        Set the playback position.

        Args:
            position: Position in seconds
        """
        self._position = max(0.0, position)
        self._event_bus.publish(
            EventBus.POSITION_CHANGED,
            {"position": self._position, "duration": self._duration},
        )

    def set_duration(self, duration: float) -> None:
        """
        Set the track duration.

        Args:
            duration: Duration in seconds
        """
        self._duration = max(0.0, duration)
        self._event_bus.publish(EventBus.DURATION_CHANGED, {"duration": self._duration})

    def set_current_track(self, track: Optional[TrackMetadata]) -> None:
        """
        Set the current track.

        Args:
            track: Current track or None
        """
        self._current_track = track
        if track:
            self._event_bus.publish(EventBus.TRACK_CHANGED, {"track": track})

    # ============================================================================
    # Playback Options Properties
    # ============================================================================

    @property
    def shuffle_enabled(self) -> bool:
        """Get shuffle state."""
        return self._shuffle_enabled

    @property
    def loop_mode(self) -> int:
        """Get loop mode (0=forward, 1=track, 2=playlist)."""
        return self._loop_mode

    @property
    def autonext_enabled(self) -> bool:
        """Get autonext state."""
        return self._autonext_enabled

    def set_shuffle_enabled(self, enabled: bool) -> None:
        """
        Set shuffle state.

        Args:
            enabled: True to enable shuffle
        """
        if self._shuffle_enabled != enabled:
            self._shuffle_enabled = enabled
            self._event_bus.publish(EventBus.SHUFFLE_CHANGED, {"enabled": enabled})

    def set_loop_mode(self, mode: int) -> None:
        """
        Set loop mode.

        Args:
            mode: Loop mode (0=forward, 1=track, 2=playlist)
        """
        if 0 <= mode <= 2 and self._loop_mode != mode:
            self._loop_mode = mode
            self._event_bus.publish(EventBus.LOOP_MODE_CHANGED, {"mode": mode})

    def set_autonext_enabled(self, enabled: bool) -> None:
        """
        Set autonext state.

        Args:
            enabled: True to enable autonext
        """
        if self._autonext_enabled != enabled:
            self._autonext_enabled = enabled
            self._event_bus.publish(EventBus.AUTONEXT_CHANGED, {"enabled": enabled})

    # ============================================================================
    # Volume Properties
    # ============================================================================

    @property
    def volume(self) -> float:
        """Get the volume (0.0 to 1.0)."""
        return self._volume

    def set_volume(self, volume: float) -> None:
        """
        Set the volume.

        Args:
            volume: Volume level (0.0 to 1.0, will be clamped)
        """
        new_volume = max(0.0, min(1.0, volume))
        if abs(self._volume - new_volume) > 0.001:  # Avoid floating point noise
            self._volume = new_volume
            self._event_bus.publish(EventBus.VOLUME_CHANGED, {"volume": self._volume})
