"""Music library scanning and indexing."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict
import threading

from core.metadata import TrackMetadata


# Supported audio file extensions
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.ogg', '.m4a', '.aac', '.wav', '.opus', '.mp4'}


class MusicLibrary:
    """Manages the music library, scanning and indexing tracks."""
    
    def __init__(self):
        self.tracks: List[TrackMetadata] = []
        self.artists: Dict[str, Dict[str, List[TrackMetadata]]] = defaultdict(lambda: defaultdict(list))
        self._lock = threading.Lock()
        self._scanning = False
    
    def scan_library(self, callback=None):
        """Scan music directories asynchronously."""
        if self._scanning:
            return
        
        def scan_thread():
            self._scanning = True
            try:
                self._do_scan()
                if callback:
                    callback()
            finally:
                self._scanning = False
        
        thread = threading.Thread(target=scan_thread, daemon=True)
        thread.start()
    
    def _do_scan(self):
        """Perform the actual scanning."""
        music_dirs = [
            Path.home() / 'Music',
            Path.home() / 'Musik',
        ]
        
        tracks = []
        for music_dir in music_dirs:
            if music_dir.exists() and music_dir.is_dir():
                tracks.extend(self._scan_directory(music_dir))
        
        with self._lock:
            self.tracks = tracks
            self._rebuild_index()
    
    def _scan_directory(self, directory: Path) -> List[TrackMetadata]:
        """Recursively scan a directory for audio files."""
        tracks = []
        
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                        try:
                            metadata = TrackMetadata(str(file_path))
                            tracks.append(metadata)
                        except Exception as e:
                            print(f"Error processing {file_path}: {e}")
        except Exception as e:
            print(f"Error scanning directory {directory}: {e}")
        
        return tracks
    
    def _rebuild_index(self):
        """Rebuild the artist/album index from tracks."""
        self.artists.clear()
        
        for track in self.tracks:
            # Use album artist if available, otherwise artist
            artist_name = track.album_artist or track.artist or "Unknown Artist"
            album_name = track.album or "Unknown Album"
            
            self.artists[artist_name][album_name].append(track)
        
        # Sort tracks within albums by track number
        for artist in self.artists:
            for album in self.artists[artist]:
                tracks = self.artists[artist][album]
                tracks.sort(key=lambda t: (t.track_number or 999, t.title or ""))
    
    def get_artists(self) -> List[str]:
        """Get list of all artists, sorted."""
        with self._lock:
            return sorted(self.artists.keys())
    
    def get_albums(self, artist: str) -> List[str]:
        """Get list of albums for an artist, sorted."""
        with self._lock:
            if artist in self.artists:
                return sorted(self.artists[artist].keys())
            return []
    
    def get_tracks(self, artist: Optional[str] = None, album: Optional[str] = None) -> List[TrackMetadata]:
        """Get tracks, optionally filtered by artist and/or album."""
        with self._lock:
            if artist and album:
                if artist in self.artists and album in self.artists[artist]:
                    return self.artists[artist][album].copy()
                return []
            elif artist:
                tracks = []
                if artist in self.artists:
                    for album_tracks in self.artists[artist].values():
                        tracks.extend(album_tracks)
                return tracks
            else:
                return self.tracks.copy()
    
    def search(self, query: str) -> List[TrackMetadata]:
        """Search tracks by title, artist, or album."""
        query_lower = query.lower()
        results = []
        
        with self._lock:
            for track in self.tracks:
                matches = False
                
                if track.title and query_lower in track.title.lower():
                    matches = True
                if track.artist and query_lower in track.artist.lower():
                    matches = True
                if track.album and query_lower in track.album.lower():
                    matches = True
                if track.album_artist and query_lower in track.album_artist.lower():
                    matches = True
                
                if matches:
                    results.append(track)
        
        return results
    
    def get_track_count(self) -> int:
        """Get total number of tracks."""
        with self._lock:
            return len(self.tracks)
    
    def is_scanning(self) -> bool:
        """Check if library is currently being scanned."""
        return self._scanning

