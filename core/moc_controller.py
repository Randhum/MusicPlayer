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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.metadata import TrackMetadata


class MocController:
    """Minimal wrapper around `mocp` for playlist and playback control."""

    def __init__(self):
        self._mocp_path: Optional[str] = shutil.which("mocp")
        self._playlist_path: Path = Path.home() / ".moc" / "playlist.m3u"
        # Track whether we've already attempted to start the server to avoid
        # spamming `mocp --server` on every status poll.
        self._server_initialized: bool = False

    # ------------------------------------------------------------------
    # Availability / helpers
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Return True if `mocp` is available in PATH."""
        return self._mocp_path is not None

    def _run(self, *args: str, capture_output: bool = False) -> subprocess.CompletedProcess:
        """Run `mocp` with the given arguments."""
        if not self._mocp_path:
            # Simulate a failed process
            return subprocess.CompletedProcess(args=["mocp", *args], returncode=127, stdout="", stderr="mocp not found")

        cmd = [self._mocp_path, *args]
        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            check=False,
        )

    def ensure_server(self):
        """Start the MOC server if it is not already running."""
        if not self.is_available():
            return
        if self._server_initialized:
            return
        # This is safe to call even if the server is already running; we just
        # avoid doing it more than once per application run.
        self._run("--server")
        self._server_initialized = True

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
            print(f"Error reading MOC playlist: {e}")

        return tracks, current_index

    # ------------------------------------------------------------------
    # Status / info
    # ------------------------------------------------------------------
    def get_status(self) -> Optional[Dict]:
        """
        Get current MOC status (state, file, position, duration, volume).

        Returns None if status can't be read.
        """
        if not self.is_available():
            return None

        self.ensure_server()
        result = self._run("--info", capture_output=True)
        if result.returncode != 0 or not result.stdout:
            return None

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

        position = _parse_float(info.get("CurrentSec"))
        duration = _parse_float(info.get("TotalSec"))

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

        return {
            "state": state,  # PLAY, PAUSE, STOP
            "file_path": file_path,
            "position": position,
            "duration": duration,
            "volume": volume,
        }

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

        # Append tracks in order
        for track in tracks:
            self._run("-a", track.file_path)  # equivalent to --append

        # Optionally start playback from the selected track
        if start_playback and 0 <= current_index < len(tracks):
            # Play the desired track; mocp will find it in the playlist
            self._run("--playit", tracks[current_index].file_path)

    def play_file(self, file_path: str):
        """Play a specific file via MOC, keeping the playlist intact."""
        if not self.is_available():
            return
        self.ensure_server()
        self._run("--playit", file_path)


