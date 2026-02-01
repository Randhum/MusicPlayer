"""Centralized event bus for decoupled component communication."""
from typing import Any, Callable, Dict, List
from core.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    """Publish-subscribe event system. Components publish/subscribe without knowing each other."""

    PLAYBACK_STARTED = "playback.started"
    PLAYBACK_PAUSED = "playback.paused"
    PLAYBACK_STOPPED = "playback.stopped"
    TRACK_CHANGED = "track.changed"
    POSITION_CHANGED = "position.changed"
    DURATION_CHANGED = "duration.changed"
    PLAYLIST_CHANGED = "playlist.changed"
    CURRENT_INDEX_CHANGED = "playlist.current_index_changed"
    RELOAD_PLAYLIST_FROM_MOC = "playlist.reload_from_moc"
    SHUFFLE_CHANGED = "playback.shuffle_changed"
    LOOP_MODE_CHANGED = "playback.loop_mode_changed"
    AUTONEXT_CHANGED = "playback.autonext_changed"
    ACTIVE_BACKEND_CHANGED = "playback.active_backend_changed"
    BT_DEVICE_CONNECTED = "bluetooth.device_connected"
    BT_DEVICE_DISCONNECTED = "bluetooth.device_disconnected"
    BT_DEVICE_ADDED = "bluetooth.device_added"
    BT_DEVICE_REMOVED = "bluetooth.device_removed"
    BT_SINK_ENABLED = "bluetooth.sink_enabled"
    BT_SINK_DISABLED = "bluetooth.sink_disabled"
    BT_SINK_DEVICE_CONNECTED = "bluetooth.sink_device_connected"
    VOLUME_CHANGED = "volume.changed"
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
    ACTION_SYNC_PLAYLIST_TO_MOC = "action.sync_playlist_to_moc"
    ACTION_APPEND_FOLDER = "action.append_folder"
    ADD_FOLDER = "playlist.add_folder"
    ACTION_MOVE = "action.move"
    ACTION_REMOVE = "action.remove"
    ACTION_CLEAR_PLAYLIST = "action.clear_playlist"

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._debug_enabled = False

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
        if self._debug_enabled:
            logger.debug("Publishing event: %s (data: %s)", event, data)
        for callback in self._subscribers.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.error("Error in event callback for %s: %s", event, e, exc_info=True)

    def set_debug(self, enabled: bool) -> None:
        self._debug_enabled = enabled
