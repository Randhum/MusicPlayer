"""Metadata extraction for audio files using mutagen."""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from mutagen import File
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4


class TrackMetadata:
    """Represents metadata for a single audio track."""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.title: Optional[str] = None
        self.artist: Optional[str] = None
        self.album: Optional[str] = None
        self.album_artist: Optional[str] = None
        self.track_number: Optional[int] = None
        self.duration: Optional[float] = None
        self.album_art_path: Optional[str] = None
        self.genre: Optional[str] = None
        self.year: Optional[str] = None
        
        self._extract_metadata()
    
    def _extract_metadata(self):
        """Extract metadata from the audio file."""
        try:
            audio_file = File(self.file_path)
            if audio_file is None:
                return
            
            # Extract basic metadata
            self.title = self._get_tag(audio_file, ['TIT2', 'TITLE', '\xa9nam'])
            self.artist = self._get_tag(audio_file, ['TPE1', 'ARTIST', '\xa9ART'])
            self.album = self._get_tag(audio_file, ['TALB', 'ALBUM', '\xa9alb'])
            self.album_artist = self._get_tag(audio_file, ['TPE2', 'ALBUMARTIST', 'aART'])
            self.genre = self._get_tag(audio_file, ['TCON', 'GENRE', '\xa9gen'])
            self.year = self._get_tag(audio_file, ['TDRC', 'DATE', '\xa9day'])
            
            # Extract track number
            track_num = self._get_tag(audio_file, ['TRCK', 'TRACKNUMBER', 'trkn'])
            if track_num:
                try:
                    # Handle formats like "1/10" or just "1"
                    if isinstance(track_num, list):
                        track_num = track_num[0]
                    if isinstance(track_num, tuple):
                        track_num = track_num[0]
                    self.track_number = int(str(track_num).split('/')[0])
                except (ValueError, AttributeError):
                    pass
            
            # Extract duration
            if hasattr(audio_file, 'info') and hasattr(audio_file.info, 'length'):
                self.duration = audio_file.info.length
            
            # Extract album art
            self.album_art_path = self._extract_album_art(audio_file)
            
            # Fallback to filename if no title
            if not self.title:
                self.title = Path(self.file_path).stem
            
        except Exception as e:
            print(f"Error extracting metadata from {self.file_path}: {e}")
    
    def _get_tag(self, audio_file, tag_keys: list) -> Optional[str]:
        """Get a tag value trying multiple possible keys."""
        for key in tag_keys:
            try:
                value = audio_file.get(key)
                if value is None:
                    continue
                
                # Handle different tag formats
                if isinstance(value, list):
                    value = value[0]
                if isinstance(value, tuple):
                    value = value[0]
                if isinstance(value, bytes):
                    value = value.decode('utf-8', errors='ignore')
                
                return str(value).strip() if value else None
            except (KeyError, AttributeError, TypeError):
                continue
        return None
    
    def _extract_album_art(self, audio_file) -> Optional[str]:
        """Extract album art from the audio file."""
        try:
            # Try different tag formats for album art
            art_keys = [
                'APIC:',  # MP3
                'covr',   # MP4
                'METADATA_BLOCK_PICTURE',  # FLAC
                'PICTURE',  # FLAC alternative
            ]
            
            for key in art_keys:
                try:
                    if key in audio_file:
                        art_data = audio_file[key]
                        if isinstance(art_data, list):
                            art_data = art_data[0]
                        
                        # Save to temporary file
                        if isinstance(art_data, bytes):
                            art_path = self._save_album_art(art_data)
                            if art_path:
                                return art_path
                        elif hasattr(art_data, 'data'):
                            art_path = self._save_album_art(art_data.data)
                            if art_path:
                                return art_path
                except (KeyError, AttributeError, TypeError):
                    continue
        except Exception as e:
            print(f"Error extracting album art: {e}")
        
        return None
    
    def _save_album_art(self, art_data: bytes) -> Optional[str]:
        """Save album art to a temporary file."""
        try:
            # Create cache directory
            cache_dir = Path.home() / '.cache' / 'musicplayer' / 'art'
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename from track path hash
            import hashlib
            track_hash = hashlib.md5(self.file_path.encode()).hexdigest()
            art_path = cache_dir / f"{track_hash}.jpg"
            
            # Save if not exists
            if not art_path.exists():
                with open(art_path, 'wb') as f:
                    f.write(art_data)
            
            return str(art_path)
        except Exception as e:
            print(f"Error saving album art: {e}")
            return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            'file_path': self.file_path,
            'title': self.title,
            'artist': self.artist,
            'album': self.album,
            'album_artist': self.album_artist,
            'track_number': self.track_number,
            'duration': self.duration,
            'album_art_path': self.album_art_path,
            'genre': self.genre,
            'year': self.year,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrackMetadata':
        """Create TrackMetadata from dictionary."""
        metadata = cls.__new__(cls)
        for key, value in data.items():
            setattr(metadata, key, value)
        return metadata


def get_metadata(file_path: str) -> TrackMetadata:
    """Convenience function to get metadata for a file."""
    return TrackMetadata(file_path)

