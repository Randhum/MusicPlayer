"""Playlist management for tracks."""

import json
import random
from pathlib import Path
from typing import List, Optional
from core.metadata import TrackMetadata


class PlaylistManager:
    """Manages playlists - in-memory and persistent storage."""
    
    def __init__(self, playlists_dir: Optional[Path] = None):
        if playlists_dir is None:
            playlists_dir = Path(__file__).parent.parent / 'data' / 'playlists'
        self.playlists_dir = Path(playlists_dir)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_playlist: List[TrackMetadata] = []
        self.current_index: int = -1
    
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
    
    def shuffle(self):
        """Shuffle the playlist randomly, keeping current track at position 0."""
        if len(self.current_playlist) <= 1:
            return
        
        # If there's a current track, move it to the front, then shuffle the rest
        if 0 <= self.current_index < len(self.current_playlist):
            current_track = self.current_playlist[self.current_index]
            remaining = [t for i, t in enumerate(self.current_playlist) if i != self.current_index]
            random.shuffle(remaining)
            self.current_playlist = [current_track] + remaining
            self.current_index = 0
        else:
            # No current track, shuffle everything
            random.shuffle(self.current_playlist)
            self.current_index = -1
    
    def get_current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track."""
        if 0 <= self.current_index < len(self.current_playlist):
            return self.current_playlist[self.current_index]
        return None
    
    def set_current_index(self, index: int):
        """Set the current playing index."""
        if 0 <= index < len(self.current_playlist):
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
            print(f"Error saving playlist: {e}")
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
            print(f"Error loading playlist: {e}")
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
            print(f"Error deleting playlist: {e}")
            return False
    
    def get_playlist(self) -> List[TrackMetadata]:
        """Get the current playlist."""
        return self.current_playlist.copy()
    
    def get_current_index(self) -> int:
        """Get the current playing index."""
        return self.current_index

