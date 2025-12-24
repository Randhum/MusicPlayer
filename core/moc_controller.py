"""Integration with MOC (Music On Console) via the `mocp` CLI.

This module lets us:
- Read the current MOC playlist from ~/.moc/playlist.m3u
- Control playback (play/pause/stop/next/prev)
- Sync volume
- Query current status (state, track, position, duration, volume)
"""

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
    """Minimal wrapper around `mocp` for playlist and playback control."""

    def __init__(self):
        self._mocp_path: Optional[str] = shutil.which("mocp")
        # Get playlist path from config
        config = get_config()
        self._playlist_path: Path = config.moc_playlist_path
        # Track whether we've already attempted to start the server to avoid
        # spamming `mocp --server` on every status poll.
        self._server_initialized: bool = False
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
            if result.returncode != 0 and result.stderr:
                stderr_lower = result.stderr.lower()
                if "server is not running" in stderr_lower or "can't receive value" in stderr_lower or "can't connect" in stderr_lower:
                    self._server_initialized = False
                    self._status_cache = None
                    return subprocess.CompletedProcess(args=cmd, returncode=125, stdout="", stderr="")
            
            # Clear status cache on successful command (except for --info and --server)
            if "--info" not in args and "--server" not in args:
                self._status_cache = None
            return result
        except subprocess.TimeoutExpired:
            # Timeout - return error result
            return subprocess.CompletedProcess(args=cmd, returncode=124, stdout="", stderr="Command timed out")
        except Exception as e:
            # Other errors - return error result
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=str(e))

    def ensure_server(self):
        """Start the MOC server if it is not already running."""
        if not self.is_available():
            return False
        if self._server_initialized:
            return True
        result = self._run("--server", capture_output=True)
        if result.returncode == 0:
            time.sleep(0.1)
            self._server_initialized = True
            return True
        return False

    # ------------------------------------------------------------------
    # Playlist
    # ------------------------------------------------------------------
    def get_playlist(self) -> Tuple[List[TrackMetadata], int]:
        """
        Read MOC's current playlist and return (tracks, current_index).

        current_index is -1 if there is no active track.
        """
        tracks: List[TrackMetadata] = []
        current_index = -1

        if not self._playlist_path.exists():
            return tracks, current_index

        # Get current track path from status so we can align indices
        status = self.get_status()
        current_file = status.get("file_path") if status else None

        try:
            with self._playlist_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    # M3U entries are usually absolute paths; if not, treat as-is
                    path = Path(line).expanduser()
                    if not path.is_absolute():
                        path = path.expanduser()
                    file_path = str(path)
                    # Only include files that actually exist
                    if not Path(file_path).exists():
                        continue
                    metadata = TrackMetadata(file_path)
                    tracks.append(metadata)

            if current_file:
                for idx, track in enumerate(tracks):
                    if track.file_path == current_file:
                        current_index = idx
                        break
        except Exception as e:
            logger.error("Error reading MOC playlist: %s", e, exc_info=True)

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
        if not self.is_available():
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

        if not self.ensure_server():
            self._status_cache = None
            return None
        
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
        
        # Update cache
        self._status_cache = status
        self._status_cache_time = current_time
        
        return status

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    def play(self):
        """Start / resume playback."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--play")

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
            return
        # We don't call ensure_server() here on purpose – if the server is not
        # running, there is nothing to shut down.
        self._run("--exit")
        self._server_initialized = False

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
        self.ensure_server()
        self._run("--on=autonext")

    def disable_autonext(self):
        """Disable autonext (autoplay) in MOC."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--off=autonext")

    def enable_shuffle(self):
        """Enable shuffle mode in MOC."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--on=shuffle")

    def disable_shuffle(self):
        """Disable shuffle mode in MOC."""
        if not self.is_available():
            return
        self.ensure_server()
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
        Replace MOC's playlist with the given tracks.

        Args:
            tracks: List of tracks to become the new playlist.
            current_index: Index of the track that should start playing (if start_playback is True).
            start_playback: If True and current_index is valid, start playback of that track.
        """
        if not self.is_available():
            return
        self.ensure_server()

        # Clear existing playlist
        self._run("-c")  # equivalent to --clear

        # Validate and add tracks to MOC playlist
        # Track which tracks were successfully added (by original index)
        # We need to map original indices to MOC playlist indices since some tracks might fail to add
        successfully_added = {}  # Maps original index -> MOC playlist index
        moc_playlist_index = 0
        
        for idx, track in enumerate(tracks):
            if not track or not track.file_path:
                continue
            # Validate that file exists
            file_path = Path(track.file_path)
            if not file_path.exists() or not file_path.is_file():
                logger.warning("Track file does not exist: %s", track.file_path)
                continue
            # Use absolute path for MOC
            abs_path = str(file_path.resolve())
            # Append to MOC playlist
            result = self._run("-a", abs_path, capture_output=True)
            if result.returncode == 0:
                successfully_added[idx] = moc_playlist_index
                moc_playlist_index += 1
            else:
                logger.warning("Failed to add track to MOC playlist: %s", abs_path)
                if result.stderr:
                    logger.debug("MOC error: %s", result.stderr)

        # Optionally start playback from the selected track
        if start_playback and 0 <= current_index < len(tracks):
            if current_index in successfully_added:
                track = tracks[current_index]
                if track and track.file_path:
                    file_path = Path(track.file_path)
                    if file_path.exists() and file_path.is_file():
                        abs_path = str(file_path.resolve())
                        # Use --playit to play the specific file (works even if it's in playlist)
                        result = self._run("--playit", abs_path, capture_output=True)
                        if result.returncode != 0:
                            # Fallback: use jump with 0-based index
                            moc_index = successfully_added[current_index]
                            self._run("-j", str(moc_index), capture_output=False)
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


