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
            
            # Check if it's a FLAC file for special handling
            is_flac = isinstance(audio_file, FLAC)
            
            # Extract basic metadata
            # FLAC uses Vorbis comments: TITLE, ARTIST, ALBUM, ALBUMARTIST, GENRE, DATE
            # MP3 uses ID3: TIT2, TPE1, TALB, TPE2, TCON, TDRC
            # MP4 uses: \xa9nam, \xa9ART, \xa9alb, aART, \xa9gen, \xa9day
            if is_flac:
                # FLAC-specific tag names (Vorbis comments)
                self.title = self._get_tag(audio_file, ['TITLE', 'TIT2', '\xa9nam'])
                self.artist = self._get_tag(audio_file, ['ARTIST', 'TPE1', '\xa9ART'])
                self.album = self._get_tag(audio_file, ['ALBUM', 'TALB', '\xa9alb'])
                self.album_artist = self._get_tag(audio_file, ['ALBUMARTIST', 'ALBUM ARTIST', 'TPE2', 'aART'])
                self.genre = self._get_tag(audio_file, ['GENRE', 'TCON', '\xa9gen'])
                self.year = self._get_tag(audio_file, ['DATE', 'YEAR', 'TDRC', '\xa9day'])
            else:
                # Standard tag names for other formats
                self.title = self._get_tag(audio_file, ['TIT2', 'TITLE', '\xa9nam'])
                self.artist = self._get_tag(audio_file, ['TPE1', 'ARTIST', '\xa9ART'])
                self.album = self._get_tag(audio_file, ['TALB', 'ALBUM', '\xa9alb'])
                self.album_artist = self._get_tag(audio_file, ['TPE2', 'ALBUMARTIST', 'ALBUM ARTIST', 'aART'])
                self.genre = self._get_tag(audio_file, ['TCON', 'GENRE', '\xa9gen'])
                self.year = self._get_tag(audio_file, ['TDRC', 'DATE', 'YEAR', '\xa9day'])
            
            # Extract track number
            if is_flac:
                track_num = self._get_tag(audio_file, ['TRACKNUMBER', 'TRACK', 'TRCK', 'trkn'])
            else:
                track_num = self._get_tag(audio_file, ['TRCK', 'TRACKNUMBER', 'TRACK', 'trkn'])
            
            if track_num:
                try:
                    # Handle formats like "1/10" or just "1"
                    if isinstance(track_num, list):
                        track_num = track_num[0]
                    if isinstance(track_num, tuple):
                        track_num = track_num[0]
                    # FLAC track numbers are often just strings like "1" or "01"
                    track_str = str(track_num).split('/')[0].strip()
                    self.track_number = int(track_str)
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
            is_flac = isinstance(audio_file, FLAC)
            
            if is_flac:
                # FLAC uses METADATA_BLOCK_PICTURE which is a list of Picture objects
                try:
                    pictures = audio_file.pictures
                    if pictures:
                        # Get the first picture (usually the cover)
                        picture = pictures[0]
                        if picture.data:
                            art_path = self._save_album_art(picture.data)
                            if art_path:
                                return art_path
                except (AttributeError, IndexError, TypeError):
                    pass
                
                # Fallback: try METADATA_BLOCK_PICTURE tag directly
                try:
                    if 'METADATA_BLOCK_PICTURE' in audio_file:
                        import base64
                        import struct
                        picture_data = audio_file['METADATA_BLOCK_PICTURE'][0]
                        # Decode base64
                        decoded = base64.b64decode(picture_data)
                        # Skip FLAC picture block header (32 bytes)
                        # Format: picture type (4), MIME length (4), MIME, description length (4), description, 
                        # width (4), height (4), depth (4), colors (4), data length (4), data
                        if len(decoded) > 32:
                            # Find data start (skip header)
                            offset = 32
                            # Actually, let's use mutagen's built-in handling
                            # The pictures property should work
                            pass
                except (KeyError, ValueError, TypeError):
                    pass
            
            # Try different tag formats for album art (MP3, MP4, etc.)
            art_keys = [
                'APIC:',  # MP3
                'covr',   # MP4
                'PICTURE',  # OGG
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

