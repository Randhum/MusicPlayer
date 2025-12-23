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
        """Extract metadata from the audio file using a generic approach."""
        try:
            audio_file = File(self.file_path)
            if audio_file is None:
                return
            
            # Determine file type for format-specific handling
            file_type = type(audio_file).__name__
            is_flac = isinstance(audio_file, FLAC)
            is_mp3 = isinstance(audio_file, MP3)
            is_mp4 = isinstance(audio_file, MP4)
            is_ogg = isinstance(audio_file, OggVorbis)
            
            # Extract basic metadata using format-agnostic approach
            # Try all common tag names for each field across all formats
            self.title = self._get_tag_generic(audio_file, [
                'TITLE',      # FLAC, OGG (Vorbis)
                'TIT2',       # MP3 (ID3v2)
                '\xa9nam',    # MP4 (iTunes)
                'TIT1',       # MP3 (ID3v1 title)
            ])
            
            self.artist = self._get_tag_generic(audio_file, [
                'ARTIST',     # FLAC, OGG (Vorbis)
                'TPE1',       # MP3 (ID3v2)
                '\xa9ART',    # MP4 (iTunes)
                'TP1',        # MP3 (ID3v1 artist)
            ])
            
            self.album = self._get_tag_generic(audio_file, [
                'ALBUM',      # FLAC, OGG (Vorbis)
                'TALB',       # MP3 (ID3v2)
                '\xa9alb',    # MP4 (iTunes)
                'TAL',        # MP3 (ID3v1 album)
            ])
            
            self.album_artist = self._get_tag_generic(audio_file, [
                'ALBUMARTIST',    # FLAC, OGG (Vorbis)
                'ALBUM ARTIST',   # FLAC, OGG (alternative)
                'TPE2',           # MP3 (ID3v2)
                'aART',           # MP4 (iTunes)
            ])
            
            self.genre = self._get_tag_generic(audio_file, [
                'GENRE',      # FLAC, OGG (Vorbis)
                'TCON',       # MP3 (ID3v2)
                '\xa9gen',    # MP4 (iTunes)
                'TCO',        # MP3 (ID3v1 genre)
            ])
            
            self.year = self._get_tag_generic(audio_file, [
                'DATE',       # FLAC, OGG (Vorbis)
                'YEAR',       # Alternative
                'TDRC',       # MP3 (ID3v2 date)
                'TDRL',       # MP3 (ID3v2 release date)
                'TDOR',       # MP3 (ID3v2 original release date)
                '\xa9day',    # MP4 (iTunes)
                'TYE',        # MP3 (ID3v1 year)
            ])
            
            # Extract track number
            track_num = self._get_tag_generic(audio_file, [
                'TRACKNUMBER',  # FLAC, OGG (Vorbis)
                'TRACK',        # Alternative
                'TRCK',         # MP3 (ID3v2)
                'trkn',         # MP4 (iTunes - tuple format)
                'TRK',          # MP3 (ID3v1 track)
            ])
            
            if track_num:
                try:
                    # Handle different formats
                    # MP4 uses tuples like (track_number, total_tracks)
                    if isinstance(track_num, tuple):
                        track_num = track_num[0]
                    # Most formats use lists
                    if isinstance(track_num, list):
                        track_num = track_num[0]
                    # Convert to string and extract number (handle "1/10" format)
                    track_str = str(track_num).split('/')[0].strip()
                    self.track_number = int(track_str)
                except (ValueError, AttributeError, TypeError):
                    pass
            
            # Extract duration
            if hasattr(audio_file, 'info') and hasattr(audio_file.info, 'length'):
                self.duration = audio_file.info.length
            
            # Extract album art
            self.album_art_path = self._extract_album_art(audio_file)
            
        except Exception as e:
            print(f"Error extracting metadata from {self.file_path}: {e}")
        finally:
            # Always ensure we at least have a sensible title, even if Mutagen
            # failed to parse tags for this file.
            if not self.title:
                self.title = Path(self.file_path).stem
    
    def _get_tag_generic(self, audio_file, tag_keys: list) -> Optional[str]:
        """Get a tag value trying multiple possible keys - works for all formats."""
        for key in tag_keys:
            try:
                value = None
                
                # Try different access methods based on file type
                # FLAC and OGG use Vorbis comments accessed via tags attribute
                if isinstance(audio_file, (FLAC, OggVorbis)):
                    # Access via tags dictionary
                    if hasattr(audio_file, 'tags') and audio_file.tags is not None:
                        if key in audio_file.tags:
                            value = audio_file.tags[key]
                # MP3 uses ID3 tags - can access directly or via tags
                elif isinstance(audio_file, MP3):
                    # Try direct access first
                    try:
                        if key in audio_file:
                            value = audio_file[key]
                    except (KeyError, TypeError):
                        # Try via tags attribute
                        if hasattr(audio_file, 'tags') and audio_file.tags is not None:
                            if key in audio_file.tags:
                                value = audio_file.tags[key]
                # MP4 uses a different structure
                elif isinstance(audio_file, MP4):
                    # MP4 tags are accessed directly
                    if key in audio_file:
                        value = audio_file[key]
                else:
                    # Generic fallback: try direct access, then tags attribute
                    try:
                        if key in audio_file:
                            value = audio_file[key]
                    except (KeyError, TypeError):
                        if hasattr(audio_file, 'tags') and audio_file.tags is not None:
                            if key in audio_file.tags:
                                value = audio_file.tags[key]
                
                if value is None:
                    continue
                
                # Handle different tag formats
                # Most formats return lists
                if isinstance(value, list):
                    if len(value) > 0:
                        value = value[0]
                    else:
                        continue
                # MP4 sometimes returns tuples
                if isinstance(value, tuple):
                    if len(value) > 0:
                        value = value[0]
                    else:
                        continue
                # Some formats return bytes
                if isinstance(value, bytes):
                    value = value.decode('utf-8', errors='ignore')
                
                # Convert to string and clean up
                result = str(value).strip()
                if result:
                    return result
                    
            except (KeyError, AttributeError, TypeError, IndexError):
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

