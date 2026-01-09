"""Integration with MOC (Music On Console) via the `mocp` CLI.

This module lets us:
- Read the current MOC playlist from ~/.moc/playlist.m3u
- Control playback (play/pause/stop/next/prev)
- Sync volume
- Query current status (state, track, position, duration, volume)
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from __future__ import annotations

import json
import shutil
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
# None

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.config import get_config
from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)


class ServerState(Enum):
    """State machine for MOC server connection."""

    UNAVAILABLE = "unavailable"  # mocp not in PATH
    DISCONNECTED = "disconnected"  # Server not running
    CONNECTING = "connecting"  # Attempting to start server
    CONNECTED = "connected"  # Server is running and available


class CacheState(Enum):
    """State machine for status cache."""

    EMPTY = "empty"  # No cache available
    VALID = "valid"  # Cache is valid and can be used
    STALE = "stale"  # Cache exists but is expired
    ERROR = "error"  # Cache invalidated due to error


class MocController:
    """Minimal wrapper around `mocp` for playlist and playback control."""

    def __init__(self):
        self._mocp_path: Optional[str] = shutil.which("mocp")
        # Get playlist path from config
        config = get_config()
        self._playlist_path: Path = config.moc_playlist_path

        # Explicit state machines (replace boolean flags)
        self._server_state: ServerState = (
            ServerState.UNAVAILABLE if not self._mocp_path else ServerState.DISCONNECTED
        )
        self._cache_state: CacheState = CacheState.EMPTY

        # Status caching to reduce MOC server load
        self._status_cache: Optional[Dict] = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 0.2  # Cache for 200ms to reduce calls

        # Error tracking for backoff
        self._last_error_time: float = 0.0
        self._error_backoff: float = 1.0  # Start with 1 second backoff

    # ------------------------------------------------------------------
    # Availability / helpers
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if `mocp` is available in PATH."""
        return self._mocp_path is not None

    def _run(self, *args: str, capture_output: bool = False) -> subprocess.CompletedProcess:
        """
        Run `mocp` with the given arguments.

        Handles errors gracefully and prevents overwhelming the MOC server.
        Silently handles "server not running" errors to avoid spam.
        """
        if not self._mocp_path:
            # Simulate a failed process
            return subprocess.CompletedProcess(
                args=["mocp", *args], returncode=127, stdout="", stderr="mocp not found"
            )

        cmd = [self._mocp_path, *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                check=False,
                timeout=5.0,  # 5 second timeout to prevent hanging
            )

            # Check for server connection errors and handle gracefully
            if result.returncode != 0 and result.stderr:
                stderr_lower = result.stderr.lower()
                if (
                    "server is not running" in stderr_lower
                    or "can't receive value" in stderr_lower
                    or "can't connect" in stderr_lower
                ):
                    self._server_state = ServerState.DISCONNECTED
                    self._cache_state = CacheState.EMPTY
                    self._status_cache = None
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=125, stdout="", stderr=""
                    )

            # Clear status cache on successful command (except for --info and --server)
            if "--info" not in args and "--server" not in args:
                self._cache_state = CacheState.EMPTY
                self._status_cache = None
            return result
        except subprocess.TimeoutExpired:
            # Timeout - return error result
            return subprocess.CompletedProcess(
                args=cmd, returncode=124, stdout="", stderr="Command timed out"
            )
        except Exception as e:
            # Other errors - return error result
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=str(e))

    def ensure_server(self) -> bool:
        """
        Start the MOC server if it is not already running.

        Uses explicit state machine to track server connection state.
        Avoids redundant connection attempts to prevent overloading.

        Returns:
            True if server is available, False otherwise
        """
        if not self.is_available():
            self._server_state = ServerState.UNAVAILABLE
            return False

        if self._server_state == ServerState.CONNECTED:
            return True
        
        # If we're already trying to connect, wait a bit and check again
        # This prevents multiple simultaneous connection attempts
        if self._server_state == ServerState.CONNECTING:
            time.sleep(0.1)
            # Check if connection succeeded (another thread might have completed it)
            if self._server_state == ServerState.CONNECTED:
                return True
            # Still connecting - return False to avoid overload
            return False

        # Attempt to start server
        self._server_state = ServerState.CONNECTING
        result = self._run("--server", capture_output=True)
        if result.returncode == 0:
            time.sleep(0.2)  # Increased delay to give server time to initialize
            self._server_state = ServerState.CONNECTED
            return True

        self._server_state = ServerState.DISCONNECTED
        return False

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------
    def get_playlist(self, current_file: Optional[str] = None) -> Tuple[List[TrackMetadata], int]:
        """
        Read MOC's current playlist from M3U file and return (tracks, current_index).

        current_index is -1 if there is no active track.

        Args:
            current_file: Optional file path of current track. If not provided,
                         will be fetched from status. Pass this to avoid redundant status call.
        """
        tracks: List[TrackMetadata] = []
        current_index = -1

        # Parse M3U file using the standard parser
        parsed_tracks = self._parse_m3u_playlist()

        # Convert to TrackMetadata objects, using EXTINF metadata if available
        for _, extinf_line, file_path in parsed_tracks:
            # Only include files that actually exist
            if Path(file_path).exists():
                # Create TrackMetadata from file (will extract metadata from file)
                metadata = TrackMetadata(file_path)
                
                # Override with EXTINF metadata if available (preserves title/artist from M3U)
                if extinf_line:
                    extinf_meta = self._extinf_to_metadata(extinf_line)
                    if extinf_meta.get("title"):
                        metadata.title = extinf_meta["title"]
                    if extinf_meta.get("artist"):
                        metadata.artist = extinf_meta["artist"]
                    if extinf_meta.get("duration") is not None:
                        metadata.duration = extinf_meta["duration"]
                
                tracks.append(metadata)

        # Find current track index
        if current_file is None:
            status = self.get_status()
            current_file = status.get("file_path") if status else None

        if current_file:
            # Normalize paths for comparison
            current_file_resolved = str(Path(current_file).resolve())
            for idx, track in enumerate(tracks):
                track_path_resolved = str(Path(track.file_path).resolve())
                if track_path_resolved == current_file_resolved:
                    current_index = idx
                    break

        return tracks, current_index

    # ------------------------------------------------------------------
    # Status / info
    # ------------------------------------------------------------------
    def get_status(self, force_refresh: bool = False) -> Optional[Dict]:
        """
        Get current MOC status (state, file, position, duration, volume).

        Uses explicit state machine for cache management and caching to reduce server load.
        Set force_refresh=True to bypass cache.

        Returns None if status can't be read.
        """
        if not self.is_available():
            self._server_state = ServerState.UNAVAILABLE
            return None

        # Check cache first (unless forced refresh)
        current_time = time.time()
        if (
            not force_refresh
            and self._cache_state == CacheState.VALID
            and self._status_cache is not None
        ):
            if current_time - self._status_cache_time < self._status_cache_ttl:
                return self._status_cache
            else:
                # Cache expired but still exists
                self._cache_state = CacheState.STALE

        # Check if we're in error backoff period
        if current_time - self._last_error_time < self._error_backoff:
            # Return cached status if available, otherwise None
            if (
                self._cache_state in (CacheState.VALID, CacheState.STALE)
                and self._status_cache is not None
            ):
                return self._status_cache
            return None

        if not self.ensure_server():
            self._cache_state = CacheState.EMPTY
            self._status_cache = None
            return None

        result = self._run("--info", capture_output=True)

        # Handle errors with backoff
        if result.returncode != 0 or not result.stdout:
            self._last_error_time = current_time
            self._error_backoff = min(self._error_backoff * 2, 5.0)
            self._cache_state = CacheState.ERROR
            self._status_cache = None
            return None

        # Success - reset backoff
        self._error_backoff = 0.2  # Reset to minimal backoff
        self._last_error_time = 0.0

        info: Dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            info[key.strip()] = value.strip()

        state = info.get("State", "").upper() or "STOP"
        file_path = info.get("File")

        def _parse_float(value: Optional[str]) -> float:
            if not value:
                return 0.0
            try:
                return float(value)
            except ValueError:
                return 0.0

        # MOC outputs position and duration in seconds
        # Try both "CurrentSec" and "CurrentTime" (in case format varies)
        position = _parse_float(info.get("CurrentSec"))
        if position == 0.0:
            # Fallback: try parsing from "CurrentTime" format (MM:SS)
            current_time_str = info.get("CurrentTime", "")
            if current_time_str and ":" in current_time_str:
                try:
                    parts = current_time_str.split(":")
                    if len(parts) == 2:
                        position = float(parts[0]) * 60 + float(parts[1])
                except (ValueError, IndexError):
                    pass

        duration = _parse_float(info.get("TotalSec"))
        if duration == 0.0:
            # Fallback: try parsing from "TotalTime" format (MM:SS)
            total_time_str = info.get("TotalTime", "")
            if total_time_str and ":" in total_time_str:
                try:
                    parts = total_time_str.split(":")
                    if len(parts) == 2:
                        duration = float(parts[0]) * 60 + float(parts[1])
                except (ValueError, IndexError):
                    pass

        # Volume comes as e.g. "75%"
        vol_str = info.get("Volume", "").strip()
        volume = 1.0
        if vol_str.endswith("%"):
            vol_str = vol_str[:-1].strip()
        try:
            vol_percent = int(vol_str)
            volume = max(0.0, min(1.0, vol_percent / 100.0))
        except ValueError:
            pass

        # Parse shuffle and autonext state from info
        shuffle = info.get("Shuffle", "").strip().upper() == "ON"
        autonext = info.get("Autonext", "").strip().upper() == "ON"

        status = {
            "state": state,  # PLAY, PAUSE, STOP
            "file_path": file_path,
            "position": position,
            "duration": duration,
            "volume": volume,
            "shuffle": shuffle,
            "autonext": autonext,
        }

        # Update cache and state
        self._status_cache = status
        self._status_cache_time = current_time
        self._cache_state = CacheState.VALID

        return status

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def play(self):
        """Start / resume playback."""
        if not self.is_available():
            return
        self.ensure_server()
        # Check if MOC is paused - if so, use --unpause to resume from pause position
        # Otherwise use --play to start/resume
        status = self.get_status(force_refresh=False)
        if status and status.get("state", "STOP") == "PAUSE":
            # MOC is paused - use --unpause to resume from pause position
            self._run("--unpause", capture_output=False)
        else:
            # MOC is stopped or in other state - use --play
            self._run("--play", capture_output=False)

    def pause(self):
        """Pause playback."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--pause")

    def stop(self):
        """Stop playback."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--stop")

    def shutdown(self):
        """Completely stop the MOC server (equivalent to `mocp --exit`)."""
        if not self.is_available():
            self._server_state = ServerState.UNAVAILABLE
            return
        # We don't call ensure_server() here on purpose – if the server is not
        # running, there is nothing to shut down.
        self._run("--exit")
        self._server_state = ServerState.DISCONNECTED
        self._cache_state = CacheState.EMPTY
        self._status_cache = None

    def next(self):
        """Skip to next track."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--next")

    def previous(self):
        """Go back to previous track."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--previous")

    def jump_to_index(self, index: int, start_playback: bool = False):
        """
        Jump to a specific track index in MOC's playlist.

        Args:
            index: Index of track to jump to (0-based)
            start_playback: If True, start playback after jumping

        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            return False

        self.ensure_server()
        # MOC uses -j (jump) with index
        # Format: mocp -j <index>
        result = self._run("-j", str(index), capture_output=True)

        if result.returncode == 0:
            if start_playback:
                self.play()
            logger.debug("Jumped to index %d", index)
            return True
        else:
            logger.warning("Failed to jump to index %d", index)
            return False

    def set_volume(self, volume: float):
        """Set volume as a float 0.0–1.0."""
        if not self.is_available():
            return
        self.ensure_server()
        vol_percent = int(max(0.0, min(1.0, volume)) * 100)
        self._run("--volume", str(vol_percent))

    def seek_relative(self, delta_seconds: float):
        """
        Seek relatively by delta in seconds (positive or negative).

        MOC uses `--seek N` for relative seek in seconds.
        """
        if not self.is_available():
            return
        seconds = int(delta_seconds)
        if seconds == 0:
            return
        self.ensure_server()
        self._run("--seek", str(seconds))

    def enable_autonext(self):
        """Enable autonext (autoplay) in MOC."""
        if not self.is_available():
            return
        # Only ensure server if not already connected
        # This avoids redundant calls when server is already running
        if self._server_state != ServerState.CONNECTED:
            if not self.ensure_server():
                return
        self._run("--on=autonext")

    def disable_autonext(self):
        """Disable autonext (autoplay) in MOC."""
        if not self.is_available():
            return
        # Only ensure server if not already connected
        if self._server_state != ServerState.CONNECTED:
            if not self.ensure_server():
                return
        self._run("--off=autonext")

    def enable_shuffle(self):
        """Enable shuffle mode in MOC."""
        if not self.is_available():
            return
        # Only ensure server if not already connected
        if self._server_state != ServerState.CONNECTED:
            if not self.ensure_server():
                return
        self._run("--on=shuffle")

    def disable_shuffle(self):
        """Disable shuffle mode in MOC."""
        if not self.is_available():
            return
        # Only ensure server if not already connected
        if self._server_state != ServerState.CONNECTED:
            if not self.ensure_server():
                return
        self._run("--off=shuffle")

    def get_shuffle_state(self) -> Optional[bool]:
        """Get current shuffle state from MOC. Returns None if unavailable."""
        status = self.get_status()
        if status:
            return status.get("shuffle", False)
        return None

    def get_autonext_state(self) -> Optional[bool]:
        """Get current autonext state from MOC. Returns None if unavailable."""
        status = self.get_status()
        if status:
            return status.get("autonext", False)
        return None

    # ------------------------------------------------------------------
    # Playlist write helpers
    # ------------------------------------------------------------------
    def _parse_m3u_playlist(self) -> List[Tuple[int, Optional[str], str]]:
        """
        Parse M3U playlist file following the standard format.

        M3U format uses pairs:
        - #EXTINF:duration,title (metadata line)
        - /path/to/file (file path line)

        Returns:
            List of tuples: (track_index, extinf_line, file_path)
            - track_index: 0-based index of the track
            - extinf_line: The EXTINF metadata line (without newline), or None if missing
            - file_path: The file path line (without newline)
        """
        tracks = []
        if not self._playlist_path.exists():
            return tracks

        try:
            with self._playlist_path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            i = 0
            track_index = 0
            while i < len(lines):
                line = lines[i].rstrip("\n\r")
                stripped = line.strip()

                # Skip empty lines and header
                if not stripped or stripped == "#EXTM3U":
                    i += 1
                    continue

                # Check if this is an EXTINF line
                if stripped.startswith("#EXTINF:"):
                    extinf_line = stripped
                    # Next line should be the file path
                    if i + 1 < len(lines):
                        file_path = lines[i + 1].rstrip("\n\r").strip()
                        if file_path and not file_path.startswith("#"):
                            tracks.append((track_index, extinf_line, file_path))
                            track_index += 1
                            i += 2  # Skip both EXTINF and file path lines
                            continue

                # If no EXTINF, treat as plain file path
                if not stripped.startswith("#"):
                    tracks.append((track_index, None, stripped))
                    track_index += 1

                i += 1
        except Exception as e:
            logger.error("Error parsing M3U file: %s", e, exc_info=True)

        return tracks

    def _track_to_extinf(self, track: TrackMetadata) -> str:
        """Convert TrackMetadata to EXTINF line.
        
        Format: #EXTINF:duration,title - artist
        """
        duration = int(track.duration) if track.duration and track.duration > 0 else -1
        title = track.title or Path(track.file_path).stem
        artist = track.artist or "Unknown Artist"
        return f"#EXTINF:{duration},{title} - {artist}"
    
    def _extinf_to_metadata(self, extinf_line: str) -> Dict[str, Any]:
        """Parse EXTINF line to extract metadata.
        
        Format: #EXTINF:duration,title - artist
        Returns dict with duration, title, artist (or None if parsing fails)
        """
        try:
            # Remove #EXTINF: prefix
            if not extinf_line.startswith("#EXTINF:"):
                return {}
            content = extinf_line[8:].strip()  # Remove "#EXTINF:"
            
            # Find comma separator
            if "," not in content:
                return {}
            
            duration_str, rest = content.split(",", 1)
            duration = int(duration_str) if duration_str and duration_str != "-1" else None
            
            # Parse "title - artist" format
            title = rest
            artist = None
            if " - " in rest:
                parts = rest.split(" - ", 1)
                title = parts[0].strip()
                artist = parts[1].strip() if len(parts) > 1 else None
            
            result = {}
            if duration is not None:
                result["duration"] = float(duration)
            if title:
                result["title"] = title
            if artist:
                result["artist"] = artist
            return result
        except Exception:
            return {}
    
    def _write_m3u_playlist(self, tracks: List[Tuple[Optional[str], str]]) -> bool:
        """
        Write tracks to M3U playlist file following the standard format.
        Uses atomic write (temp file + replace) to handle file locking gracefully.

        Args:
            tracks: List of tuples (extinf_line, file_path)
                - extinf_line: EXTINF metadata line (with #EXTINF: prefix), or None
                - file_path: File path to write

        Returns:
            True if successful
        """
        try:
            self._playlist_path.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically using temp file (handles file locking gracefully)
            temp_file = self._playlist_path.with_suffix(".m3u.tmp")
            with temp_file.open("w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for extinf_line, file_path in tracks:
                    if extinf_line:
                        f.write(extinf_line + "\n")
                    f.write(file_path + "\n")
            # Atomic replace (works even if file is open in another process)
            temp_file.replace(self._playlist_path)
            return True
        except (OSError, PermissionError) as e:
            logger.warning("Could not write M3U file atomically (may be locked): %s", e)
            # Try direct write as fallback (might work if lock is brief)
            try:
                with self._playlist_path.open("w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for extinf_line, file_path in tracks:
                        if extinf_line:
                            f.write(extinf_line + "\n")
                        f.write(file_path + "\n")
                return True
            except Exception as e2:
                logger.error("Error writing M3U file: %s", e2, exc_info=True)
                return False
        except Exception as e:
            logger.error("Error writing M3U file: %s", e, exc_info=True)
            return False

    def add_track_at_index_m3u(
        self, track_index: int, file_path: str, extinf_line: Optional[str] = None
    ) -> bool:
        """
        Add a track at a specific index in the M3U playlist file.

        Args:
            track_index: Index where to insert (0-based)
            file_path: File path to add
            extinf_line: Optional EXTINF metadata line (with #EXTINF: prefix)

        Returns:
            True if successful
        """
        parsed_tracks = self._parse_m3u_playlist()

        # Convert to (extinf_line, file_path) format
        track_list = [(extinf, path) for _, extinf, path in parsed_tracks]

        # Validate and clamp track_index
        if track_index < 0:
            track_index = 0
        if track_index > len(track_list):
            track_index = len(track_list)

        # Insert new track
        track_list.insert(track_index, (extinf_line, file_path))

        return self._write_m3u_playlist(track_list)

    def remove_track_at_index_m3u(self, track_index: int) -> bool:
        """
        Remove a track at a specific index from the M3U playlist file.

        Args:
            track_index: Index of track to remove (0-based)

        Returns:
            True if successful
        """
        parsed_tracks = self._parse_m3u_playlist()

        if not (0 <= track_index < len(parsed_tracks)):
            return False

        # Convert to (extinf_line, file_path) format and remove
        track_list = [(extinf, path) for _, extinf, path in parsed_tracks]
        track_list.pop(track_index)

        return self._write_m3u_playlist(track_list)

    def move_track_in_m3u(self, from_index: int, to_index: int) -> bool:
        """
        Move a track from one index to another in the M3U playlist file.

        Args:
            from_index: Current index of the track
            to_index: Target index for the track

        Returns:
            True if successful
        """
        if from_index == to_index:
            return True

        parsed_tracks = self._parse_m3u_playlist()

        if not (0 <= from_index < len(parsed_tracks) and 0 <= to_index < len(parsed_tracks)):
            return False

        # Convert to (extinf_line, file_path) format
        track_list = [(extinf, path) for _, extinf, path in parsed_tracks]

        # Move the track
        track = track_list.pop(from_index)
        track_list.insert(to_index, track)

        return self._write_m3u_playlist(track_list)

    def get_playlist_length_m3u(self) -> int:
        """Get the number of tracks in the M3U playlist file."""
        parsed_tracks = self._parse_m3u_playlist()
        return len(parsed_tracks)

    def set_playlist(
        self, tracks: List[TrackMetadata], current_index: int = -1, start_playback: bool = False
    ):
        """
        Replace MOC's playlist with the given tracks by writing directly to M3U file.

        Args:
            tracks: List of tracks to become the new playlist.
            current_index: Index of the track that should start playing (if start_playback is True).
            start_playback: If True and current_index is valid, start playback of that track.
        """
        # Build track list for M3U file (extinf_line, file_path pairs)
        # Generate EXTINF lines to preserve metadata
        track_list = []
        valid_tracks = []
        original_to_valid_index = {}  # Map original index to valid_tracks index

        for orig_idx, track in enumerate(tracks):
            if not track or not track.file_path:
                continue
            # Validate that file exists
            file_path = Path(track.file_path)
            if not file_path.exists() or not file_path.is_file():
                logger.warning("Track file does not exist: %s", track.file_path)
                continue
            # Use absolute path
            abs_path = str(file_path.resolve())
            # Generate EXTINF line from track metadata
            extinf_line = self._track_to_extinf(track)
            track_list.append((extinf_line, abs_path))
            original_to_valid_index[orig_idx] = len(valid_tracks)
            valid_tracks.append(track)

        # Write entire playlist to M3U file (always write, even if server isn't available)
        # This ensures the file is ready when MOC starts
        if not self._write_m3u_playlist(track_list):
            logger.error("Failed to write playlist to M3U file")
            return

        # Optionally start playback from the selected track (only if server is available)
        # Map current_index from original tracks list to valid_tracks list
        valid_index = -1
        if 0 <= current_index < len(tracks):
            valid_index = original_to_valid_index.get(current_index, -1)
        
        if start_playback and self.is_available() and 0 <= valid_index < len(valid_tracks):
            track = valid_tracks[valid_index]
            if track and track.file_path:
                file_path = Path(track.file_path)
                if file_path.exists() and file_path.is_file():
                    abs_path = str(file_path.resolve())
                    
                    # Ensure server is running - only call once here
                    # get_status() will also check, but it's optimized to avoid redundant calls
                    if not self.ensure_server():
                        logger.warning("MOC server is not available, cannot start playback")
                        return
                    
                    # Small delay after ensuring server to let it stabilize
                    time.sleep(0.1)
                    
                    # Check if MOC is already paused on this track - if so, just resume instead of restarting
                    # get_status() will call ensure_server() but it's already connected, so it returns immediately
                    status = self.get_status(force_refresh=False)
                    if status:
                        moc_state = status.get("state", "STOP")
                        moc_file = status.get("file_path")
                        if moc_state == "PAUSE" and moc_file:
                            moc_file_abs = str(Path(moc_file).resolve())
                            if moc_file_abs == abs_path:
                                # MOC is already paused on this track - just resume, don't restart
                                logger.debug(
                                    "MOC is paused on target track - using --unpause to resume instead of restarting"
                                )
                                self._run("--unpause", capture_output=False)
                                return

                    # Use --playit to play the specific file (works even if it's in playlist)
                    # This will restart from the beginning
                    result = self._run("--playit", abs_path, capture_output=True)
                    if result.returncode != 0:
                        # Check if it's a server connection error
                        if result.stderr and "can't connect" in result.stderr.lower():
                            logger.error("MOC server connection failed: %s", result.stderr)
                            return
                        # Fallback: use jump with mapped valid_index
                        if valid_index >= 0:
                            time.sleep(0.1)  # Small delay before fallback
                            self._run("-j", str(valid_index), capture_output=False)
                            self._run("-p", capture_output=False)

    def play_file(self, file_path: str):
        """Play a specific file via MOC, keeping the playlist intact."""
        if not self.is_available():
            return
        if not file_path:
            logger.error("Cannot play file - file path is empty")
            return

        # Validate file exists
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.error("Cannot play file - file does not exist: %s", file_path)
            return

        self.ensure_server()
        abs_path = str(path.resolve())
        result = self._run("--playit", abs_path, capture_output=True)
        if result.returncode != 0:
            logger.error("Failed to play file: %s", abs_path)
            if result.stderr:
                logger.debug("MOC error: %s", result.stderr)
