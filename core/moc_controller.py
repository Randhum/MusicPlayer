"""MOC (Music On Console) integration via mocp CLI."""

from __future__ import annotations
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from core.config import get_config
from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)

class MocController:
    def __init__(self):
        self._mocp_path: Optional[str] = shutil.which("mocp")
        self._playlist_path: Path = get_config().moc_playlist_path
        self._server_available: bool = False
        self._status_cache: Optional[Dict] = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 0.4
        self._last_error_time: float = 0.0
        self._error_backoff: float = 1.0

    def is_available(self) -> bool:
        return self._server_available is not None

    def _run(self, *args: str, capture_output: bool = False) -> subprocess.CompletedProcess:
        if not self._mocp_path:
            return subprocess.CompletedProcess(args=["mocp", *args], returncode=127, stdout="", stderr="mocp not found")

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
            # Use ensure_server to verify and potentially restart the server
            if result.returncode != 0 and result.stderr:
                stderr_lower = result.stderr.lower()
                # Check for server connection errors (be specific to avoid false positives)
                server_errors = [
                    "server is not running",
                    "can't receive value",
                    "can't connect",
                    "connection refused",
                ]
                if any(err in stderr_lower for err in server_errors):
                    # Only handle if this isn't a --server or --info command
                    # (--server is handled in ensure_server, --info is used for verification)
                    if "--server" not in args and "--info" not in args:
                        # Try to ensure server is running
                        success, _ = self.ensure_server()
                        if not success:
                            # Server still not available after ensure_server attempt
                            self._server_available = False
                            self._status_cache = None
                            return subprocess.CompletedProcess(args=cmd, returncode=125, stdout="", stderr="")
                        # Server was restarted - retry the command once
                        retry_result = subprocess.run(
                            cmd,
                            capture_output=capture_output,
                            text=True,
                            check=False,
                            timeout=5.0,
                        )
                        if retry_result.returncode == 0:
                            # Retry succeeded - update server_available
                            self._server_available = True
                            # Clear status cache on successful command
                            self._status_cache = None
                            self._status_cache_time = 0.0
                            return retry_result
                        # Retry also failed
                        self._server_available = False
                        self._status_cache = None
                        return subprocess.CompletedProcess(args=cmd, returncode=125, stdout="", stderr="")
            
            # Command succeeded - update server_available flag
            if result.returncode == 0:
                self._server_available = True
            
            # Clear status cache on successful command (except for --info and --server)
            # This ensures UI reflects changes immediately after control commands
            if result.returncode == 0 and "--info" not in args and "--server" not in args:
                self._status_cache = None
                # Also reset cache time to force refresh on next get_status() call
                self._status_cache_time = 0.0
            return result
        except subprocess.TimeoutExpired:
            # Timeout - return error result
            return subprocess.CompletedProcess(args=cmd, returncode=124, stdout="", stderr="Command timed out")
        except Exception as e:
            # Other errors - return error result
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=str(e))

    def ensure_server(self) -> Tuple[bool, bool]:
        if self._server_available:
            return True, True
        
        # First attempt: call --server
        result = self._run("--server", capture_output=True)
        was_already_running = False
        
        # Check if server is already running (exit code 2 with "Server is already running")
        if result.returncode == 2 and result.stderr:
            stderr_lower = result.stderr.lower()
            if "server is already running" in stderr_lower:
                was_already_running = True
        
        # Verify server is active
        time.sleep(0.2)  # Give server a moment to be ready
        status_result = self._run("--info", capture_output=True)
        if status_result.returncode == 0 and bool(status_result.stdout):
            self._server_available = True
            logger.info("MOC server is active (was already running: %s)", was_already_running)
            return True, was_already_running
        
        # Verification failed - try restart once
        logger.warning("MOC server verification failed, attempting restart")
        self._server_available = False
        
        # Second attempt: restart server
        result = self._run("--server", capture_output=True)
        time.sleep(0.3)  # Give server more time to start
        status_result = self._run("--info", capture_output=True)
        
        if status_result.returncode == 0 and bool(status_result.stdout):
            self._server_available = True
            logger.info("MOC server restarted successfully")
            return True, False
        
        # Failed to start server after retry
        logger.error("MOC server startup error - failed to start after retry")
        self._server_available = False
        return False, False

    # ------------------------------------------------------------------
    # M3U file operations (follow M3U standard with EXTINF pairs)
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
            with self._playlist_path.open('r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            i = 0
            track_index = 0
            while i < len(lines):
                line = lines[i].rstrip('\n\r')
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
                        file_path = lines[i + 1].rstrip('\n\r').strip()
                        if file_path and not file_path.startswith('#'):
                            tracks.append((track_index, extinf_line, file_path))
                            track_index += 1
                            i += 2  # Skip both EXTINF and file path lines
                            continue
                
                # If no EXTINF, treat as plain file path
                if not stripped.startswith('#'):
                    tracks.append((track_index, None, stripped))
                    track_index += 1
                
                i += 1
        except Exception as e:
            logger.error("Error parsing M3U file: %s", e, exc_info=True)
        
        return tracks
    
    def _write_m3u_playlist(self, tracks: List[Tuple[Optional[str], str]]) -> bool:
        """
        Write tracks to M3U playlist file following the standard format.
        
        Args:
            tracks: List of tuples (extinf_line, file_path)
                - extinf_line: EXTINF metadata line (with #EXTINF: prefix), or None
                - file_path: File path to write
        
        Returns:
            True if successful
        """
        try:
            self._playlist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._playlist_path.open('w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                for extinf_line, file_path in tracks:
                    if extinf_line:
                        f.write(extinf_line + '\n')
                    f.write(file_path + '\n')
            return True
        except Exception as e:
            logger.error("Error writing M3U file: %s", e, exc_info=True)
            return False
    
    def get_track_at_index_m3u(self, track_index: int) -> Optional[Tuple[Optional[str], str]]:
        """
        Get track at a specific index from the M3U playlist file.
        
        Args:
            track_index: Index of track to get (0-based)
            
        Returns:
            Tuple (extinf_line, file_path) or None if index is invalid
            - extinf_line: EXTINF metadata line or None
            - file_path: File path
        """
        parsed_tracks = self._parse_m3u_playlist()
        if not (0 <= track_index < len(parsed_tracks)):
            return None
        _, extinf_line, file_path = parsed_tracks[track_index]
        return (extinf_line, file_path)
    
    def add_track_at_index_m3u(self, track_index: int, file_path: str, extinf_line: Optional[str] = None) -> bool:
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
        
        if not (0 <= from_index < len(parsed_tracks) and 
                0 <= to_index < len(parsed_tracks)):
            return False
        
        # Convert to (extinf_line, file_path) format
        track_list = [(extinf, path) for _, extinf, path in parsed_tracks]
        
        # Move the track
        track = track_list.pop(from_index)
        track_list.insert(to_index, track)
        
        return self._write_m3u_playlist(track_list)
    
    
    def get_playlist_length_m3u(self) -> int:
        """Get the number of tracks in the M3U playlist file."""
        if not self._playlist_path.exists():
            return 0
        
        try:
            with self._playlist_path.open('r', encoding='utf-8', errors='ignore') as f:
                count = 0
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        count += 1
                return count
        except Exception as e:
            logger.error("Error reading M3U file length: %s", e, exc_info=True)
            return 0
    
    def clear_playlist_m3u(self):
        """Clear the M3U playlist file (keeps header)."""
        try:
            with self._playlist_path.open('w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
        except Exception as e:
            logger.error("Error clearing M3U file: %s", e, exc_info=True)
    
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

        # Parse M3U file
        parsed_tracks = self._parse_m3u_playlist()
        
        # Convert to TrackMetadata objects
        for _, _, file_path in parsed_tracks:
            # Only include files that actually exist
            if Path(file_path).exists():
                metadata = TrackMetadata(file_path)
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
        
        Uses caching to reduce server load. Set force_refresh=True to bypass cache.

        Returns None if status can't be read.
        """
        if not self._server_available:
            return None

        # Check cache first (unless forced refresh)
        current_time = time.time()
        if not force_refresh and self._status_cache is not None:
            if current_time - self._status_cache_time < self._status_cache_ttl:
                return self._status_cache
        
        # Check if we're in error backoff period
        if current_time - self._last_error_time < self._error_backoff:
            # Return cached status if available, otherwise None
            return self._status_cache
        
        result = self._run("--info", capture_output=True)
        
        # Handle errors with backoff
        if result.returncode != 0 or not result.stdout:
            self._last_error_time = current_time
            self._error_backoff = min(self._error_backoff * 2, 5.0)
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

        def parse_float(value: Optional[str]) -> float:
            """Parse a string value to float, returning 0.0 on error."""
            if not value:
                return 0.0
            try:
                return float(value)
            except ValueError:
                return 0.0

        # MOC outputs position and duration in seconds
        # Try both "CurrentSec" and "CurrentTime" (in case format varies)
        position = parse_float(info.get("CurrentSec"))
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
        
        duration = parse_float(info.get("TotalSec"))
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
        
        # Update cache
        self._status_cache = status
        self._status_cache_time = current_time
        
        return status

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def _check_server(self):
        """Helper: check if server is available."""
        return self._server_available
    
    def play(self):
        if not self._check_server():
            return
        status = self.get_status(force_refresh=False)
        self._run("--unpause" if status and status.get("state") == "PAUSE" else "--play")

    def pause(self):
        if self._check_server():
            self._run("--pause")

    def stop(self):
        if self._check_server():
            self._run("--stop")

    def shutdown(self):
        if self._check_server():
            self._run("--exit")
            self._server_available = False

    def next(self):
        if self._check_server():
            self._run("--next")

    def previous(self):
        if self._check_server():
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
        if not self._server_available:
            return False
        
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
        if not self._server_available:
            return
        vol_percent = int(max(0.0, min(1.0, volume)) * 100)
        self._run("--volume", str(vol_percent))

    def seek_relative(self, delta_seconds: float):
        """
        Seek relatively by delta in seconds (positive or negative).

        MOC uses `--seek N` for relative seek in seconds.
        """
        if not self._server_available:
            return
        seconds = int(delta_seconds)
        if seconds == 0:
            return
        self._run("--seek", str(seconds))

    def enable_autonext(self):
        """Enable autonext (autoplay) in MOC."""
        if not self._server_available:
            return
        self._run("--on=autonext")

    def disable_autonext(self):
        """Disable autonext (autoplay) in MOC."""
        if not self._server_available:
            return
        self._run("--off=autonext")

    def enable_shuffle(self):
        """Enable shuffle mode in MOC."""
        if not self._server_available:
            return
        self._run("--on=shuffle")

    def disable_shuffle(self):
        """Disable shuffle mode in MOC."""
        if not self._server_available:
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
    def set_playlist(self, tracks: List[TrackMetadata], current_index: int = -1, start_playback: bool = False):
        """
        Replace MOC's playlist with the given tracks by writing directly to M3U file.

        Args:
            tracks: List of tracks to become the new playlist.
            current_index: Index of the track that should start playing (if start_playback is True).
            start_playback: If True and current_index is valid, start playback of that track.
        """
        if not self._server_available:
            return
        
        # Build track list for M3U file (extinf_line, file_path pairs)
        # For now, we don't generate EXTINF lines - MOC will handle that
        track_list = []
        valid_tracks = []
        
        for track in tracks:
            if not track or not track.file_path:
                continue
            # Validate that file exists
            file_path = Path(track.file_path)
            if not file_path.exists() or not file_path.is_file():
                logger.warning("Track file does not exist: %s", track.file_path)
                continue
            # Use absolute path
            abs_path = str(file_path.resolve())
            track_list.append((None, abs_path))  # No EXTINF line for now
            valid_tracks.append(track)
        
        # Write entire playlist to M3U file
        if not self._write_m3u_playlist(track_list):
            logger.error("Failed to write playlist to M3U file")
            return
        
        # Optionally start playback from the selected track
        if start_playback and 0 <= current_index < len(valid_tracks):
            track = valid_tracks[current_index]
            if track and track.file_path:
                file_path = Path(track.file_path)
                if file_path.exists() and file_path.is_file():
                    abs_path = str(file_path.resolve())
                    # Check if MOC is already paused on this track - if so, just resume instead of restarting
                    status = self.get_status(force_refresh=False)
                    if status:
                        moc_state = status.get("state", "STOP")
                        moc_file = status.get("file_path")
                        if moc_state == "PAUSE" and moc_file:
                            moc_file_abs = str(Path(moc_file).resolve())
                            if moc_file_abs == abs_path:
                                # MOC is already paused on this track - just resume, don't restart
                                logger.debug("MOC is paused on target track - using --unpause to resume instead of restarting")
                                self._run("--unpause", capture_output=False)
                                return
                    
                    # Use --playit to play the specific file (works even if it's in playlist)
                    # This will restart from the beginning
                    result = self._run("--playit", abs_path, capture_output=True)
                    if result.returncode != 0:
                        # Fallback: use jump with 0-based index
                        self._run("-j", str(current_index), capture_output=False)
                        self._run("-p", capture_output=False)

    def play_file(self, file_path: str):
        """Play a specific file via MOC, keeping the playlist intact."""
        if not self._server_available:
            return
        if not file_path:
            logger.error("Cannot play file - file path is empty")
            return
        
        # Validate file exists
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            logger.error("Cannot play file - file does not exist: %s", file_path)
            return
        
        abs_path = str(path.resolve())
        result = self._run("--playit", abs_path, capture_output=True)
        if result.returncode != 0:
            logger.error("Failed to play file: %s", abs_path)
            if result.stderr:
                logger.debug("MOC error: %s", result.stderr)


