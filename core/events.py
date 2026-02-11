"""Centralized event bus for decoupled component communication."""

from typing import Any, Callable, Dict, List
from core.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    """Publish-subscribe event system. Components publish/subscribe without knowing each other.

    Event Flow Architecture:
    - UI components (PlaylistView, PlayerControls, LibraryBrowser) publish ACTION_* events (requests)
    - Core managers (PlaylistManager, PlaybackController) publish *_CHANGED events (notifications)
    - This separation ensures clear data flow: UI -> Core -> UI
    """

    # =========================================================================
    # Core -> UI: State Change Notifications
    # Published by PlaybackController, PlaylistManager, BluetoothManager, etc.
    # =========================================================================

    # Playback state (published by PlaybackController)
    # Unified playback state event: {"state": "playing"|"paused"|"stopped", "track": TrackMetadata?}
    PLAYBACK_STATE_CHANGED = "playback.state_changed"
    # Note: PLAYBACK_STARTED, PLAYBACK_PAUSED, PLAYBACK_STOPPED merged into PLAYBACK_STATE_CHANGED
    # Note: PLAYBACK_STOP_REQUESTED merged into ACTION_STOP with reason field
    # Unified progress event: {"position": float, "duration": float}
    PLAYBACK_PROGRESS = "playback.progress"
    # Note: POSITION_CHANGED, DURATION_CHANGED merged into PLAYBACK_PROGRESS
    SHUFFLE_CHANGED = "playback.shuffle_changed"
    LOOP_MODE_CHANGED = "playback.loop_mode_changed"
    VOLUME_CHANGED = "volume.changed"
    # Note: AUTONEXT_CHANGED, ACTIVE_BACKEND_CHANGED removed (no subscribers)

    # Playlist state (published by PlaylistManager)
    PLAYLIST_CHANGED = "playlist.changed"
    CURRENT_INDEX_CHANGED = "playlist.current_index_changed"
    TRACK_CHANGED = "track.changed"

    # Bluetooth state (published by BluetoothManager/BluetoothSink)
    BT_DEVICE_CONNECTED = "bluetooth.device_connected"
    BT_DEVICE_DISCONNECTED = "bluetooth.device_disconnected"
    BT_DEVICE_ADDED = "bluetooth.device_added"
    BT_SINK_ENABLED = "bluetooth.sink_enabled"
    BT_SINK_DISABLED = "bluetooth.sink_disabled"
    BT_SINK_DEVICE_CONNECTED = "bluetooth.sink_device_connected"
    # Note: BT_DEVICE_REMOVED removed (no subscribers)

    # =========================================================================
    # UI -> Core: Action Requests
    # Published by PlaylistView, PlayerControls, LibraryBrowser
    # =========================================================================

    # Playback control actions (handled by PlaybackController)
    ACTION_PLAY = "action.play"
    ACTION_PAUSE = "action.pause"
    ACTION_STOP = "action.stop"
    ACTION_NEXT = "action.next"
    ACTION_PREV = "action.previous"
    ACTION_SEEK = "action.seek"
    ACTION_PLAY_TRACK = "action.play_track"
    ACTION_SET_SHUFFLE = "action.set_shuffle"
    ACTION_SET_LOOP_MODE = "action.set_loop_mode"
    ACTION_SET_VOLUME = "action.set_volume"
    ACTION_REFRESH_MOC = "action.refresh_moc"
    # Note: ACTION_APPEND_FOLDER removed - use ADD_FOLDER for all folder additions

    # Playlist modification actions (handled by PlaylistManager)
    ACTION_REPLACE_PLAYLIST = "action.replace_playlist"  # Replace entire playlist
    ADD_FOLDER = "playlist.add_folder"
    ACTION_MOVE = "action.move"
    ACTION_REMOVE = "action.remove"
    ACTION_CLEAR_PLAYLIST = "action.clear_playlist"

    # Note: RELOAD_PLAYLIST_FROM_MOC removed (never published, dead code)

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        if event in self._subscribers:
            try:
                self._subscribers[event].remove(callback)
            except ValueError:
                pass

    def publish(self, event: str, data: Any = None) -> None:
        for callback in self._subscribers.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(
                    "Error in event callback for %s: %s", event, e, exc_info=True
                )
