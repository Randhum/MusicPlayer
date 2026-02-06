"""Playback controller - routes playback to MOC, internal player, BT sink."""
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Any
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
        self._syncing_to_moc: bool = False
        self._pending_start_playback: bool = False
        self._sync_idle_id: Optional[int] = None  # coalesce PLAYLIST_CHANGED + ACTION_SYNC into one sync
        self._pending_sync_start_playback: bool = False
        self._playlist_changed_during_sync: bool = False  # Track if playlist changed while syncing
        self._user_action_time: float = 0.0
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
        self._events.subscribe(
            EventBus.ACTION_SYNC_PLAYLIST_TO_MOC, self._on_action_sync_playlist_to_moc
        )
        self._events.subscribe(
            EventBus.ACTION_APPEND_FOLDER, self._on_action_append_folder
        )

        # Subscribe to playlist changes to sync with MOC
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)

        # Subscribe to shuffle (PlaylistManager owns shuffle queue; we just sync to MOC)
        self._events.subscribe(EventBus.SHUFFLE_CHANGED, self._on_shuffle_changed)

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
        if state == PlaybackState.PLAYING and old != PlaybackState.PLAYING:
            self._events.publish(
                EventBus.PLAYBACK_STARTED,
                {"track": self._playlist.get_current_track()},
            )
        elif state == PlaybackState.PAUSED and old == PlaybackState.PLAYING:
            self._events.publish(EventBus.PLAYBACK_PAUSED, {})
        elif state == PlaybackState.STOPPED and old != PlaybackState.STOPPED:
            self._events.publish(EventBus.PLAYBACK_STOPPED, {})

    def _set_active_backend(self, backend: str) -> None:
        if self._active_backend != backend:
            self._active_backend = backend
            self._events.publish(
                EventBus.ACTIVE_BACKEND_CHANGED, {"backend": self._active_backend}
            )

    def _set_position(self, position: float) -> None:
        self._position = max(0.0, position)
        self._events.publish(
            EventBus.POSITION_CHANGED,
            {"position": self._position, "duration": self._duration},
        )

    def _set_duration(self, duration: float) -> None:
        self._duration = max(0.0, duration)
        self._events.publish(
            EventBus.DURATION_CHANGED,
            {"duration": self._duration, "position": self._position},
        )

    def _set_shuffle_enabled(self, enabled: bool) -> None:
        if self._shuffle_enabled != enabled:
            self._shuffle_enabled = enabled
            self._events.publish(EventBus.SHUFFLE_CHANGED, {"enabled": enabled})

    def _set_loop_mode(self, mode: int) -> None:
        if 0 <= mode <= 2 and self._loop_mode != mode:
            self._loop_mode = mode
            self._events.publish(EventBus.LOOP_MODE_CHANGED, {"mode": mode})

    def _set_autonext_enabled(self, enabled: bool) -> None:
        if self._autonext_enabled != enabled:
            self._autonext_enabled = enabled
            self._events.publish(EventBus.AUTONEXT_CHANGED, {"enabled": enabled})

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
            self._moc_controller.set_autonext(True)
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
            status = self._moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self._moc_controller.stop()

    def _load_and_play_current_track(self) -> bool:
        track = self._playlist.get_current_track()
        if not track or not track.file_path:
            logger.warning("Cannot play - no valid track or file path")
            return False
        track_path = Path(track.file_path)
        if not track_path.exists() or not track_path.is_file():
            logger.warning("Cannot play - file does not exist: %s", track.file_path)
            return False
        self._user_action_time = time.time()
        self._stop_inactive_backends()
        if self._should_use_moc(track):
            self._play_with_moc(track)
        else:
            self._play_with_internal(track)
        return True

    def _on_action_play(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play action: resume if same track paused, else load and play current track."""
        if self._should_use_bt_sink():
            if self._bt_sink:
                self._bt_sink.control_playback("play")
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

        self._user_action_time = time.time()
        active_backend = self._active_backend
        playing_file = (
            self._moc_last_file
            if active_backend == "moc"
            else (self._internal_last_file if active_backend == "internal" else None)
        )
        same_track = (
            playing_file
            and normalize_path(track.file_path) == normalize_path(playing_file)
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

        active_backend = self._active_backend
        if active_backend == "moc":
            self._moc_controller.stop()
        elif active_backend == "internal":
            self._internal_player.stop()

        # Batch state updates to avoid intermediate inconsistent states
        # Order: backend -> index -> playback state -> timeline
        self._set_active_backend("none")
        self._internal_last_file = None  # clear so same_track check is correct after stop
        self._playlist.set_current_index(-1)  # This also clears current_track
        self._set_playback_state(PlaybackState.STOPPED)
        # Reset timeline to 00:00
        self._set_position(0.0)
        self._set_duration(0.0)

    def _on_action_next(self, data: Optional[Dict[str, Any]]) -> None:
        if self._bt_sink and self._should_use_bt_sink():
            self._bt_sink.control_playback("next")
            return
        next_index = self._playlist.get_next_index()
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

    def _on_action_play_track(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle play specific track: index already set by PlaylistView, load and play."""
        if not data or "index" not in data:
            return
        # Index already set by PlaylistView.play_track_at_index() before this action
        self._load_and_play_current_track()

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
            self._moc_controller.set_repeat(mode in (1, 2))  # LOOP_TRACK or LOOP_PLAYLIST
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

    def _on_action_sync_playlist_to_moc(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle explicit sync of internal playlist to MOC (e.g. after add track or play folder).
        
        Uses the same coalescing mechanism as _on_playlist_changed to avoid double syncs.
        """
        if not self._use_moc:
            return
        start_playback = data.get("start_playback", False) if data else False
        # Record that we want to start playback for the coalesced sync
        if start_playback:
            self._pending_sync_start_playback = True
        # If currently syncing, mark that we need to re-sync and preserve start_playback for re-sync path
        if self._syncing_to_moc:
            if start_playback:
                self._pending_start_playback = True  # Only set for re-sync path
            self._playlist_changed_during_sync = True
            return
        # Schedule sync if not already scheduled (coalesce with PLAYLIST_CHANGED)
        if self._sync_idle_id is None:
            self._sync_idle_id = GLib.idle_add(self._run_pending_moc_sync)

    def _on_action_append_folder(self, data: Optional[Dict[str, Any]]) -> None:
        """Handle append folder action - add folder to MOC playlist, then reload into app state (UI updates via PLAYLIST_CHANGED)."""
        if not self._use_moc or not data or "folder_path" not in data:
            return
        folder_path = data["folder_path"]
        if not folder_path:
            return
        if self._moc_controller.append_to_playlist(folder_path):
            logger.info("Appended folder to MOC playlist: %s", folder_path)
            self._recent_moc_write = time.time()
            self._reload_playlist_from_moc()
        else:
            logger.warning("Failed to append folder to MOC playlist: %s", folder_path)

    def _play_with_moc(self, track: TrackMetadata) -> None:
        if not self._use_moc:
            return

        # CRITICAL: Set _moc_last_file FIRST so track-end detection works
        # Without this, file_path == _moc_last_file is always False
        if track and track.file_path:
            self._moc_last_file = str(Path(track.file_path).resolve())

        # Set state before playing - set_current_index will update current_track automatically
        # Find track index in playlist to avoid duplicate track updates
        playlist = self._playlist.get_playlist()
        track_index = -1
        for idx, t in enumerate(playlist):
            if t.file_path == track.file_path:
                track_index = idx
                break
        
        # Set backend first, then index (which updates track), then playback state
        self._set_active_backend("moc")
        if track_index >= 0:
            # Track is in playlist - use set_current_index to update both index and track atomically
            # This ensures consistent state: index and track are updated together, and events are published correctly
            self._playlist.set_current_index(track_index)
        else:
            # Track not in playlist - set track directly (rare case, e.g., playing external file)
            # This bypasses playlist index but still publishes TRACK_CHANGED event
            self._playlist.set_current_index(-1)
            self._events.publish(EventBus.TRACK_CHANGED, {"track": track})

        # Just play the file - MOC's --playit will add it to playlist if needed
        # Only set PLAYING if MOC actually starts (avoids UI showing play when MOC didn't start)
        if track and track.file_path:
            if not self._moc_controller.play_file(track.file_path):
                return
        self._set_playback_state(PlaybackState.PLAYING)

    def _play_with_internal(self, track: TrackMetadata) -> None:
        """Play track using internal player."""
        self._internal_player.load_track(track)
        self._internal_player.play()

        # Set state in proper order: backend -> track/index -> playback state -> duration
        # Find track index in playlist to avoid duplicate track updates
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
            # Track is in playlist - use set_current_index to update both index and track atomically
            # This ensures consistent state: index and track are updated together, and events are published correctly
            self._playlist.set_current_index(track_index)
        else:
            # Track not in playlist - set track directly (rare case, e.g., playing external file)
            # This bypasses playlist index but still publishes TRACK_CHANGED event
            self._playlist.set_current_index(-1)
            self._events.publish(EventBus.TRACK_CHANGED, {"track": track})

        # Update duration from track metadata before setting playback state
        if track.duration:
            self._set_duration(track.duration)
        
        self._set_playback_state(PlaybackState.PLAYING)

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

    def _run_pending_moc_sync(self) -> bool:
        """Single idle callback: run one sync with coalesced start_playback. Prevents double sync when PLAYLIST_CHANGED and ACTION_SYNC_PLAYLIST_TO_MOC fire together."""
        self._sync_idle_id = None
        start = self._pending_sync_start_playback
        self._pending_sync_start_playback = False
        self._sync_moc_playlist(start)
        return False

    def _sync_moc_playlist(self, start_playback: bool = False) -> bool:
        if not self._use_moc:
            return False

        if self._syncing_to_moc:
            if start_playback:
                self._pending_start_playback = True
            return False
        playlist = self._playlist.get_playlist()
        current_index = self._playlist.get_current_index()
        track = self._playlist.get_current_track()
        should_start = start_playback and track and not is_video_file(track.file_path)
        self._syncing_to_moc = True
        self._recent_moc_write = time.time()  # Suppress reload-from-MOC during and right after sync

        def on_done():
            self._syncing_to_moc = False
            self._recent_moc_write = time.time()
            try:
                config = get_config()
                if config.moc_playlist_path.exists():
                    self._moc_playlist_mtime = config.moc_playlist_path.stat().st_mtime
            except OSError:
                pass
            # Check if playlist changed during sync - if so, re-sync
            if self._playlist_changed_during_sync:
                self._playlist_changed_during_sync = False
                logger.debug("Playlist changed during MOC sync, scheduling re-sync")
                # Preserve start_playback intent: if original should_start OR pending, keep it
                re_sync_start = should_start or self._pending_start_playback
                self._pending_start_playback = False
                GLib.idle_add(self._sync_moc_playlist, re_sync_start)
                return
            # Set active backend to MOC AFTER sync completes (not before) so polling doesn't interfere
            if should_start and track:
                self._set_active_backend("moc")
                self._moc_last_file = str(Path(track.file_path).resolve())
            if self._pending_start_playback:
                self._pending_start_playback = False
                def start_after_sync():
                    # Only play if we still have a valid current track (avoids race with MOC load)
                    t = self._playlist.get_current_track()
                    if t and t.file_path:
                        self._load_and_play_current_track()
                    return False
                GLib.idle_add(start_after_sync)

        if len(playlist) >= 100:
            self._moc_controller.set_playlist_large(
                playlist, current_index, should_start, on_done=on_done
            )
        else:
            self._moc_controller.set_playlist(
                playlist, current_index, start_playback=should_start
            )
            on_done()
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

    def _on_playlist_changed(self, data: Optional[Dict[str, Any]]) -> None:
        """Request sync to MOC. Coalesced with ACTION_SYNC_PLAYLIST_TO_MOC so we run one sync."""
        content_changed = data is None or data.get("content_changed", True)
        if not content_changed:
            return
        if not self._use_moc or self._active_backend not in ("moc", "none"):
            return
        if self._loading_from_moc:
            return
        # If currently syncing, mark that playlist changed so we re-sync after current sync completes
        if self._syncing_to_moc:
            self._playlist_changed_during_sync = True
            return
        if self._sync_idle_id is None:
            self._sync_idle_id = GLib.idle_add(self._run_pending_moc_sync)

    def _on_shuffle_changed(self, data: Optional[Dict[str, Any]]) -> None:
        pass  # PlaylistManager owns shuffle queue via same event

    def _poll_internal_player_status(self) -> bool:
        """Poll internal player status and update state."""
        # Only poll if internal player is the active backend
        if self._active_backend != "internal":
            return True  # Continue polling

        # Update position and duration
        position = self._internal_player.get_position()
        duration = self._internal_player.get_duration()

        # Update state (this will publish events)
        # Batch updates when both change to avoid UI flicker
        if self._operation_state != OperationState.SEEKING:
            # Update position first
            self._set_position(position)
        # Update duration if it changed (this publishes DURATION_CHANGED event)
        if duration > 0:
            self._set_duration(duration)

        # Update playback state
        if self._internal_player.is_playing:
            if self._playback_state != PlaybackState.PLAYING:
                self._set_playback_state(PlaybackState.PLAYING)
        elif self._internal_player.current_track:
            if self._playback_state != PlaybackState.PAUSED:
                self._set_playback_state(PlaybackState.PAUSED)
        else:
            # Check if track finished (was playing, now stopped, position at end)
            was_playing = self._playback_state == PlaybackState.PLAYING
            if was_playing and duration > 0 and position >= duration - 0.5:
                # Track finished - handle auto-advance
                self._set_playback_state(PlaybackState.STOPPED)
                self._handle_track_finished()
            elif self._playback_state != PlaybackState.STOPPED:
                self._set_playback_state(PlaybackState.STOPPED)

        return True  # Continue polling

    def _poll_moc_status(self) -> bool:
        """Poll MOC status and update state."""
        if not self._use_moc:
            return False

        # Only poll if MOC is the active backend
        if self._active_backend != "moc":
            return True  # Continue polling

        status = self._moc_controller.get_status()
        if not status:
            return True  # Try again later

        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))

        # Update position and duration
        # Batch updates when both change to avoid UI flicker
        if self._operation_state != OperationState.SEEKING:
            # Update position first
            self._set_position(position)
        # Update duration if it changed (this publishes DURATION_CHANGED event)
        if duration > 0:
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
        elif not moc_shuffle and not self._shuffle_enabled:
            # Both off - no change
            pass
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
            if self._playlist.get_next_index() >= 0:
                self._handle_track_finished()
            else:
                self._set_playback_state(PlaybackState.STOPPED)
                self._set_position(0.0)
                self._set_duration(0.0)

        # Detect playlist file changes
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
        next_idx = self._playlist.get_next_index()
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
        """Check for MOC playlist file changes."""
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if not moc_playlist_path.exists():
                if self._moc_playlist_mtime > 0:
                    # File deleted - clear playlist
                    try:
                        self._loading_from_moc = True
                        self._playlist.clear()
                    finally:
                        self._loading_from_moc = False
                    self._moc_playlist_mtime = 0.0
                return

            mtime = moc_playlist_path.stat().st_mtime
            if abs(mtime - self._moc_playlist_mtime) > 0.1:
                recent_write = self._recent_moc_write and (
                    time.time() - self._recent_moc_write < RECENT_WRITE_WINDOW
                )
                if not recent_write and self._startup_complete and not self._syncing_to_moc:
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
        """Reset seek state to IDLE after seek operation completes."""
        self._operation_state = OperationState.IDLE
        # Restore playback state from actual backend state
        # Polling will update it correctly, but set it optimistically based on active backend
        active_backend = self._active_backend
        if active_backend == "moc":
            status = self._moc_controller.get_status(force_refresh=False)
            if status:
                state = status.get("state", "STOP")
                if state == "PLAY":
                    self._set_playback_state(PlaybackState.PLAYING)
                elif state == "PAUSE":
                    self._set_playback_state(PlaybackState.PAUSED)
                else:
                    self._set_playback_state(PlaybackState.STOPPED)
        elif active_backend == "internal":
            if self._internal_player.is_playing:
                self._set_playback_state(PlaybackState.PLAYING)
            elif self._internal_player.current_track:
                self._set_playback_state(PlaybackState.PAUSED)
            else:
                self._set_playback_state(PlaybackState.STOPPED)
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
        self._events.publish(
            EventBus.POSITION_CHANGED,
            {"position": self._position, "duration": self._duration},
        )
        self._events.publish(
            EventBus.DURATION_CHANGED,
            {"duration": self._duration, "position": self._position},
        )
        self._events.publish(EventBus.SHUFFLE_CHANGED, {"enabled": self._shuffle_enabled})
        self._events.publish(EventBus.LOOP_MODE_CHANGED, {"mode": self._loop_mode})
        self._events.publish(EventBus.VOLUME_CHANGED, {"volume": self._volume})
        self._events.publish(
            EventBus.ACTIVE_BACKEND_CHANGED, {"backend": self._active_backend}
        )
        if self._playback_state == PlaybackState.PLAYING:
            self._events.publish(
                EventBus.PLAYBACK_STARTED,
                {"track": self._playlist.get_current_track()},
            )
        elif self._playback_state == PlaybackState.PAUSED:
            self._events.publish(EventBus.PLAYBACK_PAUSED, {})
        else:
            self._events.publish(EventBus.PLAYBACK_STOPPED, {})

    def cleanup(self) -> None:
        if self._use_moc:
            self._moc_controller.shutdown()
