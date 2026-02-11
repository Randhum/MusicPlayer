"""PipeWire/PulseAudio volume control via pactl.

This module provides event-based volume monitoring and control using `pactl`,
which works reliably with both PulseAudio and PipeWire compatibility layers.
"""

import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

try:
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    GLIB_AVAILABLE = True
except ImportError:
    GLIB_AVAILABLE = False

from core.logging import get_logger

logger = get_logger(__name__)


class PipeWireVolume:
    """
    PipeWire volume control via pactl.

    Uses pactl for volume monitoring and control.
    """

    def __init__(self, on_volume_changed: Optional[Callable[[float], None]] = None):
        """
        Initialize PipeWire volume control.

        Args:
            on_volume_changed: Callback when volume changes externally
        """
        self.on_volume_changed = on_volume_changed
        self._monitoring_timeout_id = None
        self._last_volume: Optional[float] = None
        self._pactl_path: Optional[str] = shutil.which("pactl")

        # Use subprocess monitoring via pactl (stable and consistent across setups)
        if self._pactl_path and GLIB_AVAILABLE:
            if self.on_volume_changed:
                self._start_subprocess_monitoring()

    def _start_subprocess_monitoring(self) -> None:
        """
        Start monitoring volume changes via subprocess polling.

        Falls back to polling pactl when native D-Bus monitoring is unavailable.
        """
        if not GLIB_AVAILABLE:
            return

        # Initialize with current volume
        self._last_volume = self.get_volume()

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
        logger.debug("PipeWire: Started subprocess-based volume monitoring")

    def get_volume(self) -> float:
        """
        Get current system volume (0.0 to 1.0).

        Returns:
            Volume level from 0.0 to 1.0
        """
        if self._pactl_path:
            return self._get_pactl_volume()

        return 1.0  # Default

    def set_volume(self, volume: float):
        """
        Set system volume (0.0 to 1.0).

        Args:
            volume: Volume level from 0.0 to 1.0
        """
        volume = max(0.0, min(1.0, volume))
        if self._pactl_path:
            self._set_pactl_volume(volume)
            self._last_volume = volume

    def _get_pactl_volume(self) -> float:
        """Get volume using pactl subprocess."""
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
        except (OSError, subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug("PipeWire: Error getting volume via pactl: %s", e)
        return 1.0

    def _set_pactl_volume(self, volume: float):
        """Set volume using pactl subprocess."""
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
        except (OSError, subprocess.SubprocessError, FileNotFoundError) as e:
            logger.debug("PipeWire: Error setting volume via pactl: %s", e)

    def get_sinks(self) -> List[Dict[str, Any]]:
        """
        Get list of available audio sinks.

        Returns:
            List of sink dictionaries with name, description, etc.
        """
        sinks = []

        if self._pactl_path:
            try:
                result = subprocess.run(
                    [self._pactl_path, "list", "sinks", "short"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            sink_id = parts[0]
                            sink_name = parts[1]
                            description = (
                                " ".join(parts[2:]) if len(parts) > 2 else sink_name
                            )
                            sinks.append(
                                {
                                    "id": sink_id,
                                    "name": sink_name,
                                    "description": description,
                                }
                            )
            except (OSError, subprocess.SubprocessError, FileNotFoundError) as e:
                logger.debug("PipeWire: Error listing sinks: %s", e)

        return sinks

    def set_sink(self, sink_name: str) -> bool:
        """
        Set the default audio sink.

        Args:
            sink_name: Name or ID of the sink to set as default

        Returns:
            True if successful, False otherwise
        """
        if self._pactl_path:
            try:
                result = subprocess.run(
                    [self._pactl_path, "set-default-sink", sink_name],
                    capture_output=True,
                    timeout=2,
                    check=False,
                )
                return result.returncode == 0
            except (OSError, subprocess.SubprocessError, FileNotFoundError) as e:
                logger.debug("PipeWire: Error setting sink: %s", e)
        return False

    def cleanup(self):
        """Clean up resources."""
        # Stop monitoring
        if self._monitoring_timeout_id and GLIB_AVAILABLE:
            GLib.source_remove(self._monitoring_timeout_id)
            self._monitoring_timeout_id = None

        logger.debug("PipeWire: Cleaned up")
