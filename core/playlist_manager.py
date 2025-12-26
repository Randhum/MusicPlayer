"""Playlist management for tracks."""

import json
from pathlib import Path
from typing import List, Optional

from core.metadata import TrackMetadata
from core.logging import get_logger
from core.config import get_config

logger = get_logger(__name__)


class PlaylistManager:
    """Manages playlists - works directly with playlist files using indexes."""
    
    def __init__(self, playlists_dir: Optional[Path] = None):
        if playlists_dir is None:
            playlists_dir = Path(__file__).parent.parent / 'data' / 'playlists'
        self.playlists_dir = Path(playlists_dir)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        
        # Current playlist file path (None means no active playlist file)
        config = get_config()
        self.current_playlist_file: Optional[Path] = config.cache_dir / 'current_playlist.json'
        
        # In-memory cache (optional, for quick access)
        self.current_playlist: List[TrackMetadata] = []
        self.current_index: int = -1
        
        # Load playlist from file on initialization
        self.load_playlist_from_file()
    
    def add_track(self, track: TrackMetadata, position: Optional[int] = None):
        """Add a track to the current playlist."""
        if position is None:
            self.current_playlist.append(track)
        else:
            self.current_playlist.insert(position, track)
    
    def add_tracks(self, tracks: List[TrackMetadata], position: Optional[int] = None):
        """Add multiple tracks to the current playlist."""
        if position is None:
            self.current_playlist.extend(tracks)
        else:
            for i, track in enumerate(tracks):
                self.current_playlist.insert(position + i, track)
    
    def remove_track(self, index: int):
        """Remove a track from the current playlist."""
        if 0 <= index < len(self.current_playlist):
            self.current_playlist.pop(index)
            # Adjust current index if needed
            if index < self.current_index:
                self.current_index -= 1
            elif index == self.current_index:
                self.current_index = -1
    
    def move_track(self, from_index: int, to_index: int):
        """Move a track from one position to another."""
        if 0 <= from_index < len(self.current_playlist) and 0 <= to_index < len(self.current_playlist):
            track = self.current_playlist.pop(from_index)
            self.current_playlist.insert(to_index, track)
            # Update current index
            if self.current_index == from_index:
                self.current_index = to_index
            elif from_index < self.current_index <= to_index:
                self.current_index -= 1
            elif to_index <= self.current_index < from_index:
                self.current_index += 1
    
    def clear(self):
        """Clear the current playlist."""
        self.current_playlist.clear()
        self.current_index = -1
    
    def get_current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track."""
        if 0 <= self.current_index < len(self.current_playlist):
            return self.current_playlist[self.current_index]
        return None
    
    def set_current_index(self, index: int):
        """Set the current playing index."""
        data = self._read_playlist_file()
        tracks = data.get('tracks', [])
        if 0 <= index < len(tracks):
            self.current_index = index
            data['current_index'] = index
            self._write_playlist_file(data)
        elif 0 <= index < len(self.current_playlist):
            # Fallback to in-memory if file doesn't have tracks yet
            self.current_index = index
    
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
        """Save the current playlist to a file."""
        try:
            playlist_file = self.playlists_dir / f"{name}.json"
            
            playlist_data = {
                'name': name,
                'tracks': [track.to_dict() for track in self.current_playlist]
            }
            
            with open(playlist_file, 'w', encoding='utf-8') as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)
            
            return True
        except Exception as e:
            logger.error("Error saving playlist: %s", e, exc_info=True)
            return False
    
    def load_playlist(self, name: str) -> bool:
        """Load a playlist from a file."""
        try:
            playlist_file = self.playlists_dir / f"{name}.json"
            
            if not playlist_file.exists():
                return False
            
            with open(playlist_file, 'r', encoding='utf-8') as f:
                playlist_data = json.load(f)
            
            self.current_playlist = [
                TrackMetadata.from_dict(track_dict)
                for track_dict in playlist_data.get('tracks', [])
            ]
            self.current_index = -1
            
            return True
        except Exception as e:
            logger.error("Error loading playlist: %s", e, exc_info=True)
            return False
    
    def list_playlists(self) -> List[str]:
        """List all saved playlists."""
        playlists = []
        for playlist_file in self.playlists_dir.glob('*.json'):
            playlists.append(playlist_file.stem)
        return sorted(playlists)
    
    def delete_playlist(self, name: str) -> bool:
        """Delete a saved playlist."""
        try:
            playlist_file = self.playlists_dir / f"{name}.json"
            if playlist_file.exists():
                playlist_file.unlink()
                return True
            return False
        except Exception as e:
            logger.error("Error deleting playlist: %s", e, exc_info=True)
            return False
    
    def get_playlist(self) -> List[TrackMetadata]:
        """Get the current playlist."""
        return self.current_playlist.copy()
    
    def get_current_index(self) -> int:
        """Get the current playing index."""
        data = self._read_playlist_file()
        file_index = data.get('current_index', -1)
        # Use file index if available, otherwise fallback to in-memory
        if file_index != -1 or len(data.get('tracks', [])) > 0:
            self.current_index = file_index
            return file_index
        return self.current_index
    
    # ------------------------------------------------------------------
    # File-based index operations (work directly with JSON file)
    # ------------------------------------------------------------------
    
    def _get_playlist_file(self) -> Path:
        """Get the current playlist file path."""
        return self.current_playlist_file
    
    def _read_playlist_file(self) -> Optional[dict]:
        """Read the current playlist file and return its contents."""
        playlist_file = self._get_playlist_file()
        if not playlist_file.exists():
            return {'name': 'current', 'tracks': [], 'current_index': -1}
        
        try:
            with open(playlist_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure current_index exists for backward compatibility
                if 'current_index' not in data:
                    data['current_index'] = -1
                return data
        except Exception as e:
            logger.error("Error reading playlist file: %s", e, exc_info=True)
            return {'name': 'current', 'tracks': [], 'current_index': -1}
    
    def _write_playlist_file(self, data: dict):
        """Write playlist data to file."""
        playlist_file = self._get_playlist_file()
        try:
            # Write atomically using temp file
            temp_file = playlist_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(playlist_file)
        except Exception as e:
            logger.error("Error writing playlist file: %s", e, exc_info=True)
    
    def add_track_at_index_file(self, index: int, track: TrackMetadata) -> bool:
        """
        Add a track at a specific index directly in the playlist file.
        
        Args:
            index: Position where to insert (0-based)
            track: Track to add
            
        Returns:
            True if successful
        """
        data = self._read_playlist_file()
        tracks = data.get('tracks', [])
        current_index = data.get('current_index', -1)
        
        # Validate index
        if index < 0:
            index = 0
        if index > len(tracks):
            index = len(tracks)
        
        # Insert track dict at index
        track_dict = track.to_dict()
        tracks.insert(index, track_dict)
        data['tracks'] = tracks
        
        # Adjust current index if needed
        if index <= current_index:
            current_index += 1
        data['current_index'] = current_index
        
        self._write_playlist_file(data)
        
        return True
    
    def remove_track_at_index_file(self, index: int) -> bool:
        """
        Remove a track at a specific index directly from the playlist file.
        
        Args:
            index: Index of track to remove (0-based)
            
        Returns:
            True if successful
        """
        data = self._read_playlist_file()
        tracks = data.get('tracks', [])
        current_index = data.get('current_index', -1)
        
        if not (0 <= index < len(tracks)):
            return False
        
        # Remove track at index
        tracks.pop(index)
        data['tracks'] = tracks
        
        # Adjust current index if needed
        if index < current_index:
            current_index -= 1
        elif index == current_index:
            current_index = -1
        data['current_index'] = current_index
        
        self._write_playlist_file(data)
        
        return True
    
    def move_track_in_file(self, from_index: int, to_index: int) -> bool:
        """
        Move a track from one index to another directly in the playlist file.
        
        Args:
            from_index: Current index of the track
            to_index: Target index for the track
            
        Returns:
            True if successful
        """
        data = self._read_playlist_file()
        tracks = data.get('tracks', [])
        current_index = data.get('current_index', -1)
        
        if not (0 <= from_index < len(tracks) and 0 <= to_index < len(tracks)):
            return False
        
        if from_index == to_index:
            return True
        
        # Move track
        track_dict = tracks.pop(from_index)
        tracks.insert(to_index, track_dict)
        data['tracks'] = tracks
        
        # Update current index
        if current_index == from_index:
            current_index = to_index
        elif from_index < current_index <= to_index:
            current_index -= 1
        elif to_index <= current_index < from_index:
            current_index += 1
        data['current_index'] = current_index
        
        self._write_playlist_file(data)
        
        return True
    
    def get_track_at_index_file(self, index: int) -> Optional[TrackMetadata]:
        """
        Get track at a specific index from the playlist file.
        
        Args:
            index: Index of track to get
            
        Returns:
            TrackMetadata or None if index is invalid
        """
        data = self._read_playlist_file()
        tracks = data.get('tracks', [])
        
        if not (0 <= index < len(tracks)):
            return None
        
        return TrackMetadata.from_dict(tracks[index])
    
    def get_playlist_length_file(self) -> int:
        """Get the length of the playlist from file."""
        data = self._read_playlist_file()
        return len(data.get('tracks', []))
    
    def clear_playlist_file(self):
        """Clear the playlist file."""
        data = {'name': 'current', 'tracks': [], 'current_index': -1}
        self._write_playlist_file(data)
    
    def load_playlist_from_file(self) -> bool:
        """Load the current playlist from file into memory cache."""
        data = self._read_playlist_file()
        tracks_data = data.get('tracks', [])
        
        self.current_playlist = [
            TrackMetadata.from_dict(track_dict)
            for track_dict in tracks_data
        ]
        
        # Load current_index from file
        self.current_index = data.get('current_index', -1)
        
        return True

