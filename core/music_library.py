"""Music library scanning and indexing."""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from collections import defaultdict
import threading

from core.metadata import TrackMetadata


# Supported audio file extensions
AUDIO_EXTENSIONS = {'.mp3', '.flac', '.ogg', '.m4a', '.aac', '.wav', '.opus', '.mp4'}

# Index file location
INDEX_FILE = Path.home() / '.config' / 'musicplayer' / 'library_index.json'


class MusicLibrary:
    """Manages the music library, scanning and indexing tracks."""
    
    def __init__(self):
        self.tracks: List[TrackMetadata] = []
        self.artists: Dict[str, Dict[str, List[TrackMetadata]]] = defaultdict(lambda: defaultdict(list))
        # Folder structure: path -> List[TrackMetadata]
        self.folder_structure: Dict[str, List[TrackMetadata]] = defaultdict(list)
        self._lock = threading.Lock()
        self._scanning = False
        self._index_file = INDEX_FILE
        self._file_cache: Dict[str, Dict] = {}  # file_path -> {mtime, hash, metadata}
        self._music_root: Optional[Path] = None  # Root music directory
        
        # Ensure config directory exists
        self._index_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing index
        self._load_index()
    
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
        
        # Scan directories incrementally
        tracks = []
        folder_structure = defaultdict(list)
        music_root = None
        
        for music_dir in music_dirs:
            if music_dir.exists() and music_dir.is_dir():
                if music_root is None:
                    music_root = music_dir
                tracks.extend(self._scan_directory(music_dir, folder_structure, music_dir))
        
        with self._lock:
            self.tracks = tracks
            self.folder_structure = folder_structure
            self._music_root = music_root
            self._rebuild_index()
            self._save_index()
    
    def _scan_directory(self, directory: Path, folder_structure: Dict[str, List[TrackMetadata]], music_root: Path) -> List[TrackMetadata]:
        """Recursively scan a directory for audio files."""
        tracks = []
        
        try:
            for root, dirs, files in os.walk(directory):
                root_path = Path(root)
                # Get relative path from music root for folder structure
                try:
                    rel_path = str(root_path.relative_to(music_root))
                except ValueError:
                    # If not relative, use absolute path
                    rel_path = str(root_path)
                
                for file in files:
                    file_path = root_path / file
                    if file_path.suffix.lower() in AUDIO_EXTENSIONS:
                        try:
                            file_str = str(file_path)
                            
                            # Check if file needs to be rescanned
                            if self._needs_rescan(file_str):
                                metadata = TrackMetadata(file_str)
                                tracks.append(metadata)
                                folder_structure[rel_path].append(metadata)
                                # Update cache
                                self._update_cache(file_str, metadata)
                            else:
                                # Load from cache
                                cached_metadata = self._get_cached_metadata(file_str)
                                if cached_metadata:
                                    tracks.append(cached_metadata)
                                    folder_structure[rel_path].append(cached_metadata)
                        except Exception as e:
                            print(f"Error processing {file_path}: {e}")
        except Exception as e:
            print(f"Error scanning directory {directory}: {e}")
        
        return tracks
    
    def _needs_rescan(self, file_path: str) -> bool:
        """Check if a file needs to be rescanned based on modification time."""
        try:
            if not os.path.exists(file_path):
                return False
            
            mtime = os.path.getmtime(file_path)
            
            # If not in cache, needs scan
            if file_path not in self._file_cache:
                return True
            
            # If modification time changed, needs rescan
            cached_mtime = self._file_cache[file_path].get('mtime', 0)
            if mtime != cached_mtime:
                return True
            
            return False
        except OSError:
            return True
    
    def _update_cache(self, file_path: str, metadata: TrackMetadata):
        """Update the cache for a file."""
        try:
            mtime = os.path.getmtime(file_path)
            self._file_cache[file_path] = {
                'mtime': mtime,
                'metadata': metadata.to_dict()
            }
        except OSError:
            pass
    
    def _get_cached_metadata(self, file_path: str) -> Optional[TrackMetadata]:
        """Get metadata from cache."""
        if file_path in self._file_cache:
            try:
                cached_data = self._file_cache[file_path].get('metadata')
                if cached_data:
                    return TrackMetadata.from_dict(cached_data)
            except Exception as e:
                print(f"Error loading cached metadata for {file_path}: {e}")
        return None
    
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
        
        # Sort tracks within folders by filename
        for folder_path in self.folder_structure:
            self.folder_structure[folder_path].sort(key=lambda t: t.file_path)
    
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
    
    def get_folder_structure(self) -> Dict[str, List[TrackMetadata]]:
        """Get the folder structure of the music library."""
        with self._lock:
            return dict(self.folder_structure)
    
    def get_music_root(self) -> Optional[Path]:
        """Get the root music directory."""
        with self._lock:
            return self._music_root
    
    def _save_index(self):
        """Save the library index to disk."""
        try:
            # Prepare data for serialization
            index_data = {
                'version': 1,
                'file_cache': {}
            }
            
            # Convert TrackMetadata objects to dicts for serialization
            for file_path, cache_entry in self._file_cache.items():
                index_data['file_cache'][file_path] = {
                    'mtime': cache_entry.get('mtime', 0),
                    'metadata': cache_entry.get('metadata', {})
                }
            
            # Write to file atomically
            temp_file = self._index_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            temp_file.replace(self._index_file)
            
        except Exception as e:
            print(f"Error saving library index: {e}")
    
    def _load_index(self):
        """Load the library index from disk."""
        try:
            if not self._index_file.exists():
                return
            
            with open(self._index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            # Load file cache
            if 'file_cache' in index_data:
                self._file_cache = index_data['file_cache']
            else:
                self._file_cache = {}
            
            # Rebuild tracks and index from cache
            tracks = []
            files_to_remove = []
            
            for file_path, cache_entry in self._file_cache.items():
                # Verify file still exists
                if not os.path.exists(file_path):
                    files_to_remove.append(file_path)
                    continue
                
                # Check if file was modified
                try:
                    current_mtime = os.path.getmtime(file_path)
                    cached_mtime = cache_entry.get('mtime', 0)
                    
                    # Only use cache if file hasn't changed
                    if current_mtime == cached_mtime:
                        metadata_dict = cache_entry.get('metadata', {})
                        if metadata_dict:
                            try:
                                metadata = TrackMetadata.from_dict(metadata_dict)
                                tracks.append(metadata)
                            except Exception as e:
                                print(f"Error loading cached metadata for {file_path}: {e}")
                                # Mark for rescan
                                cache_entry['mtime'] = 0
                    else:
                        # File changed, will be rescanned - clear old metadata
                        cache_entry['mtime'] = current_mtime
                        cache_entry['metadata'] = {}
                except OSError:
                    # File doesn't exist or can't be accessed, remove from cache
                    files_to_remove.append(file_path)
                    continue
            
            # Remove deleted files from cache
            for file_path in files_to_remove:
                if file_path in self._file_cache:
                    del self._file_cache[file_path]
            
            with self._lock:
                self.tracks = tracks
                self._rebuild_index()
            
        except Exception as e:
            print(f"Error loading library index: {e}")
            # If loading fails, start with empty cache
            self._file_cache = {}

