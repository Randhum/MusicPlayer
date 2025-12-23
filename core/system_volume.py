"""System volume control using PulseAudio or ALSA."""

import subprocess
import shutil
from typing import Optional, Callable

try:
    import gi
    gi.require_version('GLib', '2.0')
    from gi.repository import GLib
    GLIB_AVAILABLE = True
except ImportError:
    GLIB_AVAILABLE = False


class SystemVolume:
    """Controls system volume via PulseAudio or ALSA."""
    
    def __init__(self, on_volume_changed: Optional[Callable[[float], None]] = None):
        self._pactl_path: Optional[str] = shutil.which("pactl")
        self._amixer_path: Optional[str] = shutil.which("amixer")
        self._use_pulseaudio = self._pactl_path is not None
        self.on_volume_changed = on_volume_changed
        self._last_volume: Optional[float] = None
        self._monitoring_timeout_id = None
        
        # Start monitoring for volume changes
        if GLIB_AVAILABLE and self.on_volume_changed:
            self._start_monitoring()
    
    def get_volume(self) -> float:
        """Get current system volume (0.0 to 1.0)."""
        if self._use_pulseaudio:
            return self._get_pulseaudio_volume()
        elif self._amixer_path:
            return self._get_alsa_volume()
        return 1.0  # Default if neither available
    
    def set_volume(self, volume: float):
        """Set system volume (0.0 to 1.0)."""
        volume = max(0.0, min(1.0, volume))
        if self._use_pulseaudio:
            self._set_pulseaudio_volume(volume)
        elif self._amixer_path:
            self._set_alsa_volume(volume)
        # Update last known volume to prevent triggering callback for our own changes
        self._last_volume = volume
    
    def _get_pulseaudio_volume(self) -> float:
        """Get volume from PulseAudio."""
        try:
            result = subprocess.run(
                [self._pactl_path, "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Parse output like "Volume: front-left: 32768 /  50% / -18.06 dB"
                for line in result.stdout.splitlines():
                    if "Volume:" in line and "%" in line:
                        # Extract percentage value
                        parts = line.split("%")
                        if parts:
                            vol_str = parts[0].split()[-1]
                            try:
                                vol_percent = int(vol_str)
                                return vol_percent / 100.0
                            except ValueError:
                                pass
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass
        return 1.0
    
    def _set_pulseaudio_volume(self, volume: float):
        """Set volume in PulseAudio."""
        vol_percent = int(volume * 100)
        try:
            subprocess.run(
                [self._pactl_path, "set-sink-volume", "@DEFAULT_SINK@", f"{vol_percent}%"],
                capture_output=True,
                timeout=2,
                check=False
            )
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass
    
    def _get_alsa_volume(self) -> float:
        """Get volume from ALSA."""
        try:
            result = subprocess.run(
                [self._amixer_path, "get", "Master"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Parse output like "[50%]"
                for line in result.stdout.splitlines():
                    if "%" in line and "[" in line:
                        # Extract percentage
                        start = line.find("[")
                        end = line.find("%", start)
                        if start != -1 and end != -1:
                            vol_str = line[start+1:end]
                            try:
                                vol_percent = int(vol_str)
                                return vol_percent / 100.0
                            except ValueError:
                                pass
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass
        return 1.0
    
    def _set_alsa_volume(self, volume: float):
        """Set volume in ALSA."""
        vol_percent = int(volume * 100)
        try:
            subprocess.run(
                [self._amixer_path, "set", "Master", f"{vol_percent}%"],
                capture_output=True,
                timeout=2,
                check=False
            )
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass
    
    def _start_monitoring(self):
        """Start monitoring for volume changes via periodic polling."""
        if not GLIB_AVAILABLE:
            return
        
        # Initialize with current volume
        self._last_volume = self.get_volume()
        
        # Poll every 500ms for volume changes
        def check_volume():
            current_volume = self.get_volume()
            if self._last_volume is not None and abs(current_volume - self._last_volume) > 0.01:
                # Volume changed externally
                if self.on_volume_changed:
                    self.on_volume_changed(current_volume)
            self._last_volume = current_volume
            return True  # Continue monitoring
        
        self._monitoring_timeout_id = GLib.timeout_add(500, check_volume)
    
    def cleanup(self):
        """Stop monitoring for volume changes."""
        if self._monitoring_timeout_id and GLIB_AVAILABLE:
            GLib.source_remove(self._monitoring_timeout_id)
            self._monitoring_timeout_id = None

