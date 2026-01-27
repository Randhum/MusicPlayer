"""System volume control using PipeWire, PulseAudio, or ALSA."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import shutil
import subprocess
from typing import Callable, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
try:
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    GLIB_AVAILABLE = True
except ImportError:
    GLIB_AVAILABLE = False

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger

# Try to use native PipeWire integration
try:
    from core.pipewire_volume import PipeWireVolume

    PIPEWIRE_AVAILABLE = True
except ImportError:
    PIPEWIRE_AVAILABLE = False

logger = get_logger(__name__)


class SystemVolume:
    """Controls system volume via PipeWire, PulseAudio, or ALSA."""

    def __init__(self, on_volume_changed: Optional[Callable[[float], None]] = None):
        self.on_volume_changed = on_volume_changed
        self._pipewire: Optional[PipeWireVolume] = None
        self._pactl_path: Optional[str] = shutil.which("pactl")
        self._amixer_path: Optional[str] = shutil.which("amixer")
        self._use_pipewire = False
        self._use_pulseaudio = self._pactl_path is not None
        self._last_volume: Optional[float] = None
        self._monitoring_timeout_id = None

        # Try PipeWire native integration first
        if PIPEWIRE_AVAILABLE:
            try:
                self._pipewire = PipeWireVolume(on_volume_changed=on_volume_changed)
                # Check if PipeWire is actually available (pactl works with PipeWire too)
                if self._pactl_path:
                    # Test if we're using PipeWire by checking pactl info
                    try:
                        result = subprocess.run(
                            [self._pactl_path, "info"],
                            capture_output=True,
                            text=True,
                            timeout=1,
                        )
                        if result.returncode == 0 and "PipeWire" in result.stdout:
                            self._use_pipewire = True
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("PipeWire integration not available: %s", e)

        # Fallback to subprocess monitoring if PipeWire not available
        if not self._use_pipewire and GLIB_AVAILABLE and self.on_volume_changed:
            self._start_monitoring()

    def get_volume(self) -> float:
        """Get current system volume (0.0 to 1.0)."""
        if self._use_pipewire and self._pipewire:
            return self._pipewire.get_volume()
        elif self._use_pulseaudio:
            return self._get_pulseaudio_volume()
        elif self._amixer_path:
            return self._get_alsa_volume()
        return 1.0  # Default if neither available

    def set_volume(self, volume: float) -> None:
        """
        Set system volume (0.0 to 1.0).

        Args:
            volume: Volume level from 0.0 to 1.0 (will be clamped)
        """
        volume = max(0.0, min(1.0, volume))
        if self._use_pipewire and self._pipewire:
            self._pipewire.set_volume(volume)
        elif self._use_pulseaudio:
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
                timeout=2,
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

    def _set_pulseaudio_volume(self, volume: float) -> None:
        """
        Set volume in PulseAudio.

        Args:
            volume: Volume level from 0.0 to 1.0
        """
        vol_percent = int(volume * 100)
        try:
            subprocess.run(
                [
                    self._pactl_path,
                    "set-sink-volume",
                    "@DEFAULT_SINK@",
                    f"{vol_percent}%",
                ],
                capture_output=True,
                timeout=2,
                check=False,
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
                timeout=2,
            )
            if result.returncode == 0:
                # Parse output like "[50%]"
                for line in result.stdout.splitlines():
                    if "%" in line and "[" in line:
                        # Extract percentage
                        start = line.find("[")
                        end = line.find("%", start)
                        if start != -1 and end != -1:
                            vol_str = line[start + 1 : end]
                            try:
                                vol_percent = int(vol_str)
                                return vol_percent / 100.0
                            except ValueError:
                                pass
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass
        return 1.0

    def _set_alsa_volume(self, volume: float) -> None:
        """
        Set volume in ALSA.

        Args:
            volume: Volume level from 0.0 to 1.0
        """
        vol_percent = int(volume * 100)
        try:
            subprocess.run(
                [self._amixer_path, "set", "Master", f"{vol_percent}%"],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            pass

    def _start_monitoring(self) -> None:
        """Start monitoring for volume changes via periodic polling."""
        if not GLIB_AVAILABLE:
            return

        # Initialize with current volume
        self._last_volume = self.get_volume()

        # Poll every 500ms for volume changes
        def check_volume():
            current_volume = self.get_volume()
            if (
                self._last_volume is not None
                and abs(current_volume - self._last_volume) > 0.01
            ):
                # Volume changed externally
                if self.on_volume_changed:
                    self.on_volume_changed(current_volume)
            self._last_volume = current_volume
            return True  # Continue monitoring

        self._monitoring_timeout_id = GLib.timeout_add(500, check_volume)

    def get_sinks(self) -> list:
        """
        Get list of available audio sinks.

        Returns:
            List of sink dictionaries with name, description, etc.
        """
        if self._use_pipewire and self._pipewire:
            return self._pipewire.get_sinks()
        return []

    def set_sink(self, sink_name: str) -> bool:
        """Set the default audio sink."""
        if self._use_pipewire and self._pipewire:
            return self._pipewire.set_sink(sink_name)
        return False

    def cleanup(self) -> None:
        """
        Stop monitoring for volume changes and clean up resources.

        Should be called when the volume controller is no longer needed.
        """
        if self._pipewire:
            self._pipewire.cleanup()
        if self._monitoring_timeout_id and GLIB_AVAILABLE:
            GLib.source_remove(self._monitoring_timeout_id)
            self._monitoring_timeout_id = None
