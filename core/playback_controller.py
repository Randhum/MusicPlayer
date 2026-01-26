"""Playback controller - routes playback commands to appropriate backends."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import random
import time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.app_state import AppState, PlaybackState
from core.audio_player import AudioPlayer
from core.bluetooth_sink import BluetoothSink
from core.config import get_config
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.workflow_utils import is_video_file, normalize_path

logger = get_logger(__name__)


class OperationState(Enum):
    """State machine for playback operations to prevent race conditions."""

    IDLE = "idle"
    SEEKING = "seeking"
    SYNCING = "syncing"


# MOC status update interval (milliseconds)
MOC_STATUS_UPDATE_INTERVAL = 500


class PlaybackController:
    """
    Mediator that routes playback commands to appropriate backends.

    Handles:
    - Backend selection (MOC, internal player, BT sink)
    - MOC status polling and state synchronization
    - Track change detection
    - Playlist synchronization with MOC
    - Ensuring only one backend is active at a time
    """

    def __init__(
        self,
        app_state: AppState,
        event_bus: EventBus,
        internal_player: AudioPlayer,
        moc_controller: MocController,
        bt_sink: Optional[BluetoothSink] = None,
    ):
        """
        Initialize playback controller.

        Args:
            app_state: AppState instance
            event_bus: EventBus instance
            internal_player: AudioPlayer instance for video files
            moc_controller: MocController instance for audio files
            bt_sink: Optional BluetoothSink instance
        """
        self._state = app_state
        self._events = event_bus
        self._internal_player = internal_player
        self._moc_controller = moc_controller
        self._bt_sink = bt_sink

        self._use_moc = moc_controller.is_available()
        self._operation_state = OperationState.IDLE

        # MOC tracking state
        self._moc_last_file: Optional[str] = None
        self._moc_playlist_mtime: float = 0.0
        self._recent_moc_write: Optional[float] = None
        self._recent_shuffle_write: Optional[float] = (
            None  # Guard to prevent circular shuffle sync
        )
        self._loading_from_moc: bool = False  # Guard to prevent circular sync
        self._syncing_to_moc: bool = False  # Guard to prevent concurrent syncs
        self._user_action_time: float = 0.0  # Timestamp of last user-initiated action

        # Shuffle queue management (for both MOC and internal player)
        self._shuffle_queue: List[int] = (
            []
        )  # Queue of shuffled indices for shuffle mode

        # Initialize playlist mtime if file exists
        if self._use_moc:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if moc_playlist_path.exists():
                try:
                    self._moc_playlist_mtime = moc_playlist_path.stat().st_mtime
                except OSError:
                    self._moc_playlist_mtime = 0.0

        # Subscribe to action events
        self._events.subscribe(EventBus.ACTION_PLAY, self._on_action_play)
        self._events.subscribe(EventBus.ACTION_PAUSE, self._on_action_pause)
        self._events.subscribe(EventBus.ACTION_STOP, self._on_action_stop)
        self._events.subscribe(EventBus.ACTION_NEXT, self._on_action_next)
        self._events.subscribe(EventBus.ACTION_PREV, self._on_action_previous)
        self._events.subscribe(EventBus.ACTION_SEEK, self._on_action_seek)
        self._events.subscribe(EventBus.ACTION_PLAY_TRACK, self._on_action_play_track)
        self._events.subscribe(EventBus.ACTION_SET_SHUFFLE, self._on_action_set_shuffle)
        self._events.subscribe(
            EventBus.ACTION_SET_LOOP_MODE, self._on_action_set_loop_mode
        )
        self._events.subscribe(EventBus.ACTION_SET_VOLUME, self._on_action_set_volume)
        self._events.subscribe(EventBus.ACTION_REFRESH_MOC, self._on_action_refresh_moc)
        self._events.subscribe(
            EventBus.ACTION_APPEND_FOLDER, self._on_action_append_folder
        )

        # Subscribe to playlist changes to sync with MOC
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)

        # Subscribe to shuffle changes to regenerate shuffle queue
        self._events.subscribe(EventBus.SHUFFLE_CHANGED, self._on_shuffle_changed)

        # Initialize shuffle queue if shuffle is enabled
        if self._state.shuffle_enabled:
            self._regenerate_shuffle_queue()

        # Subscribe to BT events
        if bt_sink:
            self._events.subscribe(EventBus.BT_SINK_ENABLED, self._on_bt_sink_enabled)
            self._events.subscribe(EventBus.BT_SINK_DISABLED, self._on_bt_sink_disabled)
            self._events.subscribe(
                EventBus.BT_SINK_DEVICE_CONNECTED, self._on_bt_sink_device_connected
            )

        # Start MOC polling if available
        if self._use_moc:
            GLib.timeout_add(1000, self._initialize_moc)  # Delay initialization
            GLib.timeout_add(MOC_STATUS_UPDATE_INTERVAL, self._poll_moc_status)

        # Start internal player polling
        GLib.timeout_add(500, self._poll_internal_player_status)  # 500ms interval

    def _initialize_moc(self) -> bool:
        """Initialize MOC server and settings."""
        if not self._use_moc:
            return False

        if self._moc_controller.ensure_server():
            # Disable MOC's autonext - we handle track navigation ourselves
            self._moc_controller.disable_autonext()
            # Sync shuffle state from MOC
            moc_shuffle = self._moc_controller.get_shuffle_state()
            if moc_shuffle is not None:
                self._state.set_shuffle_enabled(moc_shuffle)
            
            # Check if MOC playlist is empty but we have tracks in internal playlist
            # Only sync if:
            # 1. We haven't written to MOC recently (avoid race with startup sync)
            # 2. We're not currently loading from MOC (avoid circular sync)
            # 3. We're not already syncing (avoid concurrent syncs)
            tracks, _ = self._moc_controller.get_playlist()
            if not tracks:
                # Check if we recently wrote to MOC (within last 2 seconds) - if so, skip to avoid race
                recent_write = self._recent_moc_write and (time.time() - self._recent_moc_write < 2.0)
                if not recent_write and not self._loading_from_moc and not self._syncing_to_moc:
                    internal_tracks = self._state.playlist
                    if internal_tracks:
                        logger.info(
                            "MOC playlist is empty on initialization, writing internal playlist (%d tracks) to MOC",
                            len(internal_tracks)
                        )
                        GLib.idle_add(self._sync_moc_playlist, False)
            
            return False  # Don't repeat

        return False

    def _should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Check if MOC should be used for this track."""
        if not self._use_moc or not track or not track.file_path:
            return False
        return not is_video_file(track.file_path)

    def _should_use_bt_sink(self) -> bool:
        """Check if BT sink should be used (takes priority)."""
        return (
            self._bt_sink
            and self._bt_sink.is_sink_enabled
            and self._bt_sink.connected_device is not None
        )

    def _stop_inactive_backends(self) -> None:
        """Ensure only one backend is active at a time."""
        active_backend = self._state.active_backend

        # Stop internal player if not active
        if active_backend != "internal" and (
            self._internal_player.is_playing or self._internal_player.current_track
        ):
            self._internal_player.stop()

        # Stop MOC if not active
        if active_backend != "moc" and self._use_moc:
            status = self._moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self._moc_controller.stop()

    # ============================================================================
    # Action Handlers
    # ============================================================================

    def _on_action_play(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play action."""
        # Check BT sink first (takes priority)
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("play")
            return

        track = self._state.current_track
        if not track:
            # No current track - try to play first track
            playlist = self._state.playlist
            if playlist:
                self._state.set_current_index(0)
                track = self._state.current_track

        # Validate track exists and has valid file path
        if not track or not track.file_path:
            logger.warning("Cannot play - no valid track or file path")
            return

        # Verify file exists
        track_path = Path(track.file_path)
        if not track_path.exists() or not track_path.is_file():
            logger.warning("Cannot play - file does not exist: %s", track.file_path)
            return

        # Mark user action time to prevent poll interference
        self._user_action_time = time.time()

        # Stop inactive backends
        self._stop_inactive_backends()

        if self._should_use_moc(track):
            self._play_with_moc(track)
        else:
            self._play_with_internal(track)

    def _on_action_pause(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle pause action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("pause")
            return

        active_backend = self._state.active_backend
        if active_backend == "moc":
            self._moc_controller.pause()
            self._state.set_playback_state(PlaybackState.PAUSED)
        elif active_backend == "internal":
            self._internal_player.pause()
            self._state.set_playback_state(PlaybackState.PAUSED)

    def _on_action_stop(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle stop action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("stop")
            return

        active_backend = self._state.active_backend
        if active_backend == "moc":
            self._moc_controller.stop()
        elif active_backend == "internal":
            self._internal_player.stop()

        self._state.set_current_index(-1)
        self._state.set_playback_state(PlaybackState.STOPPED)
        self._state.set_active_backend("none")
        # Reset timeline to 00:00
        self._state.set_position(0.0)
        self._state.set_duration(0.0)

    def _on_action_next(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle next track action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("next")
            return

        playlist = self._state.playlist
        if not playlist:
            return

        # Use shuffle queue if shuffle is enabled
        if self._state.shuffle_enabled:
            next_index = self._get_next_shuffled_index()
        else:
            # Sequential navigation
            current_index = self._state.current_index
            next_index = current_index + 1 if current_index < len(playlist) - 1 else -1

        if next_index >= 0:
            self._state.set_current_index(next_index)
            self._on_action_play(None)

    def _on_action_previous(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle previous track action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("prev")
            return

        current_index = self._state.current_index
        if current_index > 0:
            self._state.set_current_index(current_index - 1)
            self._on_action_play(None)

    def _on_action_seek(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle seek action."""
        if not data or "position" not in data:
            return

        position = float(data["position"])

        if self._should_use_bt_sink():
            # BT sink doesn't support seeking
            return

        # Mark user action time to prevent poll interference during seek
        self._user_action_time = time.time()
        self._operation_state = OperationState.SEEKING

        active_backend = self._state.active_backend
        if active_backend == "moc":
            self._seek_moc(position)
        elif active_backend == "internal":
            self._internal_player.seek(position)
            # For internal player, reset state immediately after seek
            # Internal player updates position synchronously
            GLib.timeout_add(100, self._reset_seek_state)  # Short delay for consistency

    def _on_action_play_track(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play specific track action."""
        if not data or "index" not in data:
            return

        index = int(data["index"])
        # Index is already set by PlaylistView.play_track_at_index() - don't set again
        # Mark user action time to prevent poll interference
        self._user_action_time = time.time()
        self._on_action_play(None)

    def _on_action_set_shuffle(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set shuffle action."""
        if not data or "enabled" not in data:
            return

        enabled = bool(data["enabled"])
        self._state.set_shuffle_enabled(enabled)

        # Sync to MOC if using MOC
        if self._use_moc:
            if enabled:
                self._moc_controller.enable_shuffle()
            else:
                self._moc_controller.disable_shuffle()
            # Track when we modified shuffle in MOC
            self._recent_shuffle_write = time.time()

    def _on_action_set_loop_mode(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set loop mode action."""
        if not data or "mode" not in data:
            return

        mode = int(data["mode"])
        self._state.set_loop_mode(mode)

    def _on_action_set_volume(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set volume action."""
        if not data or "volume" not in data:
            return

        volume = float(data["volume"])
        self._state.set_volume(volume)

        # Volume is controlled by SystemVolume, not by backends
        # The SystemVolume class will handle the actual volume change

    def _on_action_refresh_moc(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle refresh from MOC action - reload playlist from MOC."""
        if not self._use_moc:
            logger.debug("Refresh MOC requested but MOC mode not active")
            return

        # Sync MOC's in-memory playlist to disk first
        self._moc_controller.sync_playlist()
        
        # Wait a moment for MOC to finish writing the file
        # MOC writes asynchronously, so we need to wait for the file to be updated
        if self._use_moc:
            GLib.timeout_add(100, self._do_refresh_moc_after_sync)
    
    def _do_refresh_moc_after_sync(self) -> bool:
        """Actually refresh playlist from MOC after sync has completed."""
        # Get config and playlist path first
        config = get_config()
        moc_playlist_path = config.moc_playlist_path
        
        # Get current playing file from MOC status
        status = self._moc_controller.get_status(force_refresh=True)
        current_file = status.get("file_path") if status else None

        # Load playlist from MOC's M3U file
        tracks, current_index = self._moc_controller.get_playlist(
            current_file=current_file
        )
        if tracks:
            logger.info("Refreshed playlist from MOC: %d tracks, current_index=%d", len(tracks), current_index)
            # Set flag to prevent circular sync back to MOC
            try:
                self._loading_from_moc = True
                # Update AppState (source of truth) - this publishes PLAYLIST_CHANGED event
                self._state.set_playlist(tracks, current_index)
            finally:
                self._loading_from_moc = False
            
            # Sync to PlaylistManager to keep file in sync
            # Get PlaylistManager from the event bus or app (we need access to it)
            # Actually, PlaylistManager sync should happen via the PLAYLIST_CHANGED event
            # But we need to ensure current_index is synced too
            # The event handler in PlaylistView will update the UI, but we should also
            # sync PlaylistManager's current_index from AppState
            
            # Update mtime to prevent duplicate reload from polling
            if moc_playlist_path.exists():
                self._moc_playlist_mtime = moc_playlist_path.stat().st_mtime
        else:
            # Check if MOC actually has tracks by checking the playlist file directly
            file_has_content = False
            if moc_playlist_path.exists():
                try:
                    # Read file directly to see if it has content
                    with moc_playlist_path.open("r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        # Check if file has actual track entries (not just header)
                        lines = [line.strip() for line in content.splitlines() if line.strip()]
                        has_tracks = any(
                            line and not line.startswith("#EXTM3U") and not line.startswith("#EXTINF")
                            for line in lines
                        )
                        if has_tracks:
                            file_has_content = True
                            # File has content but parsing failed - this is the real issue
                            logger.warning(
                                "MOC playlist file exists and has track entries (%d lines), "
                                "but no valid tracks were parsed. This might indicate a path resolution issue. "
                                "Using internal playlist state instead.",
                                len(lines)
                            )
                            # Fallback: use our internal playlist state since MOC has tracks but we can't parse them
                            internal_tracks = self._state.playlist
                            if internal_tracks:
                                logger.info(
                                    "Using internal playlist state (%d tracks) instead of MOC file",
                                    len(internal_tracks)
                                )
                                # Don't update state (it's already correct), just update mtime
                                if moc_playlist_path.exists():
                                    self._moc_playlist_mtime = moc_playlist_path.stat().st_mtime
                        else:
                            # File is empty or only has header
                            logger.debug("MOC playlist file is empty or only contains header")
                except Exception as e:
                    logger.debug("Could not read MOC playlist file to verify: %s", e)
            
            if not file_has_content:
                # File doesn't exist or is empty - MOC might not have synced yet or playlist is actually empty
                logger.warning(
                    "No tracks found in MOC playlist. "
                    "This might be a timing issue (MOC hasn't written file yet) or the playlist is empty."
                )
                # If we have tracks in the internal playlist, write them to MOC
                # Only if we're not already syncing or loading from MOC
                if not self._syncing_to_moc and not self._loading_from_moc:
                    internal_tracks = self._state.playlist
                    if internal_tracks:
                        logger.info(
                            "Writing internal playlist (%d tracks) to MOC",
                            len(internal_tracks)
                        )
                        GLib.idle_add(self._sync_moc_playlist, False)
        
        return False  # Don't repeat

    def _on_action_append_folder(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle append folder action - add folder to MOC playlist."""
        if not self._use_moc or not data or "folder_path" not in data:
            return

        folder_path = data["folder_path"]
        if not folder_path:
            return

        # Use MOC's native append command for folders (recursively adds all tracks)
        if self._moc_controller.append_to_playlist(folder_path):
            logger.info("Appended folder to MOC playlist: %s", folder_path)
            # Mark that we modified MOC (prevents polling from reloading immediately)
            self._recent_moc_write = time.time()
            # Let polling mechanism handle the reload naturally after MOC writes the file
            # This is more efficient than doing a full refresh immediately
            # The polling will detect the mtime change after 0.5 seconds
        else:
            logger.warning("Failed to append folder to MOC playlist: %s", folder_path)

    # ============================================================================
    # Playback Methods
    # ============================================================================

    def _play_with_moc(self, track: TrackMetadata) -> None:
        """Play track using MOC."""
        if not self._use_moc:
            return

        # CRITICAL: Set _moc_last_file FIRST so track-end detection works
        # Without this, file_path == _moc_last_file is always False
        if track and track.file_path:
            self._moc_last_file = str(Path(track.file_path).resolve())

        # Set state before playing
        self._state.set_active_backend("moc")
        self._state.set_current_track(track)

        # Just play the file - MOC's --playit will add it to playlist if needed
        # This is fast and doesn't require full playlist sync
        if track and track.file_path:
            self._moc_controller.play_file(track.file_path)

        # Set playback state (optimistic - assume play will succeed)
        self._state.set_playback_state(PlaybackState.PLAYING)

    def _play_with_internal(self, track: TrackMetadata) -> None:
        """Play track using internal player."""
        self._internal_player.load_track(track)
        self._internal_player.play()

        # Set state
        self._state.set_active_backend("internal")
        self._state.set_playback_state(PlaybackState.PLAYING)
        self._state.set_current_track(track)

        # Update duration from track metadata
        if track.duration:
            self._state.set_duration(track.duration)

    def _seek_moc(self, position: float) -> None:
        """Seek in MOC."""
        if not self._use_moc:
            return

        # Note: _user_action_time and _operation_state are already set by _on_action_seek
        # This method is only called from _on_action_seek, so we don't need to set them again

        try:
            # Get current position from MOC
            status = self._moc_controller.get_status(force_refresh=True)
            if not status:
                return

            current_pos = float(status.get("position", 0.0))
            duration = float(status.get("duration", 0.0))

            # Clamp position
            if duration > 0:
                position = max(0.0, min(position, duration))
            else:
                position = max(0.0, position)

            # Calculate delta
            delta = position - current_pos

            # Only seek if delta is significant
            if abs(delta) >= 0.5:
                self._moc_controller.seek_relative(delta)
                # Set position optimistically - MOC will move to this position
                self._state.set_position(position)
        finally:
            # Keep operation state as SEEKING briefly to prevent poll from overwriting
            # The poll will skip position updates while SEEKING
            # We'll reset to IDLE after a short delay to allow MOC to catch up
            GLib.timeout_add(200, self._reset_seek_state)  # 200ms delay

    # ============================================================================
    # MOC Synchronization
    # ============================================================================

    def _sync_moc_playlist(self, start_playback: bool = False) -> bool:
        """
        Sync playlist to MOC using native MOC commands.
        
        Returns:
            False to indicate this is a one-time callback (for GLib.idle_add)
        """
        if not self._use_moc:
            return False

        # Prevent concurrent syncs
        if self._syncing_to_moc:
            logger.debug("MOC sync already in progress, skipping duplicate sync")
            return False

        self._syncing_to_moc = True
        try:
            playlist = self._state.playlist
            current_index = self._state.current_index
            track = self._state.current_track

            # Only start playback if track is audio (not video)
            should_start = (
                start_playback and track is not None and not is_video_file(track.file_path)
            )

            # Use MOC's native commands to set the playlist
            # This keeps MOC's internal state in sync
            # Note: This does many --append commands which can be slow for large playlists
            self._moc_controller.set_playlist(
                playlist, current_index, start_playback=should_start
            )

            # Track when we modified MOC
            self._recent_moc_write = time.time()

            # Update playlist mtime (MOC will write to the file after our commands)
            try:
                config = get_config()
                moc_playlist_path = config.moc_playlist_path
                if moc_playlist_path.exists():
                    self._moc_playlist_mtime = moc_playlist_path.stat().st_mtime
            except OSError:
                pass
        finally:
            self._syncing_to_moc = False
        
        return False  # Don't repeat

    def _on_playlist_changed(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle playlist change - sync to MOC if using MOC and regenerate shuffle queue."""
        # Only sync TO MOC if we're not currently loading FROM MOC and not already syncing
        # This prevents circular sync issues and concurrent syncs
        if (
            self._use_moc
            and self._state.active_backend == "moc"
            and not self._loading_from_moc
            and not self._syncing_to_moc
        ):
            # Defer MOC sync to avoid blocking UI (set_playlist does many --append commands)
            GLib.idle_add(self._sync_moc_playlist, False)

        # Regenerate shuffle queue when playlist changes
        if self._state.shuffle_enabled:
            self._regenerate_shuffle_queue()

    def _on_shuffle_changed(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle shuffle state change - regenerate shuffle queue."""
        if data and data.get("enabled", False):
            self._regenerate_shuffle_queue()
        else:
            # Clear shuffle queue when shuffle is disabled
            self._shuffle_queue = []

    def _get_next_shuffled_index(self) -> int:
        """Get next index from shuffle queue."""
        playlist = self._state.playlist
        if not playlist:
            return -1

        # If queue is empty, regenerate it
        if not self._shuffle_queue:
            self._regenerate_shuffle_queue()

        # If still empty (shouldn't happen, but handle edge case)
        if not self._shuffle_queue:
            return -1

        # Pop the next index from the queue
        return self._shuffle_queue.pop(0)

    def _regenerate_shuffle_queue(self) -> None:
        """Regenerate the shuffle queue with all playlist indices in random order."""
        playlist = self._state.playlist
        if not playlist:
            self._shuffle_queue = []
            return

        # Create a list of all indices
        indices = list(range(len(playlist)))

        # Shuffle the list
        random.shuffle(indices)

        # If there's a current track, remove it from the queue to avoid immediate repeat
        current_idx = self._state.current_index
        if 0 <= current_idx < len(playlist) and current_idx in indices:
            indices.remove(current_idx)
            # Add it at the end so it plays eventually, but not next
            indices.append(current_idx)

        self._shuffle_queue = indices

    def _poll_internal_player_status(self) -> bool:
        """Poll internal player status and update state."""
        # Only poll if internal player is the active backend
        if self._state.active_backend != "internal":
            return True  # Continue polling

        # Update position and duration
        position = self._internal_player.get_position()
        duration = self._internal_player.get_duration()

        # Update state (this will publish events)
        if self._operation_state != OperationState.SEEKING:
            self._state.set_position(position)
        if duration > 0:
            self._state.set_duration(duration)

        # Update playback state
        if self._internal_player.is_playing:
            if self._state.playback_state != PlaybackState.PLAYING:
                self._state.set_playback_state(PlaybackState.PLAYING)
        elif self._internal_player.current_track:
            if self._state.playback_state != PlaybackState.PAUSED:
                self._state.set_playback_state(PlaybackState.PAUSED)
        else:
            # Check if track finished (was playing, now stopped, position at end)
            was_playing = self._state.playback_state == PlaybackState.PLAYING
            if was_playing and duration > 0 and position >= duration - 0.5:
                # Track finished - handle auto-advance
                self._state.set_playback_state(PlaybackState.STOPPED)
                self._handle_track_finished()
            elif self._state.playback_state != PlaybackState.STOPPED:
                self._state.set_playback_state(PlaybackState.STOPPED)

        return True  # Continue polling

    def _poll_moc_status(self) -> bool:
        """Poll MOC status and update state."""
        if not self._use_moc:
            return False

        # Only poll if MOC is the active backend
        if self._state.active_backend != "moc":
            return True  # Continue polling

        status = self._moc_controller.get_status()
        if not status:
            return True  # Try again later

        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))

        # Update position and duration
        if self._operation_state != OperationState.SEEKING:
            self._state.set_position(position)
        if duration > 0:
            self._state.set_duration(duration)

        # Update playback state
        if state == "PLAY":
            if self._state.playback_state != PlaybackState.PLAYING:
                self._state.set_playback_state(PlaybackState.PLAYING)
        elif state == "PAUSE":
            if self._state.playback_state != PlaybackState.PAUSED:
                self._state.set_playback_state(PlaybackState.PAUSED)
        elif state == "STOP":
            if self._state.playback_state != PlaybackState.STOPPED:
                self._state.set_playback_state(PlaybackState.STOPPED)

        # Sync shuffle state from MOC (but skip if we just changed it ourselves)
        moc_shuffle = status.get("shuffle", False)
        if moc_shuffle != self._state.shuffle_enabled:
            # Check if we wrote it recently (within last 0.5 seconds)
            if not self._recent_shuffle_write or (
                time.time() - self._recent_shuffle_write > 0.5
            ):
                # MOC's shuffle state changed externally - update our state
                self._state.set_shuffle_enabled(moc_shuffle)

        # Detect track change - but skip if user just initiated an action (prevent interference)
        if file_path and file_path != self._moc_last_file:
            # Only handle track change if it wasn't user-initiated (within last 1 second)
            if time.time() - self._user_action_time >= 1.0:
                self._handle_moc_track_change(file_path)

        # Detect track finished (MOC stopped at end of track with autonext disabled)
        # Check for track end: state is STOP, we have duration, position is near end, and file matches
        # Also check if position reached end while playing (MOC might not stop immediately)
        track_finished = False
        if file_path == self._moc_last_file and duration > 0:
            if state == "STOP" and position >= duration - 0.5:
                # MOC stopped at end
                track_finished = True
            elif state == "PLAY" and position >= duration - 1.0:
                # Position reached end while playing - track finished, advance soon
                # Use slightly more lenient threshold (1.0s) for playing state
                track_finished = True

        if track_finished:
            # Track finished - handle auto-advance
            # Mark user action time BEFORE handling to prevent poll interference
            # This ensures the next poll (500ms later) won't interfere
            self._user_action_time = time.time()

            playlist = self._state.playlist
            # Check if there are more tracks available (considering shuffle mode)
            has_next = False
            if self._state.shuffle_enabled:
                # In shuffle mode, check if queue has tracks or can be regenerated
                if self._shuffle_queue or len(playlist) > 1:
                    has_next = True
            else:
                # Sequential mode - check if not at end
                current_index = self._state.current_index
                has_next = current_index < len(playlist) - 1

            if has_next:
                # There's a next track - advance
                self._handle_track_finished()
            else:
                # End of playlist - reset timeline
                self._state.set_playback_state(PlaybackState.STOPPED)
                self._state.set_position(0.0)
                self._state.set_duration(0.0)

        # Detect playlist file changes
        self._check_moc_playlist_changes()

        return True  # Continue polling

    def _handle_moc_track_change(self, file_path: str) -> None:
        """Handle MOC track change (auto-advancement)."""
        self._moc_last_file = file_path

        # Find track in playlist
        playlist = self._state.playlist
        for idx, track in enumerate(playlist):
            track_path_resolved = str(Path(track.file_path).resolve())
            file_path_resolved = str(Path(file_path).resolve())
            if track_path_resolved == file_path_resolved:
                # Found track - update state
                self._state.set_current_index(idx)
                new_track = TrackMetadata(file_path)
                self._state.set_current_track(new_track)
                # Remove from shuffle queue if present (to avoid playing it again before queue regenerates)
                if self._state.shuffle_enabled and idx in self._shuffle_queue:
                    self._shuffle_queue.remove(idx)
                return

        # Track not found - MOC might have a different playlist
        # Try to load from MOC
        tracks, current_index = self._moc_controller.get_playlist(
            current_file=file_path
        )
        if tracks:
            # Update state with MOC's playlist (prevent circular sync)
            try:
                self._loading_from_moc = True
                self._state.set_playlist(tracks, current_index)
            finally:
                self._loading_from_moc = False

    def _handle_track_finished(self) -> None:
        """Handle track finished - auto-advance based on loop mode and autonext."""
        # Only auto-advance if autonext is enabled
        if not self._state.autonext_enabled:
            return

        # Reset timeline before advancing to prevent stale UI
        self._state.set_position(0.0)
        self._state.set_duration(0.0)

        # Note: _user_action_time is already set by caller to prevent poll interference
        # The handlers (_on_action_play, _on_action_next) will also set it, ensuring
        # proper guard window throughout the advancement process

        loop_mode = self._state.loop_mode
        playlist = self._state.playlist
        current_index = self._state.current_index

        if loop_mode == 1:  # LOOP_TRACK
            # Loop current track - restart it
            self._on_action_play(None)
        elif loop_mode == 2:  # LOOP_PLAYLIST
            # Loop playlist - advance to next or wrap to beginning
            if self._state.shuffle_enabled:
                # In shuffle mode, use shuffle queue (will regenerate when empty)
                next_index = self._get_next_shuffled_index()
                if next_index >= 0:
                    self._state.set_current_index(next_index)
                    self._on_action_play(None)
                else:
                    # Queue exhausted - regenerate and play first from new queue
                    self._regenerate_shuffle_queue()
                    if self._shuffle_queue:
                        next_index = self._shuffle_queue.pop(0)
                        self._state.set_current_index(next_index)
                        self._on_action_play(None)
            else:
                # Sequential navigation
                if current_index < len(playlist) - 1:
                    self._on_action_next(None)
                else:
                    # End of playlist - wrap to beginning
                    if playlist:
                        self._state.set_current_index(0)
                        self._on_action_play(None)
        else:  # LOOP_FORWARD (0)
            # Forward mode - advance to next track or stop at end
            if self._state.shuffle_enabled:
                # Use shuffle queue if shuffle is enabled
                next_index = self._get_next_shuffled_index()
                if next_index >= 0:
                    self._state.set_current_index(next_index)
                    self._on_action_play(None)
                else:
                    # Shuffle queue exhausted - stop
                    self._on_action_stop(None)
            else:
                # Sequential navigation
                if current_index < len(playlist) - 1:
                    self._on_action_next(None)
                else:
                    # End of playlist reached - stop
                    self._on_action_stop(None)

    def _check_moc_playlist_changes(self) -> None:
        """Check for MOC playlist file changes."""
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if not moc_playlist_path.exists():
                if self._moc_playlist_mtime > 0:
                    # File deleted - clear playlist
                    try:
                        self._loading_from_moc = True
                        self._state.clear_playlist()
                    finally:
                        self._loading_from_moc = False
                    self._moc_playlist_mtime = 0.0
                return

            mtime = moc_playlist_path.stat().st_mtime

            # Check if file changed
            if abs(mtime - self._moc_playlist_mtime) > 0.1:
                # Check if we wrote it recently
                if not self._recent_moc_write or (
                    time.time() - self._recent_moc_write > 0.5
                ):
                    # External change - load from MOC
                    tracks, current_index = self._moc_controller.get_playlist()
                    if tracks:
                        # Set flag to prevent circular sync back to MOC
                        try:
                            self._loading_from_moc = True
                            self._state.set_playlist(tracks, current_index)
                        finally:
                            self._loading_from_moc = False
                self._moc_playlist_mtime = mtime
        except OSError:
            pass

    # ============================================================================
    # Bluetooth Event Handlers
    # ============================================================================

    def _on_bt_sink_enabled(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink enabled."""
        # Set active backend FIRST so _stop_inactive_backends knows what to stop
        self._state.set_active_backend("bt_sink")
        # Stop other backends
        self._stop_inactive_backends()

    def _on_bt_sink_disabled(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink disabled."""
        if self._state.active_backend == "bt_sink":
            self._state.set_active_backend("none")
            self._state.set_playback_state(PlaybackState.STOPPED)

    def _on_bt_sink_device_connected(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink device connected."""
        # BT sink takes priority when device is connected
        if self._bt_sink and self._bt_sink.is_sink_enabled:
            # Set active backend FIRST so _stop_inactive_backends knows what to stop
            self._state.set_active_backend("bt_sink")
            # Stop other backends
            self._stop_inactive_backends()

    def _reset_seek_state(self) -> bool:
        """Reset seek state to IDLE after seek operation completes."""
        self._operation_state = OperationState.IDLE
        return False  # Don't repeat

    # ============================================================================
    # Cleanup
    # ============================================================================

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._use_moc:
            self._moc_controller.shutdown()
