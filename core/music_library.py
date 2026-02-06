"""Music library scanning and indexing."""

import json
import os
import threading
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

# Try to import watchdog for file system monitoring
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

from core.config import get_config
from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)


# Supported audio file extensions (covers ~90% of common formats)
AUDIO_EXTENSIONS = {
    # Lossy formats
    ".mp3",  # MPEG Audio Layer 3
    ".m4a",
    ".aac",  # Advanced Audio Coding (iTunes/Apple)
    ".ogg",  # OGG Vorbis
    ".opus",  # Opus codec
    ".wma",  # Windows Media Audio
    # Lossless formats
    ".flac",  # Free Lossless Audio Codec
    ".wav",  # Waveform Audio
    ".aiff",
    ".aif",  # Audio Interchange File Format
    ".alac",
    ".m4a",  # Apple Lossless (also uses .m4a)
    ".ape",  # Monkey's Audio
    # Container formats (may contain audio)
    ".mp4",  # MPEG-4 (may contain AAC/ALAC)
    ".mkv",  # Matroska (may contain audio)
    ".webm",  # WebM (may contain Opus/Vorbis)
}


class LibraryWatcher(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """File system watcher for incremental library updates."""

    def __init__(self, library: "MusicLibrary") -> None:
        """
        Initialize library watcher.

        Args:
            library: MusicLibrary instance to notify of changes
        """
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self.library = library

    def on_created(self, event) -> None:
        """
        Handle file creation.

        Args:
            event: File system event from watchdog
        """
        if not event.is_directory and event.src_path:
            self.library._handle_file_change(event.src_path, "created")

    def on_modified(self, event) -> None:
        """
        Handle file modification.

        Args:
            event: File system event from watchdog
        """
        if not event.is_directory and event.src_path:
            self.library._handle_file_change(event.src_path, "modified")

    def on_deleted(self, event) -> None:
        """
        Handle file deletion.

        Args:
            event: File system event from watchdog
        """
        if not event.is_directory and event.src_path:
            self.library._handle_file_change(event.src_path, "deleted")


class MusicLibrary:
    """Manages the music library, scanning and indexing tracks."""

    def __init__(self) -> None:
        """
        Initialize music library manager.

        Sets up file system monitoring, loads existing index, and prepares
        for incremental scanning.
        """
        self.tracks: List[TrackMetadata] = []
        self.artists: Dict[str, Dict[str, List[TrackMetadata]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # Folder structure: path -> List[TrackMetadata]
        self.folder_structure: Dict[str, List[TrackMetadata]] = defaultdict(list)
        self._lock = threading.Lock()
        self._scanning = False

        # Get config
        config = get_config()
        self._index_file = config.library_index_file
        self._file_cache: Dict[str, Dict] = {}  # file_path -> {mtime, hash, metadata}
        self._music_root: Optional[Path] = None  # Root music directory

        # File system watcher for incremental updates
        self._observer: Optional[Observer] = None
        self._watcher: Optional[LibraryWatcher] = None

        # Load existing index
        self._load_index()

        # File system monitoring disabled - method not implemented
        # TODO: Implement _start_watching() and _handle_file_change() if needed
        # if WATCHDOG_AVAILABLE:
        #     self._start_watching()

    def scan_library(self, callback: Optional[Callable[[], None]] = None) -> None:
        """
        Scan music directories asynchronously.

        Args:
            callback: Optional callback to call when scanning completes
        """
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
        config = get_config()
        music_dirs = config.music_directories
        # Fallback to defaults if none configured
        if not music_dirs:
            music_dirs = [
                Path.home() / "Music",
                Path.home() / "Musik",
            ]

        # Scan directories incrementally
        tracks = []
        folder_structure = defaultdict(list)
        music_root = None

        for music_dir in music_dirs:
            if music_dir.exists() and music_dir.is_dir():
                if music_root is None:
                    music_root = music_dir
                tracks.extend(
                    self._scan_directory(music_dir, folder_structure, music_dir)
                )

        with self._lock:
            self.tracks = tracks
            self.folder_structure = folder_structure
            self._music_root = music_root
            self._rebuild_index()
            self._save_index()

    def _scan_directory(
        self,
        directory: Path,
        folder_structure: Dict[str, List[TrackMetadata]],
        music_root: Path,
    ) -> List[TrackMetadata]:
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
                            logger.error(
                                "Error processing %s: %s", file_path, e, exc_info=True
                            )
        except Exception as e:
            logger.error("Error scanning directory %s: %s", directory, e, exc_info=True)

        return tracks

    def _needs_rescan(self, file_path: str) -> bool:
        """Check if a file needs to be rescanned based on modification time."""
        try:
            path = Path(file_path)
            if not path.exists():
                return False

            mtime = path.stat().st_mtime

            # If not in cache, needs scan
            if file_path not in self._file_cache:
                return True

            # If modification time changed, needs rescan
            cached_mtime = self._file_cache[file_path].get("mtime", 0)
            if mtime != cached_mtime:
                return True

            return False
        except OSError:
            return True

    def _update_cache(self, file_path: str, metadata: TrackMetadata):
        """Update the cache for a file."""
        try:
            path = Path(file_path)
            mtime = path.stat().st_mtime
            self._file_cache[file_path] = {
                "mtime": mtime,
                "metadata": metadata.to_dict(),
            }
        except OSError:
            pass

    def _get_cached_metadata(self, file_path: str) -> Optional[TrackMetadata]:
        """Get metadata from cache."""
        if file_path in self._file_cache:
            try:
                cached_data = self._file_cache[file_path].get("metadata")
                if cached_data:
                    return TrackMetadata.from_dict(cached_data)
            except Exception as e:
                logger.error(
                    "Error loading cached metadata for %s: %s",
                    file_path,
                    e,
                    exc_info=True,
                )
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

    def get_tracks(
        self, artist: Optional[str] = None, album: Optional[str] = None
    ) -> List[TrackMetadata]:
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
            index_data = {"version": 1, "file_cache": {}}

            # Convert TrackMetadata objects to dicts for serialization
            for file_path, cache_entry in self._file_cache.items():
                index_data["file_cache"][file_path] = {
                    "mtime": cache_entry.get("mtime", 0),
                    "metadata": cache_entry.get("metadata", {}),
                }

            # Write to file atomically
            temp_file = self._index_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_file.replace(self._index_file)

        except Exception as e:
            logger.error("Error saving library index: %s", e, exc_info=True)

    def _load_index(self):
        """Load the library index from disk."""
        try:
            if not self._index_file.exists():
                return

            with open(self._index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            # Load file cache
            if "file_cache" in index_data:
                self._file_cache = index_data["file_cache"]
            else:
                self._file_cache = {}

            # Rebuild tracks and index from cache
            tracks = []
            files_to_remove = []

            for file_path, cache_entry in self._file_cache.items():
                # Verify file still exists
                path = Path(file_path)
                if not path.exists():
                    files_to_remove.append(file_path)
                    continue

                # Check if file was modified
                try:
                    current_mtime = path.stat().st_mtime
                    cached_mtime = cache_entry.get("mtime", 0)

                    # Only use cache if file hasn't changed
                    if current_mtime == cached_mtime:
                        metadata_dict = cache_entry.get("metadata", {})
                        if metadata_dict:
                            try:
                                metadata = TrackMetadata.from_dict(metadata_dict)
                                tracks.append(metadata)
                            except Exception as e:
                                logger.error(
                                    "Error loading cached metadata for %s: %s",
                                    file_path,
                                    e,
                                    exc_info=True,
                                )
                                # Mark for rescan
                                cache_entry["mtime"] = 0
                    else:
                        # File changed, will be rescanned - clear old metadata
                        cache_entry["mtime"] = current_mtime
                        cache_entry["metadata"] = {}
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
            logger.error("Error loading library index: %s", e, exc_info=True)
            # If loading fails, start with empty cache
            self._file_cache = {}
