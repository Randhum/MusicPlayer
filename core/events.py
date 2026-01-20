"""Centralized event bus for decoupled component communication."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from typing import Any, Callable, Dict, List

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    """
    Centralized publish-subscribe event system.
    
    Replaces direct callbacks and circular dependencies with a clean
    event-driven architecture. Components publish events and subscribe
    to events they care about, without knowing about each other.
    """

    # Playback state events
    PLAYBACK_STARTED = "playback.started"
    PLAYBACK_PAUSED = "playback.paused"
    PLAYBACK_STOPPED = "playback.stopped"
    PLAYBACK_RESUMED = "playback.resumed"

    # Track events
    TRACK_CHANGED = "track.changed"
    TRACK_LOADED = "track.loaded"
    TRACK_FINISHED = "track.finished"
    POSITION_CHANGED = "position.changed"
    DURATION_CHANGED = "duration.changed"

    # Playlist events
    PLAYLIST_CHANGED = "playlist.changed"
    PLAYLIST_CLEARED = "playlist.cleared"
    PLAYLIST_TRACK_ADDED = "playlist.track_added"
    PLAYLIST_TRACK_REMOVED = "playlist.track_removed"
    PLAYLIST_TRACK_MOVED = "playlist.track_moved"
    CURRENT_INDEX_CHANGED = "playlist.current_index_changed"

    # Playback control events (shuffle, loop, etc.)
    SHUFFLE_CHANGED = "playback.shuffle_changed"
    LOOP_MODE_CHANGED = "playback.loop_mode_changed"
    AUTONEXT_CHANGED = "playback.autonext_changed"

    # Bluetooth events
    BT_DEVICE_CONNECTED = "bluetooth.device_connected"
    BT_DEVICE_DISCONNECTED = "bluetooth.device_disconnected"
    BT_DEVICE_ADDED = "bluetooth.device_added"
    BT_DEVICE_REMOVED = "bluetooth.device_removed"
    BT_SINK_ENABLED = "bluetooth.sink_enabled"
    BT_SINK_DISABLED = "bluetooth.sink_disabled"
    BT_SINK_DEVICE_CONNECTED = "bluetooth.sink_device_connected"

    # Volume events
    VOLUME_CHANGED = "volume.changed"

    # Action events (user intents - these trigger handlers)
    ACTION_PLAY = "action.play"
    ACTION_PAUSE = "action.pause"
    ACTION_STOP = "action.stop"
    ACTION_NEXT = "action.next"
    ACTION_PREV = "action.previous"
    ACTION_SEEK = "action.seek"
    ACTION_PLAY_TRACK = "action.play_track"  # Play specific track at index
    ACTION_SET_SHUFFLE = "action.set_shuffle"
    ACTION_SET_LOOP_MODE = "action.set_loop_mode"
    ACTION_SET_VOLUME = "action.set_volume"
    ACTION_REFRESH_MOC = "action.refresh_moc"  # Reload playlist from MOC
    ACTION_APPEND_FOLDER = "action.append_folder"  # Append folder to playlist (MOC mode)

    def __init__(self):
        """Initialize the event bus."""
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._debug_enabled = False

    def subscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        """
        Subscribe to an event.

        Args:
            event: Event name (use EventBus constants)
            callback: Callback function that takes event data as argument
        """
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(callback)
        if self._debug_enabled:
            logger.debug("Subscribed to event: %s", event)

    def unsubscribe(self, event: str, callback: Callable[[Any], None]) -> None:
        """
        Unsubscribe from an event.

        Args:
            event: Event name
            callback: Callback function to remove
        """
        if event in self._subscribers:
            try:
                self._subscribers[event].remove(callback)
                if self._debug_enabled:
                    logger.debug("Unsubscribed from event: %s", event)
            except ValueError:
                # Callback not in list - ignore
                pass

    def publish(self, event: str, data: Any = None) -> None:
        """
        Publish an event to all subscribers.

        Args:
            event: Event name (use EventBus constants)
            data: Optional event data (can be any type)
        """
        if self._debug_enabled:
            logger.debug("Publishing event: %s (data: %s)", event, data)

        subscribers = self._subscribers.get(event, [])
        for callback in subscribers:
            try:
                callback(data)
            except Exception as e:
                logger.error(
                    "Error in event callback for %s: %s", event, e, exc_info=True
                )

    def set_debug(self, enabled: bool) -> None:
        """
        Enable or disable debug logging.

        Args:
            enabled: True to enable debug logging
        """
        self._debug_enabled = enabled
