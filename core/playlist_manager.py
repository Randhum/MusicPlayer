"""Playlist management for tracks."""

import json
import random
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

logger = get_logger(__name__)


class PlaylistManager:
    """In-memory playlist and persistence. Single source of truth; publishes PLAYLIST_CHANGED (and index/track when needed) so UI and PlaybackController react via pub/sub."""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        playlists_dir: Optional[Path] = None,
    ) -> None:
        """
        Initialize playlist manager.

        Args:
            event_bus: EventBus instance for publishing playlist events. If None, no events are published.
            playlists_dir: Directory for storing saved playlists.
                          If None, uses config default.
        """
        self._event_bus = event_bus
        if playlists_dir is None:
            from core.config import get_config

            config = get_config()
            playlists_dir = config.playlists_dir
        self.playlists_dir = Path(playlists_dir)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)

        self.current_playlist: List[TrackMetadata] = []
        self.current_index: int = -1
        self._auto_save_enabled: bool = True
        self._shuffle_enabled: bool = False
        self._shuffle_queue: List[int] = []
        self._moc_playlist_provider: Optional[
            Callable[..., Tuple[List[TrackMetadata], int]]
        ] = None

        if self._event_bus:
            self._event_bus.subscribe(
                EventBus.SHUFFLE_CHANGED, self._on_shuffle_changed
            )
            # Note: RELOAD_PLAYLIST_FROM_MOC subscription removed (event was never published)
            self._event_bus.subscribe(EventBus.ADD_FOLDER, self._on_add_folder)
            self._event_bus.subscribe(EventBus.ACTION_MOVE, self._on_action_move)
            self._event_bus.subscribe(EventBus.ACTION_REMOVE, self._on_action_remove)
            self._event_bus.subscribe(
                EventBus.ACTION_CLEAR_PLAYLIST, self._on_action_clear_playlist
            )
            self._event_bus.subscribe(
                EventBus.ACTION_REPLACE_PLAYLIST, self._on_action_replace_playlist
            )

    def set_moc_playlist_provider(
        self,
        provider: Optional[Callable[..., Tuple[List[TrackMetadata], int]]],
    ) -> None:
        """Set or clear the MOC playlist provider (call with None when MOC unavailable)."""
        self._moc_playlist_provider = provider

    def _on_shuffle_changed(self, data: Optional[dict]) -> None:
        self._shuffle_enabled = bool(data.get("enabled", False)) if data else False
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        else:
            self._shuffle_queue = []

    def _regenerate_shuffle_queue(self) -> None:
        n = len(self.current_playlist)
        indices = list(range(n))
        random.shuffle(indices)
        cur = self.current_index
        if 0 <= cur < n and cur in indices:
            indices.remove(cur)
            indices.append(cur)
        self._shuffle_queue = indices

    def has_next(self) -> bool:
        """Check if there is a next track (read-only, does not consume shuffle queue)."""
        if not self.current_playlist:
            return False
        if not self._shuffle_enabled:
            return self.current_index < len(self.current_playlist) - 1
        # In shuffle mode, check if queue has valid entries
        return bool(self._shuffle_queue) or len(self.current_playlist) > 1

    def advance_to_next(self) -> int:
        """Get next index and consume from shuffle queue if shuffled.

        Returns the next index (-1 if none). For shuffle mode, this pops from the queue.
        Does NOT mutate current_index - caller should use set_current_index() to apply.
        """
        if not self.current_playlist:
            return -1
        if not self._shuffle_enabled:
            return (
                self.current_index + 1
                if self.current_index < len(self.current_playlist) - 1
                else -1
            )
        while self._shuffle_queue:
            idx = self._shuffle_queue.pop(0)
            if 0 <= idx < len(self.current_playlist):
                return idx
        self._regenerate_shuffle_queue()
        return self._shuffle_queue.pop(0) if self._shuffle_queue else -1

    # Note: _on_reload_from_moc_requested() removed (RELOAD_PLAYLIST_FROM_MOC was never published)

    def reload_from_moc(self, current_file: Optional[str] = None) -> bool:
        """Load playlist from MOC via the injected provider and apply with set_playlist. Returns True if reloaded."""
        if self._moc_playlist_provider is None:
            return False
        tracks, current_index = self._moc_playlist_provider(current_file=current_file)
        if not tracks:
            return False
        self.set_playlist(tracks, current_index)
        return True

    def _on_add_folder(self, data: Optional[dict]) -> None:
        """Subscriber: ADD_FOLDER with data['tracks'] (optional 'position') → add_tracks."""
        if not data or "tracks" not in data:
            return
        tracks = data["tracks"]
        position = (
            data.get("position") if isinstance(data.get("position"), int) else None
        )
        if isinstance(tracks, list) and tracks:
            self.add_tracks(tracks, position)

    def _on_action_move(self, data: Optional[dict]) -> None:
        """Subscriber: ACTION_MOVE with from_index, to_index → move_track."""
        if not data or "from_index" not in data or "to_index" not in data:
            return
        self.move_track(int(data["from_index"]), int(data["to_index"]))

    def _on_action_remove(self, data: Optional[dict]) -> None:
        """Subscriber: ACTION_REMOVE with index → remove_track."""
        if not data or "index" not in data:
            return
        self.remove_track(int(data["index"]))

    def _on_action_clear_playlist(self, data: Optional[dict]) -> None:
        """Subscriber: ACTION_CLEAR_PLAYLIST → clear."""
        self.clear()

    def _on_action_replace_playlist(self, data: Optional[dict]) -> None:
        """Subscriber: ACTION_REPLACE_PLAYLIST → replace entire playlist.

        Data fields:
            tracks: List of TrackMetadata (or dicts) to set as new playlist
            current_index: Index to set as current (default 0)
            start_playback: If True, caller expects playback to start (handled by PlaybackController)
        """
        if not data:
            return
        tracks = data.get("tracks", [])
        if not isinstance(tracks, list):
            return
        # Convert dicts to TrackMetadata if needed
        track_list = []
        for t in tracks:
            if isinstance(t, TrackMetadata):
                track_list.append(t)
            elif isinstance(t, dict):
                track_list.append(TrackMetadata.from_dict(t))
        current_index = data.get("current_index", 0) if track_list else -1
        start_playback = data.get("start_playback", False)
        self.set_playlist(track_list, current_index, start_playback=start_playback)

    def set_playlist(
        self,
        tracks: List[TrackMetadata],
        current_index: int = -1,
        start_playback: bool = False,
    ) -> None:
        """Replace playlist and index in one go; publish once; sync to file. Used by view and load paths."""
        self.current_playlist = list(tracks)
        self.current_index = (
            current_index if 0 <= current_index < len(self.current_playlist) else -1
        )
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._emit_playlist_replaced(start_playback=start_playback)
        self._sync_to_file()

    def _emit_playlist_replaced(self, start_playback: bool = False) -> None:
        """Publish PLAYLIST_CHANGED and, if index valid, CURRENT_INDEX_CHANGED and TRACK_CHANGED."""
        if not self._event_bus:
            return
        self._event_bus.publish(
            EventBus.PLAYLIST_CHANGED,
            {
                "playlist_changed": True,
                "index": self.current_index,
                "playlist_length": len(self.current_playlist),
                "content_changed": True,
                "start_playback": start_playback,
            },
        )
        if self.current_index >= 0:
            self._event_bus.publish(
                EventBus.CURRENT_INDEX_CHANGED,
                {"index": self.current_index, "old_index": -1},
            )
            track = self.get_current_track()
            if track:
                self._event_bus.publish(EventBus.TRACK_CHANGED, {"track": track})

    def _emit_current_track_changed(self, old_index: int) -> None:
        """Publish CURRENT_INDEX_CHANGED and TRACK_CHANGED when current index/track changed."""
        if not self._event_bus or old_index == self.current_index:
            return
        self._event_bus.publish(
            EventBus.CURRENT_INDEX_CHANGED,
            {"index": self.current_index, "old_index": old_index},
        )
        self._event_bus.publish(
            EventBus.TRACK_CHANGED, {"track": self.get_current_track()}
        )

    def add_track(self, track: TrackMetadata, position: Optional[int] = None) -> None:
        """
        Add a track to the current playlist.

        Args:
            track: Track metadata to add
            position: Insert position (None appends to end)
        """
        old_index = self.current_index
        if position is None:
            self.current_playlist.append(track)
            position = len(self.current_playlist) - 1
        else:
            self.current_playlist.insert(position, track)
            # Keep current_index pointing at same logical track when inserting before it
            if position <= self.current_index:
                self.current_index += 1
        if self._event_bus:
            self._event_bus.publish(
                EventBus.PLAYLIST_CHANGED,
                {
                    "playlist_changed": True,
                    "index": self.current_index,
                    "playlist_length": len(self.current_playlist),
                    "content_changed": True,
                },
            )
            self._emit_current_track_changed(old_index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._sync_to_file()

    def add_tracks(
        self, tracks: List[TrackMetadata], position: Optional[int] = None
    ) -> None:
        """
        Add multiple tracks to the current playlist.

        Args:
            tracks: List of track metadata to add
            position: Insert position (None appends to end)
        """
        old_index = self.current_index
        if position is None:
            self.current_playlist.extend(tracks)
        else:
            for i, track in enumerate(tracks):
                self.current_playlist.insert(position + i, track)
            # Keep current_index pointing at same logical track when inserting before it
            if position <= self.current_index:
                self.current_index += len(tracks)
        if self._event_bus:
            self._event_bus.publish(
                EventBus.PLAYLIST_CHANGED,
                {
                    "playlist_changed": True,
                    "index": self.current_index,
                    "playlist_length": len(self.current_playlist),
                    "content_changed": True,
                },
            )
            self._emit_current_track_changed(old_index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._sync_to_file()

    def remove_track(self, index: int) -> None:
        """
        Remove a track from the current playlist.

        Args:
            index: Index of track to remove
        """
        if not (0 <= index < len(self.current_playlist)):
            return
        old_index = self.current_index
        removed_current = index == self.current_index
        removed_track = self.current_playlist.pop(index)
        if index < self.current_index:
            self.current_index -= 1
        elif index == self.current_index:
            # When removing the current track, reset index and stop playback
            self.current_index = -1
        if self._event_bus:
            # If we removed the currently playing track, request playback stop
            # ACTION_STOP with reason="track_removed" indicates system-initiated stop
            if removed_current:
                self._event_bus.publish(
                    EventBus.ACTION_STOP, {"reason": "track_removed"}
                )
            self._event_bus.publish(
                EventBus.PLAYLIST_CHANGED,
                {
                    "playlist_changed": True,
                    "index": self.current_index,
                    "playlist_length": len(self.current_playlist),
                    "content_changed": True,
                },
            )
            self._emit_current_track_changed(old_index)
        # Regenerate shuffle queue when tracks are removed (indices change)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._sync_to_file()

    def move_track(self, from_index: int, to_index: int) -> None:
        """
        Move a track from one position to another.

        Args:
            from_index: Source position (where track currently is)
            to_index: Destination position (where track should end up)

        After the move, the track is at position to_index in the final list.
        Example: move_track(0, 3) on [A,B,C,D,E] results in [B,C,D,A,E] with A at index 3.
        """
        if not (
            0 <= from_index < len(self.current_playlist)
            and 0 <= to_index < len(self.current_playlist)
        ):
            return
        old_index = self.current_index
        track = self.current_playlist.pop(from_index)
        # After pop, insert at to_index puts the track at final position to_index
        # This works for both forward and backward moves
        self.current_playlist.insert(to_index, track)
        if self.current_index == from_index:
            self.current_index = to_index
        elif from_index < self.current_index <= to_index:
            self.current_index -= 1
        elif to_index <= self.current_index < from_index:
            self.current_index += 1
        if self._event_bus:
            self._event_bus.publish(
                EventBus.PLAYLIST_CHANGED,
                {
                    "playlist_changed": True,
                    "index": self.current_index,
                    "playlist_length": len(self.current_playlist),
                    "content_changed": True,
                },
            )
            self._emit_current_track_changed(old_index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._sync_to_file()

    def clear(self) -> None:
        """Clear the current playlist and reset index."""
        old_index = self.current_index
        self.current_playlist.clear()
        self.current_index = -1
        if self._event_bus:
            self._event_bus.publish(
                EventBus.PLAYLIST_CHANGED,
                {
                    "playlist_changed": True,
                    "index": -1,
                    "playlist_length": 0,
                    "content_changed": True,
                },
            )
            self._emit_current_track_changed(old_index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._sync_to_file()

    def get_current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track."""
        if 0 <= self.current_index < len(self.current_playlist):
            return self.current_playlist[self.current_index]
        return None

    def set_current_index(self, index: int) -> None:
        """
        Set the current playing index.

        Args:
            index: New current index (-1 for none, or 0..len-1)
        """
        if index < -1 or index >= len(self.current_playlist):
            index = -1
        old_index = self.current_index
        self.current_index = index
        if index >= 0 and index in self._shuffle_queue:
            self._shuffle_queue.remove(index)
        if self._event_bus and old_index != index:
            self._event_bus.publish(
                EventBus.CURRENT_INDEX_CHANGED,
                {"index": index, "old_index": old_index},
            )
            new_track = self.get_current_track()
            self._event_bus.publish(EventBus.TRACK_CHANGED, {"track": new_track})
        self._sync_to_file()

    # Note: get_next_track() removed - use advance_to_next() then get_current_track()

    def get_previous_track(self) -> Optional[TrackMetadata]:
        """Get the previous track in the playlist."""
        if self.current_index > 0:
            self.current_index -= 1
            return self.current_playlist[self.current_index]
        return None

    def save_playlist(self, name: str) -> bool:
        """Save the current playlist to a file.

        Args:
            name: Name of the playlist to save.

        Returns:
            True if playlist was saved successfully, False otherwise.
        """
        try:
            # Security: Validate playlist name
            sanitized_name = SecurityValidator.validate_playlist_name(name)
            if not sanitized_name:
                logger.error("Invalid playlist name: %s", name)
                return False

            playlist_file = self.playlists_dir / f"{sanitized_name}.json"

            playlist_data = {
                "name": name,
                "tracks": [track.to_dict() for track in self.current_playlist],
            }

            with open(playlist_file, "w", encoding="utf-8") as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)

            return True
        except (OSError, IOError) as e:
            logger.error("Error saving playlist: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error("Unexpected error saving playlist: %s", e, exc_info=True)
            return False

    def load_playlist(self, name: str) -> bool:
        """Load a playlist from a file.

        Args:
            name: Name of the playlist to load.

        Returns:
            True if playlist was loaded successfully, False if playlist doesn't exist or error occurred.
        """
        try:
            # Security: Validate playlist name
            sanitized_name = SecurityValidator.validate_playlist_name(name)
            if not sanitized_name:
                logger.error("Invalid playlist name: %s", name)
                return False

            playlist_file = self.playlists_dir / f"{sanitized_name}.json"

            if not playlist_file.exists():
                return False

            with open(playlist_file, "r", encoding="utf-8") as f:
                playlist_data = json.load(f)
            tracks = [
                TrackMetadata.from_dict(track_dict)
                for track_dict in playlist_data.get("tracks", [])
            ]
            current_index = playlist_data.get("current_index", -1)
            if current_index >= len(tracks):
                current_index = -1
            self.set_playlist(tracks, current_index)
            return True
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.error("Error loading playlist: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error("Unexpected error loading playlist: %s", e, exc_info=True)
            return False

    def list_playlists(self) -> List[str]:
        """List all saved playlists."""
        playlists = []
        for playlist_file in self.playlists_dir.glob("*.json"):
            playlists.append(playlist_file.stem)
        return sorted(playlists)

    def delete_playlist(self, name: str) -> bool:
        """Delete a saved playlist.

        Args:
            name: Name of the playlist to delete.

        Returns:
            True if playlist was deleted successfully, False if playlist doesn't exist or error occurred.
        """
        try:
            # Security: Validate playlist name
            sanitized_name = SecurityValidator.validate_playlist_name(name)
            if not sanitized_name:
                logger.error("Invalid playlist name: %s", name)
                return False

            playlist_file = self.playlists_dir / f"{sanitized_name}.json"
            if playlist_file.exists():
                playlist_file.unlink()
                return True
            return False
        except OSError as e:
            logger.error("Error deleting playlist: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error("Unexpected error deleting playlist: %s", e, exc_info=True)
            return False

    def get_playlist(self) -> List[TrackMetadata]:
        """Get the current playlist."""
        return self.current_playlist.copy()

    def get_current_index(self) -> int:
        """Get the current playing index."""
        return self.current_index

    @property
    def current_playlist_file(self) -> Path:
        """Get the path to the current playlist auto-save file."""
        return self.playlists_dir / "current_playlist.json"

    def _sync_to_file(self) -> None:
        """Auto-save current playlist to JSON file (sync for small, threaded for large)."""
        if not self._auto_save_enabled:
            return
        try:
            if len(self.current_playlist) > 200:
                import threading

                playlist_copy = self.current_playlist.copy()
                index_copy = self.current_index

                def save():
                    try:
                        data = {
                            "tracks": [t.to_dict() for t in playlist_copy],
                            "current_index": index_copy,
                        }
                        with open(
                            self.current_playlist_file, "w", encoding="utf-8"
                        ) as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    except Exception as e:
                        logger.warning("Failed to auto-save current playlist: %s", e)

                threading.Thread(target=save, daemon=True).start()
            else:
                data = {
                    "tracks": [t.to_dict() for t in self.current_playlist],
                    "current_index": self.current_index,
                }
                with open(self.current_playlist_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to auto-save current playlist: %s", e)

    def load_current_playlist(self) -> bool:
        """Load the current playlist from auto-save file. Replaces and publishes once via set_playlist."""
        if not self.current_playlist_file.exists():
            return False
        try:
            with open(self.current_playlist_file, "r", encoding="utf-8") as f:
                playlist_data = json.load(f)
            tracks = [
                TrackMetadata.from_dict(track_dict)
                for track_dict in playlist_data.get("tracks", [])
            ]
            current_index = playlist_data.get("current_index", -1)
            if current_index >= len(tracks):
                current_index = -1
            self.set_playlist(tracks, current_index)
            return True
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.error("Error loading current playlist: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Unexpected error loading current playlist: %s", e, exc_info=True
            )
            return False
