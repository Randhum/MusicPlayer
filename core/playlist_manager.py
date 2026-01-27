"""Playlist management for tracks."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import json
from pathlib import Path
from typing import List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.exceptions import PlaylistError, SecurityError
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

logger = get_logger(__name__)


class PlaylistManager:
    """Manages playlists - in-memory and persistent storage."""

    def __init__(self, playlists_dir: Optional[Path] = None) -> None:
        """
        Initialize playlist manager.

        Args:
            playlists_dir: Directory for storing saved playlists.
                          If None, uses config default.
        """
        if playlists_dir is None:
            from core.config import get_config

            config = get_config()
            playlists_dir = config.playlists_dir
        self.playlists_dir = Path(playlists_dir)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)

        self.current_playlist: List[TrackMetadata] = []
        self.current_index: int = -1

        # Auto-save flag to prevent recursive saves during load
        self._auto_save_enabled: bool = True

    def add_track(self, track: TrackMetadata, position: Optional[int] = None) -> None:
        """
        Add a track to the current playlist.

        Args:
            track: Track metadata to add
            position: Insert position (None appends to end)
        
        Note: File sync is handled by PlaylistView's debounced sync mechanism.
        This method only updates in-memory state.
        """
        if position is None:
            self.current_playlist.append(track)
        else:
            self.current_playlist.insert(position, track)
        # File sync is handled by PlaylistView's debounced sync mechanism

    def add_tracks(
        self, tracks: List[TrackMetadata], position: Optional[int] = None
    ) -> None:
        """
        Add multiple tracks to the current playlist.

        Args:
            tracks: List of track metadata to add
            position: Insert position (None appends to end)
        
        Note: File sync is handled by PlaylistView's debounced sync mechanism.
        This method only updates in-memory state.
        """
        if position is None:
            self.current_playlist.extend(tracks)
        else:
            for i, track in enumerate(tracks):
                self.current_playlist.insert(position + i, track)
        # File sync is handled by PlaylistView's debounced sync mechanism

    def remove_track(self, index: int) -> None:
        """
        Remove a track from the current playlist.

        Args:
            index: Index of track to remove
        
        Note: File sync and current_index updates are handled by PlaylistView's
        debounced sync mechanism. This method only updates in-memory playlist state.
        """
        if 0 <= index < len(self.current_playlist):
            self.current_playlist.pop(index)
            # Note: current_index adjustment is handled by AppState and synced via
            # PlaylistView's debounced sync mechanism
        # File sync is handled by PlaylistView's debounced sync mechanism

    def move_track(self, from_index: int, to_index: int) -> None:
        """
        Move a track from one position to another.

        Args:
            from_index: Source position (where track currently is)
            to_index: Destination position (where track should end up)
        
        Note: After the move, the track will be at position `to_index` in the final list.
        File sync and current_index updates are handled by PlaylistView's debounced
        sync mechanism. This method only updates in-memory playlist state.
        """
        if 0 <= from_index < len(self.current_playlist) and 0 <= to_index < len(
            self.current_playlist
        ):
            # Remove track from old position
            track = self.current_playlist.pop(from_index)
            
            # Calculate where to insert (accounting for the pop that shifted indices)
            if from_index < to_index:
                # Moving down: after pop, target position shifted left by 1
                insert_index = to_index - 1
            else:
                # Moving up: target position unchanged after pop
                insert_index = to_index
            
            # Insert at calculated position (track ends up at to_index)
            self.current_playlist.insert(insert_index, track)
            
            # Note: current_index is managed by AppState and synced via
            # PlaylistView's debounced sync mechanism
        # File sync is handled by PlaylistView's debounced sync mechanism

    def clear(self) -> None:
        """
        Clear the current playlist and reset index.
        
        Note: File sync is handled by PlaylistView's debounced sync mechanism.
        This method only updates in-memory state.
        """
        self.current_playlist.clear()
        self.current_index = -1
        # File sync is handled by PlaylistView's debounced sync mechanism

    def get_current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track."""
        if 0 <= self.current_index < len(self.current_playlist):
            return self.current_playlist[self.current_index]
        return None

    def set_current_index(self, index: int) -> None:
        """
        Set the current playing index.

        Args:
            index: New current index (must be valid)
        """
        if 0 <= index < len(self.current_playlist):
            self.current_index = index
            self._sync_to_file()

    def get_next_track(self) -> Optional[TrackMetadata]:
        """Get the next track in the playlist."""
        if self.current_index < len(self.current_playlist) - 1:
            self.current_index += 1
            return self.current_playlist[self.current_index]
        return None

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

            self._auto_save_enabled = False  # Prevent save during load
            try:
                self.current_playlist = [
                    TrackMetadata.from_dict(track_dict)
                    for track_dict in playlist_data.get("tracks", [])
                ]
                self.current_index = playlist_data.get("current_index", -1)
                # Clamp index to valid range
                if self.current_index >= len(self.current_playlist):
                    self.current_index = -1
            finally:
                self._auto_save_enabled = True
            # Sync after load to ensure consistency
            self._sync_to_file()

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
        """Auto-save current playlist to JSON file."""
        if not self._auto_save_enabled:
            return
        
        # For large playlists, use background thread to avoid blocking
        if len(self.current_playlist) > 200:
            # Use background thread for large playlists
            import threading
            thread = threading.Thread(target=self._sync_to_file_threaded, daemon=True)
            thread.start()
        else:
            # Synchronous save for small playlists (fast enough)
            self._sync_to_file_sync()
    
    def _sync_to_file_sync(self) -> None:
        """Synchronously save playlist to file (internal method)."""
        try:
            playlist_data = {
                "tracks": [track.to_dict() for track in self.current_playlist],
                "current_index": self.current_index,
            }
            with open(self.current_playlist_file, "w", encoding="utf-8") as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to auto-save current playlist: %s", e)
    
    def _sync_to_file_threaded(self) -> None:
        """Save playlist to file in background thread (for large playlists)."""
        try:
            # Copy playlist data to avoid race conditions
            playlist_copy = self.current_playlist.copy()
            index_copy = self.current_index
            
            # Serialize in background thread
            playlist_data = {
                "tracks": [track.to_dict() for track in playlist_copy],
                "current_index": index_copy,
            }
            
            # Write file in background thread
            with open(self.current_playlist_file, "w", encoding="utf-8") as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed to auto-save current playlist in background thread: %s", e)

    def load_current_playlist(self) -> bool:
        """Load the current playlist from auto-save file."""
        if not self.current_playlist_file.exists():
            return False
        try:
            with open(self.current_playlist_file, "r", encoding="utf-8") as f:
                playlist_data = json.load(f)

            self._auto_save_enabled = False  # Prevent save during load
            try:
                self.current_playlist = [
                    TrackMetadata.from_dict(track_dict)
                    for track_dict in playlist_data.get("tracks", [])
                ]
                self.current_index = playlist_data.get("current_index", -1)
                # Clamp index to valid range
                if self.current_index >= len(self.current_playlist):
                    self.current_index = -1
            finally:
                self._auto_save_enabled = True

            return True
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.error("Error loading current playlist: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Unexpected error loading current playlist: %s", e, exc_info=True
            )
            return False
