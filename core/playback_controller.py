"""Playback controller - routes playback to MOC, internal player, BT sink."""

import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Any

if TYPE_CHECKING:
    from core.playlist_manager import PlaylistManager
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib
from core.audio_player import AudioPlayer
from core.bluetooth_sink import BluetoothSink
from core.config import get_config
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.system_volume import SystemVolume
from core.workflow_utils import is_video_file, normalize_path

logger = get_logger(__name__)


class PlaybackState(Enum):
    """State machine for playback operations."""

    STOPPED = "stopped"
    LOADING = "loading"
    PAUSED = "paused"
    PLAYING = "playing"
    SEEKING = "seeking"


class OperationState(Enum):
    """State machine for playback operations to prevent race conditions."""

    IDLE = "idle"
    SEEKING = "seeking"
    SYNCING = "syncing"


# MOC status update interval (milliseconds)
MOC_STATUS_UPDATE_INTERVAL = 500
# Audio formats routed to GStreamer instead of MOC.
# MOC's strengths are MP3, OGG and FLAC; everything else is either unreliable or
# completely unsupported by MOC (position/duration not reported, no decoder, etc.).
# GStreamer covers all of these via gst-plugins-{good,bad,ugly}.
_GSTREAMER_AUDIO_FORMATS = frozenset({
    # PCM-based: MOC position/duration reporting broken in UI integration
    ".wav", ".wave",
    ".aiff", ".aif",
    # No MOC decoder at all
    ".ape",   # Monkey's Audio
    ".wma",   # Windows Media Audio
    ".alac",  # Apple Lossless (standalone container)
    # MOC decoder exists but is hit-or-miss across installations
    ".opus",  # Opus (requires libopus in MOC, not always present)
    ".m4a",   # AAC or ALAC container (libfaad in MOC unreliable)
    ".aac",   # Raw AAC
})
# Seconds to treat a MOC/shuffle write as "recent" (skip reload to avoid races)
RECENT_WRITE_WINDOW = 2.0


class PlaybackController:
    """Routes playback to MOC/internal/BT; subscribes to actions; publishes state events."""

    def __init__(
        self,
        playlist_manager: "PlaylistManager",
        event_bus: EventBus,
        internal_player: AudioPlayer,
        moc_controller: MocController,
        bt_sink: Optional[BluetoothSink] = None,
        system_volume: Optional[SystemVolume] = None,
    ):
        self._playlist = playlist_manager
        self._events = event_bus
        self._internal_player = internal_player
        self._moc_controller = moc_controller
        self._bt_sink = bt_sink
        self._system_volume = system_volume

        # Playback state (published via events; no AppState)
        self._playback_state = PlaybackState.STOPPED
        self._active_backend: str = "none"
        self._position: float = 0.0
        self._duration: float = 0.0
        self._shuffle_enabled: bool = False
        self._loop_mode: int = 0
        self._autonext_enabled: bool = True
        self._volume: float = 1.0

        self._use_moc = moc_controller.is_available()
        self._operation_state = OperationState.IDLE

        # MOC: file mtime, recent-write timestamps, load/sync guards
        self._moc_last_file: Optional[str] = None
        self._internal_last_file: Optional[str] = None
        self._pending_seek_position: Optional[float] = None
        self._moc_playlist_mtime: float = 0.0
        self._recent_moc_write: Optional[float] = None
        self._recent_shuffle_write: Optional[float] = None
        self._recent_repeat_write: Optional[float] = None
        self._loading_from_moc: bool = False
        # MOC sync state
        self._syncing_to_moc: bool = False
        self._moc_sync_scheduled: bool = False  # Prevents queueing multiple syncs
        self._playlist_changed_during_sync: bool = False  # Re-sync needed after current sync
        self._pending_play_after_sync: bool = False  # ACTION_PLAY arrived during sync
        self._user_action_time: float = 0.0
        self._last_action_backend: str = "none"
        self._startup_complete: bool = False

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
        # Note: ACTION_APPEND_FOLDER removed - MOC sync handled via PLAYLIST_CHANGED

        # Note: PLAYBACK_STOP_REQUESTED merged into ACTION_STOP with reason field

        # Subscribe to playlist changes - single handler for all playlist modifications
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)

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

    def _set_playback_state(self, state: PlaybackState) -> None:
        old = self._playback_state
        self._playback_state = state
        # Publish unified state change event (replaces PLAYBACK_STARTED, PLAYBACK_PAUSED, PLAYBACK_STOPPED)
        if state == PlaybackState.PLAYING and old != PlaybackState.PLAYING:
            self._events.publish(
                EventBus.PLAYBACK_STATE_CHANGED,
                {
                    "state": "playing",
                    "track": self._playlist.get_current_track(),
                },
            )
        elif state == PlaybackState.PAUSED and old != PlaybackState.PAUSED:
            self._events.publish(EventBus.PLAYBACK_STATE_CHANGED, {"state": "paused"})
        elif state == PlaybackState.STOPPED and old != PlaybackState.STOPPED:
            self._events.publish(EventBus.PLAYBACK_STATE_CHANGED, {"state": "stopped"})

    def _set_active_backend(self, backend: str) -> None:
        if self._active_backend != backend:
            self._active_backend = backend
            # Note: ACTIVE_BACKEND_CHANGED event removed (no subscribers)

    def _update_progress(self, position: float, duration: float) -> None:
        """Update position + duration together and publish one PLAYBACK_PROGRESS event."""
        self._position = max(0.0, position)
        self._duration = max(0.0, duration)
        self._events.publish(
            EventBus.PLAYBACK_PROGRESS,
            {"position": self._position, "duration": self._duration},
        )

    def _set_position(self, position: float) -> None:
        """Update position (convenience wrapper, publishes progress)."""
        self._update_progress(position, self._duration)

    def _set_duration(self, duration: float) -> None:
        """Update duration (convenience wrapper, publishes progress)."""
        self._update_progress(self._position, duration)

    def _set_shuffle_enabled(self, enabled: bool) -> None:
        if self._shuffle_enabled != enabled:
            self._shuffle_enabled = enabled
            self._events.publish(EventBus.SHUFFLE_CHANGED, {"enabled": enabled})

    def _set_loop_mode(self, mode: int) -> None:
        if 0 <= mode <= 2 and self._loop_mode != mode:
            self._loop_mode = mode
            self._events.publish(EventBus.LOOP_MODE_CHANGED, {"mode": mode})

    # Note: _set_autonext_enabled() removed (was never called, AUTONEXT_CHANGED had no subscribers)

    def _set_volume(self, volume: float) -> None:
        new_vol = max(0.0, min(1.0, volume))
        if abs(self._volume - new_vol) > 0.001:
            self._volume = new_vol
            self._events.publish(EventBus.VOLUME_CHANGED, {"volume": self._volume})

    def _initialize_moc(self) -> bool:
        """Initialize MOC server and settings. Playlist sync is driven by PLAYLIST_CHANGED (e.g. after main window loads)."""
        if not self._use_moc:
            self._startup_complete = True
            return False
        if self._moc_controller.ensure_server():
            # Enable autonext in MOC (required for track advancement)
            # Also set our flag since set_initial_state_from_moc may have set it to False
            self._moc_controller.set_autonext(True)
            self._autonext_enabled = True
            # Sync shuffle state from MOC
            moc_shuffle = self._moc_controller.get_shuffle_state()
            if moc_shuffle is not None:
                self._set_shuffle_enabled(moc_shuffle)
            # Sync repeat state from MOC to loop mode
            moc_repeat = self._moc_controller.get_repeat_state()
            if moc_repeat is not None:
                # MOC only has repeat on/off, so map to LOOP_PLAYLIST (2) if on, LOOP_FORWARD (0) if off
                # We can't distinguish between LOOP_TRACK (1) and LOOP_PLAYLIST (2) from MOC
                loop_mode = 2 if moc_repeat else 0
                self._set_loop_mode(loop_mode)
        self._startup_complete = True
        return False

    def _should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Check if MOC should be used for this track."""
        if not self._use_moc or not track or not track.file_path:
            return False
        ext = Path(track.file_path).suffix.lower()
        if ext in _GSTREAMER_AUDIO_FORMATS:
            return False  # Use GStreamer: MOC lacks reliable WAV/AIFF support
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
        # Read active_backend AFTER it may have been updated by caller
        # This ensures we stop the correct backends based on the new state
        active_backend = self._active_backend

        # Stop internal player if not active
        if active_backend != "internal" and (
            self._internal_player.is_playing or self._internal_player.current_track
        ):
            self._internal_player.stop()

        # Stop MOC if not active
        if active_backend != "moc" and self._use_moc:
            status = self._moc_controller.get_status(force_refresh=True)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self._moc_controller.stop()

    def _mark_backend_action(self, backend: str) -> None:
        """Record latest backend intent for conflict resolution."""
        self._user_action_time = time.time()
        self._last_action_backend = backend

    def _enforce_backend_exclusivity(self, target_backend: str) -> None:
        """Stop non-target backend(s) to keep a strict single-backend invariant."""
        if target_backend == "moc":
            if self._internal_player.is_playing or self._internal_player.current_track:
                self._internal_player.stop()
            return
        if target_backend == "internal":
            if self._use_moc:
                status = self._moc_controller.get_status(force_refresh=True)
                if status and status.get("state") in ("PLAY", "PAUSE"):
                    self._moc_controller.stop()

    def _resolve_dual_playback_conflict(self, moc_status: Optional[Dict[str, Any]]) -> None:
        """Self-heal if both backends play simultaneously; latest action wins."""
        if not moc_status:
            return
        moc_playing = moc_status.get("state") == "PLAY"
        internal_playing = bool(self._internal_player.is_playing)
        if not (moc_playing and internal_playing):
            return

        winner = (
            self._last_action_backend
            if self._last_action_backend in ("moc", "internal")
            else self._active_backend
        )
        if winner == "internal":
            logger.warning(
                "Dual playback detected (moc+internal); resolving to internal (latest action)"
            )
            self._moc_controller.stop()
            self._set_active_backend("internal")
        else:
            logger.warning(
                "Dual playback detected (moc+internal); resolving to moc (latest action)"
            )
            if self._internal_player.is_playing or self._internal_player.current_track:
                self._internal_player.stop()
            self._set_active_backend("moc")

    def _load_and_play_current_track(self) -> bool:
        track = self._playlist.get_current_track()
        if not track or not track.file_path:
            logger.warning("Cannot play - no valid track or file path")
            return False
        track_path = Path(track.file_path)
        if not track_path.exists() or not track_path.is_file():
            logger.warning("Cannot play - file does not exist: %s", track.file_path)
            return False
        if self._should_use_moc(track):
            self._mark_backend_action("moc")
            return self._play_with_moc(track)
        self._mark_backend_action("internal")
        return self._play_with_internal(track)

    def _on_action_play(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play action: resume if same track paused, else load and play current track.

        During MOC sync, plays immediately via play_file() (independent of playlist state).
        """
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("play")
            return

        # During MOC sync: start playback immediately using shared backend paths.
        if self._use_moc and (self._syncing_to_moc or self._moc_sync_scheduled):
            track = self._playlist.get_current_track()
            if not track:
                playlist = self._playlist.get_playlist()
                if playlist:
                    self._playlist.set_current_index(0)
                    track = self._playlist.get_current_track()
            if track and track.file_path:
                if self._should_use_moc(track):
                    self._mark_backend_action("moc")
                    if self._play_with_moc(track):
                        self._pending_play_after_sync = False
                    else:
                        # Fallback: retry when current sync completes.
                        self._pending_play_after_sync = True
                else:
                    self._mark_backend_action("internal")
                    if self._play_with_internal(track):
                        self._pending_play_after_sync = False
                    else:
                        self._pending_play_after_sync = True
            return

        track = self._playlist.get_current_track()
        if not track:
            playlist = self._playlist.get_playlist()
            if playlist:
                self._playlist.set_current_index(0)
                track = self._playlist.get_current_track()
        if not track or not track.file_path:
            logger.warning("Cannot play - no valid track or file path")
            return
        track_path = Path(track.file_path)
        if not track_path.exists() or not track_path.is_file():
            logger.warning("Cannot play - file does not exist: %s", track.file_path)
            return

        self._mark_backend_action(
            "moc" if self._should_use_moc(track) else "internal"
        )
        active_backend = self._active_backend
        playing_file = (
            self._moc_last_file
            if active_backend == "moc"
            else (self._internal_last_file if active_backend == "internal" else None)
        )
        same_track = playing_file and normalize_path(track.file_path) == normalize_path(
            playing_file
        )
        # Resume
        if same_track:
            if self._playback_state == PlaybackState.PAUSED:
                if active_backend == "moc" and self._should_use_moc(track):
                    # MOC doesn't support seek while paused; apply pending seek after play starts
                    self._pending_seek_position = self._position
                    self._moc_controller.play()
                    self._set_playback_state(PlaybackState.PLAYING)
                    GLib.timeout_add(150, self._apply_moc_seek_after_play)
                    return
                if active_backend == "internal" and not self._should_use_moc(track):
                    if self._internal_player.play():
                        self._set_playback_state(PlaybackState.PLAYING)
                    return
            elif self._playback_state == PlaybackState.PLAYING:
                return

        self._load_and_play_current_track()

    def _on_action_pause(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle pause action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("pause")
            return

        active_backend = self._active_backend
        if active_backend == "moc":
            self._moc_controller.pause()
            self._set_playback_state(PlaybackState.PAUSED)
        elif active_backend == "internal":
            self._internal_player.pause()
            self._set_playback_state(PlaybackState.PAUSED)

    def _on_action_stop(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle stop action."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("stop")
            return

        # Idempotent hard-stop for both local backends to prevent drift-induced dual playback.
        if self._use_moc:
            self._moc_controller.stop()
        if self._internal_player.is_playing or self._internal_player.current_track:
            self._internal_player.stop()

        # Reset operation state to prevent stuck SEEKING state
        self._operation_state = OperationState.IDLE

        # Order matters: publish STOPPED before clearing index so UI subscribers
        # see playback stop before the track/index cleared events arrive.
        self._set_active_backend("none")
        self._internal_last_file = None
        self._moc_last_file = None
        self._set_playback_state(PlaybackState.STOPPED)
        self._update_progress(0.0, 0.0)
        self._playlist.set_current_index(-1)

    def _on_action_next(self, data: Optional[Dict[str, Any]]) -> None:
        if self._bt_sink and self._should_use_bt_sink():
            self._bt_sink.control_playback("next")
            return
        next_index = self._playlist.advance_to_next()
        if next_index >= 0:
            self._playlist.set_current_index(next_index)
            self._load_and_play_current_track()

    def _on_action_previous(self, data: Optional[Dict[str, Any]]) -> None:
        if self._bt_sink and self._should_use_bt_sink():
            self._bt_sink.control_playback("prev")
            return
        cur = self._playlist.get_current_index()
        if cur > 0:
            self._playlist.set_current_index(cur - 1)
            self._load_and_play_current_track()

    def _on_action_seek(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle seek action. Always reflect the drag in state so UI and play-from-here work."""
        if not data or "position" not in data:
            return

        position = float(data["position"])
        if self._should_use_bt_sink():
            return

        duration = self._duration
        clamped = (
            max(0.0, min(position, duration)) if duration > 0 else max(0.0, position)
        )
        # Always update state so the drag is reflected (even when no backend or duration=0)
        self._set_position(clamped)

        self._user_action_time = time.time()
        self._operation_state = OperationState.SEEKING
        self._set_playback_state(PlaybackState.SEEKING)

        active_backend = self._active_backend
        if active_backend == "moc":
            self._seek_moc(clamped)
        elif active_backend == "internal":
            self._internal_player.seek(clamped)
            GLib.timeout_add(100, self._reset_seek_state)
        else:
            # No active backend - still reset seek state to avoid getting stuck
            GLib.timeout_add(100, self._reset_seek_state)

    def _on_action_play_track(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play specific track: set index and load/play.

        Note: PlaylistView publishes this event but does NOT set the index.
        Controller is the single source of state mutation via PlaylistManager.
        """
        if not data or "index" not in data:
            return
        index = data.get("index", -1)
        if index < 0:
            return
        # Controller sets the index (single source of mutation)
        self._playlist.set_current_index(index)
        self._load_and_play_current_track()

    # Note: _on_playback_stop_requested() removed - ACTION_STOP now handles all stop requests
    # (with optional reason field for system-initiated stops)

    def _on_playlist_changed(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle playlist changes - sync to MOC.

        This is the single handler for all playlist content modifications.
        Playback intent is handled separately via ACTION_PLAY.
        """
        if not data:
            return
        content_changed = data.get("content_changed", True)
        if not content_changed:
            return
        # Skip if we're loading from MOC (avoid sync loop)
        if self._loading_from_moc:
            return

        logger.debug(
            "PLAYLIST_CHANGED: use_moc=%s, syncing=%s, scheduled=%s",
            self._use_moc,
            self._syncing_to_moc,
            self._moc_sync_scheduled,
        )

        if self._use_moc:
            if self._syncing_to_moc or self._moc_sync_scheduled:
                # Sync in progress or already scheduled - mark for re-sync
                self._playlist_changed_during_sync = True
            else:
                # Schedule sync (single-flight: only one pending at a time)
                self._moc_sync_scheduled = True
                GLib.idle_add(self._sync_moc_playlist)

    def _on_action_set_shuffle(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set shuffle action."""
        if not data or "enabled" not in data:
            return

        enabled = bool(data["enabled"])
        self._set_shuffle_enabled(enabled)

        # Sync to MOC if using MOC
        if self._use_moc:
            self._moc_controller.set_shuffle(enabled)
            self._recent_shuffle_write = time.time()

    def _on_action_set_loop_mode(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set loop mode action."""
        if not data or "mode" not in data:
            return

        mode = int(data["mode"])
        self._set_loop_mode(mode)

        # Sync loop mode to MOC's repeat option
        # LOOP_TRACK (1) and LOOP_PLAYLIST (2) both map to repeat=on
        # LOOP_FORWARD (0) maps to repeat=off
        if self._use_moc:
            self._moc_controller.set_repeat(
                mode in (1, 2)
            )  # LOOP_TRACK or LOOP_PLAYLIST
            self._recent_repeat_write = time.time()

    def _on_action_set_volume(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle set volume action: update state and apply to system volume."""
        if not data or "volume" not in data:
            return

        volume = float(data["volume"])
        self._set_volume(volume)
        if self._system_volume:
            self._system_volume.set_volume(volume)

    def _on_action_refresh_moc(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle refresh from MOC: sync MOC to disk, then reload playlist into app state (events drive UI)."""
        if not self._use_moc:
            return
        self._moc_controller.sync_playlist()
        GLib.timeout_add(100, self._refresh_moc_callback)

    def _refresh_moc_callback(self) -> bool:
        """Reload playlist from MOC after sync_playlist (used by refresh button)."""
        status = self._moc_controller.get_status(force_refresh=True)
        current_file = status.get("file_path") if status else None
        self._reload_playlist_from_moc(current_file=current_file)
        return False

    # Note: _on_action_append_folder() removed - MOC sync handled via PLAYLIST_CHANGED

    def _play_with_moc(self, track: TrackMetadata) -> bool:
        if not self._use_moc:
            return False

        # Reset operation state to prevent stuck states
        self._operation_state = OperationState.IDLE

        self._enforce_backend_exclusivity("moc")

        # Set _moc_last_file for track-end detection
        if track and track.file_path:
            self._moc_last_file = str(Path(track.file_path).resolve())

        # Find track index in playlist
        playlist = self._playlist.get_playlist()
        track_index = -1
        for idx, t in enumerate(playlist):
            if t.file_path == track.file_path:
                track_index = idx
                break

        # Set backend and index
        self._set_active_backend("moc")
        if track_index >= 0:
            self._playlist.set_current_index(track_index)
        else:
            self._playlist.set_current_index(-1)

        # Play the file
        if track and track.file_path:
            if not self._moc_controller.play_file(track.file_path):
                return False

        # Reset progress immediately so UI doesn't show stale values
        self._update_progress(0.0, track.duration if track.duration else 0.0)
        self._set_playback_state(PlaybackState.PLAYING)
        return True

    def _play_with_internal(self, track: TrackMetadata) -> bool:
        """Play track using internal player."""
        # Reset operation state to prevent stuck states
        self._operation_state = OperationState.IDLE

        self._enforce_backend_exclusivity("internal")

        self._internal_player.load_track(track)
        if not self._internal_player.play():
            return False

        # Find track index in playlist
        playlist = self._playlist.get_playlist()
        track_index = -1
        for idx, t in enumerate(playlist):
            if t.file_path == track.file_path:
                track_index = idx
                break

        self._set_active_backend("internal")
        if track and track.file_path:
            self._internal_last_file = str(Path(track.file_path).resolve())
        if track_index >= 0:
            self._playlist.set_current_index(track_index)
        else:
            self._playlist.set_current_index(-1)

        # Reset progress immediately so UI doesn't show stale values
        self._update_progress(0.0, track.duration if track.duration else 0.0)

        self._set_playback_state(PlaybackState.PLAYING)
        return True

    def _seek_moc(self, position: float) -> None:
        """Seek in MOC. Always reflect position in state. MOC cannot seek while paused."""
        if not self._use_moc:
            return

        try:
            status = self._moc_controller.get_status(force_refresh=True)
            if not status:
                return

            duration = float(status.get("duration", 0.0))
            if duration > 0:
                position = max(0.0, min(position, duration))
            else:
                position = max(0.0, position)

            # Always reflect the drag in state
            self._set_position(position)

            # MOC does not support seek while paused; only seek when playing (or SEEKING from drag)
            if self._playback_state == PlaybackState.PAUSED:
                return

            current_pos = float(status.get("position", 0.0))
            delta = position - current_pos
            if abs(delta) >= 0.5:
                self._moc_controller.seek_relative(delta)
        finally:
            GLib.timeout_add(200, self._reset_seek_state)

    def _apply_moc_seek_after_play(self) -> bool:
        """Apply pending seek after MOC has started (seek-while-paused then play). One-shot."""
        desired = self._pending_seek_position
        self._pending_seek_position = None
        if desired is None or self._active_backend != "moc":
            return False
        status = self._moc_controller.get_status(force_refresh=True)
        if not status:
            return False
        current = float(status.get("position", 0.0))
        if abs(desired - current) < 0.5:
            return False
        self._moc_controller.seek_relative(desired - current)
        self._set_position(desired)
        return False

    def _sync_moc_playlist(self) -> bool:
        """Sync current playlist to MOC.

        Playback intent is handled separately via ACTION_PLAY and _pending_play_after_sync.
        If called while already syncing, marks for re-sync after current sync completes.
        """
        # Clear scheduled flag immediately (single-flight pattern)
        self._moc_sync_scheduled = False

        if not self._use_moc:
            return False

        if self._syncing_to_moc:
            # Already syncing - mark for re-sync
            logger.debug("_sync_moc_playlist: already syncing, marking for re-sync")
            self._playlist_changed_during_sync = True
            return False

        playlist = self._playlist.get_playlist()
        current_index = self._playlist.get_current_index()

        self._syncing_to_moc = True
        self._recent_moc_write = time.time()

        def on_done():
            logger.debug(
                "MOC sync on_done: playlist_changed=%s, pending_play=%s",
                self._playlist_changed_during_sync,
                self._pending_play_after_sync,
            )
            self._syncing_to_moc = False
            self._recent_moc_write = time.time()

            # Update mtime
            try:
                config = get_config()
                if config.moc_playlist_path.exists():
                    self._moc_playlist_mtime = config.moc_playlist_path.stat().st_mtime
            except OSError:
                pass

            # Check if re-sync needed (playlist changed during sync)
            if self._playlist_changed_during_sync:
                self._playlist_changed_during_sync = False
                logger.debug("Re-syncing after playlist changed during sync")
                GLib.idle_add(self._sync_moc_playlist)
                return

            # Handle queued playback intent (ACTION_PLAY arrived during sync)
            if self._pending_play_after_sync:
                self._pending_play_after_sync = False
                t = self._playlist.get_current_track()
                if t and t.file_path:
                    logger.debug(
                        "MOC sync complete, starting queued playback: %s", t.file_path
                    )
                    self._load_and_play_current_track()

        self._moc_controller.sync_playlist_async(
            playlist, current_index, on_done=on_done
        )
        return False

    def _reload_playlist_from_moc(self, current_file: Optional[str] = None) -> None:
        """Load playlist from MOC into app state. Skipped while syncing to avoid overwriting with partial data."""
        if not self._use_moc or self._syncing_to_moc:
            return
        tracks, current_index = self._moc_controller.get_playlist(
            current_file=current_file
        )
        if not tracks:
            return
        try:
            self._loading_from_moc = True
            self._playlist.set_playlist(tracks, current_index)
        finally:
            self._loading_from_moc = False
        try:
            config = get_config()
            if config.moc_playlist_path.exists():
                self._moc_playlist_mtime = config.moc_playlist_path.stat().st_mtime
        except OSError:
            pass

    def _poll_internal_player_status(self) -> bool:
        """Poll internal player status and update state."""
        # Only poll if internal player is the active backend
        if self._active_backend != "internal":
            return True  # Continue polling

        # Update position and duration
        position = self._internal_player.get_position()
        duration = self._internal_player.get_duration()

        # Update state — batch position + duration into one publish
        if self._operation_state != OperationState.SEEKING:
            self._update_progress(position, duration if duration > 0 else self._duration)
        elif duration > 0:
            self._set_duration(duration)

        # Update playback state
        if self._internal_player.is_playing:
            if self._playback_state != PlaybackState.PLAYING:
                self._set_playback_state(PlaybackState.PLAYING)
        elif self._internal_player.track_just_finished:
            # EOS arrived: consume the flag and trigger auto-advance.
            # Must be checked BEFORE current_track because EOS leaves current_track set,
            # which would otherwise make us think the player is merely paused.
            self._internal_player.track_just_finished = False
            self._set_playback_state(PlaybackState.STOPPED)
            self._handle_track_finished()
        elif self._internal_player.current_track:
            if self._playback_state != PlaybackState.PAUSED:
                self._set_playback_state(PlaybackState.PAUSED)
        else:
            # No track loaded and no EOS — player was stopped externally or never started
            if self._playback_state != PlaybackState.STOPPED:
                self._set_playback_state(PlaybackState.STOPPED)

        return True  # Continue polling

    def _poll_moc_status(self) -> bool:
        """Poll MOC status and update state."""
        if not self._use_moc:
            return False

        # Skip all state updates during MOC sync - MOC state is unstable while
        # playlist is being rebuilt. Sync's on_done will set correct state.
        if self._syncing_to_moc:
            return True  # Continue polling, but don't update anything

        status = self._moc_controller.get_status()
        if not status:
            return True  # Try again later

        self._resolve_dual_playback_conflict(status)

        moc_state = status.get("state", "STOP")

        # If MOC is playing/paused but backend is "none", activate MOC as backend
        # This handles: MOC started externally, or sync completed
        if self._active_backend == "none" and moc_state in ("PLAY", "PAUSE"):
            logger.debug(
                "MOC is %s but backend is 'none', activating MOC backend", moc_state
            )
            self._set_active_backend("moc")
            file_path = status.get("file_path")
            if file_path:
                self._moc_last_file = str(Path(file_path).resolve())

        # Only update state if MOC is the active backend
        if self._active_backend != "moc":
            return True  # Continue polling

        state = moc_state
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))

        # Batch position + duration into one publish
        if self._operation_state != OperationState.SEEKING:
            self._update_progress(position, duration if duration > 0 else self._duration)
        elif duration > 0:
            self._set_duration(duration)

        # Update playback state
        if state == "PLAY":
            if self._playback_state != PlaybackState.PLAYING:
                self._set_playback_state(PlaybackState.PLAYING)
        elif state == "PAUSE":
            if self._playback_state != PlaybackState.PAUSED:
                self._set_playback_state(PlaybackState.PAUSED)
        elif state == "STOP":
            if self._playback_state != PlaybackState.STOPPED:
                self._set_playback_state(PlaybackState.STOPPED)

        moc_shuffle = status.get("shuffle", False)
        if moc_shuffle and not self._shuffle_enabled:
            # MOC reports shuffle on (e.g. toggled in MOC) - sync to us
            self._set_shuffle_enabled(True)
        # When moc_shuffle is False but we have True: keep our True (MOC -i may not report Shuffle)

        moc_repeat = status.get("repeat", False)
        if moc_repeat and self._loop_mode == 0:
            # MOC reports repeat on (e.g. toggled in MOC) - sync to us as LOOP_PLAYLIST
            self._set_loop_mode(2)
        # When moc_repeat is False but we have loop_mode 1 or 2: keep ours (MOC -i may not report Repeat)

        # Detect track change - but skip if user just initiated an action (prevent interference)
        if file_path and file_path != self._moc_last_file:
            if time.time() - self._user_action_time >= 1.0:
                self._handle_moc_track_change(file_path)

        track_finished = (
            file_path == self._moc_last_file
            and duration > 0
            and (
                (state == "STOP" and position >= duration - 0.5)
                or (state == "PLAY" and position >= duration - 1.0)
            )
        )
        if track_finished:
            self._user_action_time = time.time()
            # RC-008: Use has_next() for read-only check (doesn't consume shuffle queue)
            if self._playlist.has_next():
                self._handle_track_finished()
            else:
                self._set_playback_state(PlaybackState.STOPPED)
                self._update_progress(0.0, 0.0)

        # Detect external playlist file changes (skip during sync — file is in flux)
        if not self._syncing_to_moc:
            self._check_moc_playlist_changes()

        return True  # Continue polling

    def _handle_moc_track_change(self, file_path: str) -> None:
        """Handle MOC track change (auto-advancement)."""
        self._moc_last_file = file_path

        playlist = self._playlist.get_playlist()
        resolved = str(Path(file_path).resolve())
        for idx, track in enumerate(playlist):
            if track.file_path and str(Path(track.file_path).resolve()) == resolved:
                self._playlist.set_current_index(idx)
                return
        self._reload_playlist_from_moc(current_file=file_path)

    def _handle_track_finished(self) -> None:
        if not self._autonext_enabled:
            return
        loop_mode = self._loop_mode
        playlist = self._playlist.get_playlist()
        cur = self._playlist.get_current_index()
        next_idx = self._playlist.advance_to_next()
        if loop_mode == 1:
            self._on_action_play(None)
        elif loop_mode == 2:
            if next_idx >= 0:
                self._playlist.set_current_index(next_idx)
                self._on_action_play(None)
            elif playlist:
                self._playlist.set_current_index(0)
                self._on_action_play(None)
        else:
            if next_idx >= 0:
                self._playlist.set_current_index(next_idx)
                self._on_action_play(None)
            else:
                self._on_action_stop(None)

    def _check_moc_playlist_changes(self) -> None:
        """Check for external MOC playlist file changes.

        All branches are suppressed during the recent-write window to prevent
        our own sync operations from being misinterpreted as external changes.
        """
        try:
            recent_write = self._recent_moc_write and (
                time.time() - self._recent_moc_write < RECENT_WRITE_WINDOW
            )
            config = get_config()
            moc_playlist_path = config.moc_playlist_path

            if not moc_playlist_path.exists():
                if self._moc_playlist_mtime > 0 and not recent_write:
                    try:
                        self._loading_from_moc = True
                        self._playlist.clear()
                    finally:
                        self._loading_from_moc = False
                    self._moc_playlist_mtime = 0.0
                return

            mtime = moc_playlist_path.stat().st_mtime
            if abs(mtime - self._moc_playlist_mtime) > 0.1:
                if not recent_write and self._startup_complete:
                    self._reload_playlist_from_moc()
                self._moc_playlist_mtime = mtime
        except OSError:
            pass

    def _on_bt_sink_enabled(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink enabled."""
        # Set active backend FIRST so _stop_inactive_backends knows what to stop
        self._set_active_backend("bt_sink")
        # Stop other backends
        self._stop_inactive_backends()

    def _on_bt_sink_disabled(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink disabled."""
        if self._active_backend == "bt_sink":
            # Batch state updates: backend -> playback state
            self._set_active_backend("none")
            self._set_playback_state(PlaybackState.STOPPED)

    def _on_bt_sink_device_connected(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle BT sink device connected."""
        # BT sink takes priority when device is connected
        if self._bt_sink and self._bt_sink.is_sink_enabled:
            # Set active backend FIRST so _stop_inactive_backends knows what to stop
            self._set_active_backend("bt_sink")
            # Stop other backends
            self._stop_inactive_backends()

    def _reset_seek_state(self) -> bool:
        """Reset seek state to IDLE after seek operation completes.

        Also publishes a fresh progress update so the UI never sits on a stale value.
        """
        self._operation_state = OperationState.IDLE
        # Restore playback state from actual backend state
        active_backend = self._active_backend
        if active_backend == "moc":
            status = self._moc_controller.get_status(force_refresh=True)
            if status:
                state = status.get("state", "STOP")
                if state == "PLAY":
                    self._set_playback_state(PlaybackState.PLAYING)
                elif state == "PAUSE":
                    self._set_playback_state(PlaybackState.PAUSED)
                else:
                    self._set_playback_state(PlaybackState.STOPPED)
                # Publish fresh progress from backend
                self._set_position(float(status.get("position", self._position)))
        elif active_backend == "internal":
            if self._internal_player.is_playing:
                self._set_playback_state(PlaybackState.PLAYING)
            elif self._internal_player.current_track:
                self._set_playback_state(PlaybackState.PAUSED)
            else:
                self._set_playback_state(PlaybackState.STOPPED)
            # Publish fresh progress from internal player
            self._set_position(self._internal_player.position)
        # If no active backend, polling will handle it
        return False  # Don't repeat

    def set_initial_state_from_moc(self, status: Dict[str, Any]) -> None:
        if status.get("shuffle") is not None:
            self._shuffle_enabled = bool(status["shuffle"])
        if status.get("autonext") is not None:
            self._autonext_enabled = bool(status["autonext"])
        if status.get("repeat") is not None:
            self._loop_mode = 2 if status["repeat"] else 0
        moc_state = (status.get("state") or "STOP").upper()
        if moc_state == "PLAY":
            self._playback_state = PlaybackState.PLAYING
        elif moc_state == "PAUSE":
            self._playback_state = PlaybackState.PAUSED
        else:
            self._playback_state = PlaybackState.STOPPED
        self._position = float(status.get("position", 0) or 0)
        self._duration = float(status.get("duration", 0) or 0)
        vol = status.get("volume")
        if vol is not None:
            self._volume = float(vol)
        self._active_backend = "moc"

    def publish_initial_state(self) -> None:
        """Publish current playback state as events so UI (e.g. PlayerControls) can sync without reading state."""
        # Unified progress event (replaces POSITION_CHANGED, DURATION_CHANGED)
        self._events.publish(
            EventBus.PLAYBACK_PROGRESS,
            {"position": self._position, "duration": self._duration},
        )
        self._events.publish(
            EventBus.SHUFFLE_CHANGED, {"enabled": self._shuffle_enabled}
        )
        self._events.publish(EventBus.LOOP_MODE_CHANGED, {"mode": self._loop_mode})
        self._events.publish(EventBus.VOLUME_CHANGED, {"volume": self._volume})
        # Note: ACTIVE_BACKEND_CHANGED publish removed (no subscribers)
        # Unified playback state event
        if self._playback_state == PlaybackState.PLAYING:
            self._events.publish(
                EventBus.PLAYBACK_STATE_CHANGED,
                {
                    "state": "playing",
                    "track": self._playlist.get_current_track(),
                },
            )
        elif self._playback_state == PlaybackState.PAUSED:
            self._events.publish(EventBus.PLAYBACK_STATE_CHANGED, {"state": "paused"})
        else:
            self._events.publish(EventBus.PLAYBACK_STATE_CHANGED, {"state": "stopped"})

    def cleanup(self) -> None:
        if self._use_moc:
            self._moc_controller.shutdown()
