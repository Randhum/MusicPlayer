"""Metadata extraction for audio files using mutagen and GStreamer."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import base64
import hashlib
import struct
from pathlib import Path
from typing import Any, Dict, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
from mutagen import File
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

# GStreamer for video/MP4 metadata extraction
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstPbutils", "1.0")
from gi.repository import Gst, GstPbutils

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.config import get_config
from core.logging import get_logger

logger = get_logger(__name__)

# Video file extensions that should use GStreamer for metadata
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".wmv", ".flv"}


class TrackMetadata:
    """Represents metadata for a single audio track."""

    def __init__(self, file_path: str) -> None:
        """
        Initialize track metadata from a file.

        Args:
            file_path: Path to the audio file
        """
        self.file_path: str = file_path
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

    def _extract_metadata(self) -> None:
        """
        Extract metadata from the audio file using a generic approach.

        Supports multiple audio formats (MP3, FLAC, MP4, OGG) and extracts
        common metadata fields including title, artist, album, track number,
        duration, and album art.

        For video files (MP4, MKV, etc.), uses GStreamer discoverer which
        handles video containers more reliably than mutagen.
        """
        # Check if this is a video file - use GStreamer for these
        file_ext = Path(self.file_path).suffix.lower()
        if file_ext in VIDEO_EXTENSIONS:
            if self._extract_metadata_gstreamer():
                return  # GStreamer succeeded
            # Fall through to try mutagen as backup

        try:
            audio_file = File(self.file_path)
            if audio_file is None:
                # mutagen couldn't identify the file, try GStreamer
                if self._extract_metadata_gstreamer():
                    return
                return

            # Format-specific handling
            is_flac = isinstance(audio_file, FLAC)
            is_mp3 = isinstance(audio_file, MP3)
            is_mp4 = isinstance(audio_file, MP4)
            is_ogg = isinstance(audio_file, OggVorbis)

            # Extract basic metadata using format-agnostic approach
            # Try all common tag names for each field across all formats
            self.title = self._get_tag_generic(
                audio_file,
                [
                    "TITLE",  # FLAC, OGG (Vorbis)
                    "TIT2",  # MP3 (ID3v2)
                    "\xa9nam",  # MP4 (iTunes)
                    "TIT1",  # MP3 (ID3v1 title)
                ],
            )

            self.artist = self._get_tag_generic(
                audio_file,
                [
                    "ARTIST",  # FLAC, OGG (Vorbis)
                    "TPE1",  # MP3 (ID3v2)
                    "\xa9ART",  # MP4 (iTunes)
                    "TP1",  # MP3 (ID3v1 artist)
                ],
            )

            self.album = self._get_tag_generic(
                audio_file,
                [
                    "ALBUM",  # FLAC, OGG (Vorbis)
                    "TALB",  # MP3 (ID3v2)
                    "\xa9alb",  # MP4 (iTunes)
                    "TAL",  # MP3 (ID3v1 album)
                ],
            )

            self.album_artist = self._get_tag_generic(
                audio_file,
                [
                    "ALBUMARTIST",  # FLAC, OGG (Vorbis)
                    "ALBUM ARTIST",  # FLAC, OGG (alternative)
                    "TPE2",  # MP3 (ID3v2)
                    "aART",  # MP4 (iTunes)
                ],
            )

            self.genre = self._get_tag_generic(
                audio_file,
                [
                    "GENRE",  # FLAC, OGG (Vorbis)
                    "TCON",  # MP3 (ID3v2)
                    "\xa9gen",  # MP4 (iTunes)
                    "TCO",  # MP3 (ID3v1 genre)
                ],
            )

            self.year = self._get_tag_generic(
                audio_file,
                [
                    "DATE",  # FLAC, OGG (Vorbis)
                    "YEAR",  # Alternative
                    "TDRC",  # MP3 (ID3v2 date)
                    "TDRL",  # MP3 (ID3v2 release date)
                    "TDOR",  # MP3 (ID3v2 original release date)
                    "\xa9day",  # MP4 (iTunes)
                    "TYE",  # MP3 (ID3v1 year)
                ],
            )

            # Extract track number
            track_num = self._get_tag_generic(
                audio_file,
                [
                    "TRACKNUMBER",  # FLAC, OGG (Vorbis)
                    "TRACK",  # Alternative
                    "TRCK",  # MP3 (ID3v2)
                    "trkn",  # MP4 (iTunes - tuple format)
                    "TRK",  # MP3 (ID3v1 track)
                ],
            )

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
                    track_str = str(track_num).split("/")[0].strip()
                    self.track_number = int(track_str)
                except (ValueError, AttributeError, TypeError):
                    pass

            # Extract duration
            if hasattr(audio_file, "info") and hasattr(audio_file.info, "length"):
                self.duration = audio_file.info.length

            # Extract album art
            self.album_art_path = self._extract_album_art(audio_file)

        except Exception as e:
            logger.debug(
                "Mutagen failed for %s: %s, trying GStreamer", self.file_path, e
            )
            # Try GStreamer as fallback
            if not self._extract_metadata_gstreamer():
                logger.warning("Could not extract metadata from %s", self.file_path)
        finally:
            # Always ensure we at least have a sensible title, even if extraction
            # failed to parse tags for this file.
            if not self.title:
                self.title = Path(self.file_path).stem

    def _extract_metadata_gstreamer(self) -> bool:
        """
        Extract metadata using GStreamer discoverer.

        This is more reliable for video containers (MP4, MKV, etc.) that
        mutagen sometimes fails to parse correctly.

        Returns:
            True if metadata was successfully extracted, False otherwise
        """
        try:
            # Create a discoverer with 5 second timeout
            discoverer = GstPbutils.Discoverer.new(5 * Gst.SECOND)

            # Convert file path to URI
            file_path = Path(self.file_path).resolve()
            uri = file_path.as_uri()

            # Discover the file
            info = discoverer.discover_uri(uri)

            if info is None:
                return False

            # Extract duration (in nanoseconds, convert to seconds)
            duration_ns = info.get_duration()
            if duration_ns > 0:
                self.duration = duration_ns / Gst.SECOND

            # Get tags
            tags = info.get_tags()
            if tags is None:
                # No tags but we got duration - partial success
                return self.duration is not None

            # Extract common metadata from GStreamer tags
            # Title
            success, title = tags.get_string("title")
            if success and title:
                self.title = title

            # Artist
            success, artist = tags.get_string("artist")
            if success and artist:
                self.artist = artist

            # Album
            success, album = tags.get_string("album")
            if success and album:
                self.album = album

            # Album artist
            success, album_artist = tags.get_string("album-artist")
            if success and album_artist:
                self.album_artist = album_artist

            # Genre
            success, genre = tags.get_string("genre")
            if success and genre:
                self.genre = genre

            # Track number
            success, track_num = tags.get_uint("track-number")
            if success and track_num > 0:
                self.track_number = track_num

            # Year/Date - try multiple tag names
            for date_tag in ["date-time", "date"]:
                success, date_val = tags.get_date_time(date_tag)
                if success and date_val:
                    self.year = str(date_val.get_year())
                    break

            # Try to extract album art (image tag)
            sample = tags.get_sample("image")
            if sample:
                buffer = sample[1].get_buffer()
                if buffer:
                    success, map_info = buffer.map(Gst.MapFlags.READ)
                    if success:
                        try:
                            art_path = self._save_album_art(map_info.data)
                            if art_path:
                                self.album_art_path = art_path
                        finally:
                            buffer.unmap(map_info)

            logger.debug("GStreamer extracted metadata for %s", self.file_path)
            return True

        except Exception as e:
            logger.debug(
                "GStreamer metadata extraction failed for %s: %s", self.file_path, e
            )
            return False

    def _get_tag_generic(self, audio_file: File, tag_keys: list[str]) -> Optional[str]:
        """
        Get a tag value trying multiple possible keys - works for all formats.

        This method tries different access patterns to extract tag values gracefully,
        handling format-specific quirks and errors.

        Args:
            audio_file: Mutagen File object
            tag_keys: List of possible tag key names to try

        Returns:
            Tag value as string, or None if not found
        """
        for key in tag_keys:
            value = self._try_get_tag_value(audio_file, key)
            if value is not None:
                # Normalize the value to a string
                normalized = self._normalize_tag_value(value)
                if normalized:
                    return normalized
        return None

    def _try_get_tag_value(self, audio_file: File, key: str) -> Optional[Any]:
        """
        Try to get a tag value using various access methods.

        Tries multiple access patterns in order:
        1. Direct access (audio_file[key])
        2. Tags attribute access (audio_file.tags[key])

        Handles format-specific errors gracefully.

        Args:
            audio_file: Mutagen File object
            key: Tag key to retrieve

        Returns:
            Tag value (may be list, tuple, bytes, or string), or None if not found
        """
        # Method 1: Try direct access (works for MP3, MP4, and some formats)
        try:
            if key in audio_file:
                return audio_file[key]
        except (KeyError, TypeError, ValueError):
            # KeyError: key doesn't exist (expected)
            # TypeError: object doesn't support 'in' operator
            # ValueError: some formats raise this for invalid keys
            pass

        # Method 2: Try via tags attribute (works for FLAC, OGG, and some MP3)
        if hasattr(audio_file, "tags") and audio_file.tags is not None:
            try:
                # For Vorbis tags (FLAC/OGG), checking 'key in tags' can raise ValueError
                # for invalid keys, so we need special handling
                if isinstance(audio_file, (FLAC, OggVorbis)):
                    try:
                        if key in audio_file.tags:
                            return audio_file.tags[key]
                    except ValueError:
                        # Invalid key for Vorbis tags - return None
                        return None
                else:
                    # For other formats, safe to check normally
                    if key in audio_file.tags:
                        return audio_file.tags[key]
            except (KeyError, TypeError, AttributeError, ValueError):
                # Various errors that can occur when accessing tags
                pass

        return None

    def _normalize_tag_value(self, value: Any) -> Optional[str]:
        """
        Normalize a tag value to a string, handling different formats.

        Handles:
        - Lists (take first element)
        - Tuples (take first element)
        - Bytes (decode to string)
        - Strings (return as-is after stripping)

        Args:
            value: Raw tag value from mutagen

        Returns:
            Normalized string value, or None if value is empty/invalid
        """
        if value is None:
            return None

        # Handle lists (most common format)
        if isinstance(value, list):
            if len(value) == 0:
                return None
            value = value[0]

        # Handle tuples (MP4 sometimes uses these)
        if isinstance(value, tuple):
            if len(value) == 0:
                return None
            value = value[0]

        # Handle bytes (decode to string)
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")

        # Convert to string and clean up
        result = str(value).strip()
        return result if result else None

    def _extract_album_art(self, audio_file: File) -> Optional[str]:
        """
        Extract album art from the audio file.

        Args:
            audio_file: Mutagen File object

        Returns:
            Path to saved album art file, or None if not found
        """
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
                # This handles cases where the pictures property might not work
                try:
                    if "METADATA_BLOCK_PICTURE" in audio_file:
                        picture_data = audio_file["METADATA_BLOCK_PICTURE"][0]
                        # Decode base64
                        decoded = base64.b64decode(picture_data)

                        # Parse FLAC picture block header
                        # Format: picture type (4), MIME length (4), MIME, description length (4), description,
                        # width (4), height (4), depth (4), colors (4), data length (4), data
                        if len(decoded) >= 32:
                            offset = 0
                            # Skip picture type (4 bytes)
                            offset += 4
                            # Read MIME length (4 bytes, big-endian)
                            mime_len = struct.unpack(
                                ">I", decoded[offset : offset + 4]
                            )[0]
                            offset += 4
                            # Skip MIME string
                            offset += mime_len
                            # Read description length (4 bytes, big-endian)
                            desc_len = struct.unpack(
                                ">I", decoded[offset : offset + 4]
                            )[0]
                            offset += 4
                            # Skip description
                            offset += desc_len
                            # Skip width, height, depth, colors (16 bytes total)
                            offset += 16
                            # Read data length (4 bytes, big-endian)
                            data_len = struct.unpack(
                                ">I", decoded[offset : offset + 4]
                            )[0]
                            offset += 4

                            # Extract image data
                            if offset + data_len <= len(decoded):
                                image_data = decoded[offset : offset + data_len]
                                art_path = self._save_album_art(image_data)
                                if art_path:
                                    return art_path
                except (KeyError, ValueError, TypeError, struct.error, IndexError):
                    # If parsing fails, continue to try other formats
                    pass

            # Try different tag formats for album art (MP3, MP4, etc.)
            art_keys = [
                "APIC:",  # MP3
                "covr",  # MP4
                "PICTURE",  # OGG
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
                        elif hasattr(art_data, "data"):
                            art_path = self._save_album_art(art_data.data)
                            if art_path:
                                return art_path
                except (KeyError, AttributeError, TypeError):
                    continue
        except Exception as e:
            logger.error("Error extracting album art: %s", e, exc_info=True)

        return None

    def _save_album_art(self, art_data: bytes) -> Optional[str]:
        """
        Save album art to a cache file.

        Args:
            art_data: Raw image data bytes

        Returns:
            Path to saved album art file, or None on error
        """
        try:
            # Get cache directory from config
            config = get_config()
            cache_dir = config.album_art_cache_dir

            # Generate filename from track path hash
            track_hash = hashlib.md5(self.file_path.encode()).hexdigest()
            art_path = cache_dir / f"{track_hash}.jpg"

            # Save if not exists
            if not art_path.exists():
                with open(art_path, "wb") as f:
                    f.write(art_data)

            return str(art_path)
        except Exception as e:
            logger.error("Error saving album art: %s", e, exc_info=True)
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "file_path": self.file_path,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "album_artist": self.album_artist,
            "track_number": self.track_number,
            "duration": self.duration,
            "album_art_path": self.album_art_path,
            "genre": self.genre,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackMetadata":
        """Create TrackMetadata from dictionary."""
        metadata = cls.__new__(cls)
        for key, value in data.items():
            setattr(metadata, key, value)
        return metadata


def get_metadata(file_path: str) -> TrackMetadata:
    """Convenience function to get metadata for a file."""
    return TrackMetadata(file_path)
