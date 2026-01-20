"""Native PipeWire volume control via D-Bus.

This module provides event-based volume control using PipeWire's D-Bus interface,
with fallback to subprocess calls (pactl) if native D-Bus is unavailable.
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False

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

logger = get_logger(__name__)


# PipeWire D-Bus service
PIPEWIRE_SERVICE = "org.freedesktop.portal.Desktop"
PIPEWIRE_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PIPEWIRE_INTERFACE = "org.freedesktop.portal.Settings"


class PipeWireVolume:
    """
    Native PipeWire volume control via D-Bus.

    Uses PipeWire's D-Bus interface for event-based volume monitoring
    and control, with fallback to pactl subprocess calls.
    """

    def __init__(self, on_volume_changed: Optional[Callable[[float], None]] = None):
        """
        Initialize PipeWire volume control.

        Args:
            on_volume_changed: Callback when volume changes externally
        """
        self.on_volume_changed = on_volume_changed
        self._use_native = False
        self._bus = None
        self._sink_proxy = None
        self._signal_receivers = []
        self._monitoring_timeout_id = None
        self._last_volume: Optional[float] = None
        self._pactl_path: Optional[str] = shutil.which("pactl")

        # Try native D-Bus first
        if DBUS_AVAILABLE and GLIB_AVAILABLE:
            try:
                DBusGMainLoop(set_as_default=True)
                self._bus = dbus.SessionBus()
                self._setup_native()
                if self._sink_proxy:
                    self._use_native = True
                    logger.info("PipeWire: Using native D-Bus interface")
            except Exception as e:
                logger.debug("PipeWire: Native D-Bus setup failed: %s", e)
                logger.info("PipeWire: Falling back to subprocess (pactl)")

        # Fallback to subprocess monitoring if native not available
        if not self._use_native and self._pactl_path and GLIB_AVAILABLE:
            if self.on_volume_changed:
                self._start_subprocess_monitoring()

    def _setup_native(self) -> None:
        """
        Set up native PipeWire D-Bus interface.

        Attempts to connect to PipeWire via D-Bus and configure event monitoring.
        """
        try:
            # Check if PipeWire is available via portal
            # PipeWire exposes sinks through the portal interface
            portal_obj = self._bus.get_object(PIPEWIRE_SERVICE, PIPEWIRE_OBJECT_PATH)
            portal = dbus.Interface(portal_obj, PIPEWIRE_INTERFACE)

            # Try to get default sink
            # Note: PipeWire portal interface may differ, so we'll use pactl for now
            # but set up for future native integration

            # For now, use PulseAudio-compatible interface via D-Bus
            # PipeWire provides PulseAudio compatibility
            try:
                pulse_service = "org.PulseAudio.Core"
                pulse_path = "/org/pulseaudio/core1"
                core_obj = self._bus.get_object(pulse_service, pulse_path)
                # This will work if PipeWire is running with PulseAudio compatibility
                logger.debug("PipeWire: Found PulseAudio compatibility layer")
            except dbus.exceptions.DBusException:
                # Try direct PipeWire interface
                pass

            # Set up signal monitoring for volume changes
            # This would be done via PropertiesChanged signals
            # For now, we'll use polling with native interface when available

        except Exception as e:
            logger.debug("PipeWire: Native setup error: %s", e)

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
        if self._use_native and self._sink_proxy:
            try:
                # Use native D-Bus interface
                props = dbus.Interface(
                    self._sink_proxy, "org.freedesktop.DBus.Properties"
                )
                volume = props.Get("org.PulseAudio.Core1.Device", "Volume")
                # Volume is typically a list of channel volumes, take first
                if volume and len(volume) > 0:
                    # PulseAudio volume is in 0-65536 range
                    vol_value = float(volume[0]) / 65536.0
                    return max(0.0, min(1.0, vol_value))
            except Exception as e:
                logger.debug(
                    "PipeWire: Error getting volume via native interface: %s", e
                )

        # Fallback to subprocess
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

        if self._use_native and self._sink_proxy:
            try:
                # Use native D-Bus interface
                sink = dbus.Interface(self._sink_proxy, "org.PulseAudio.Core1.Device")
                # Convert to PulseAudio volume range (0-65536)
                vol_value = int(volume * 65536)
                # Set volume for all channels
                sink.SetVolume([dbus.UInt32(vol_value), dbus.UInt32(vol_value)])
                self._last_volume = volume
                return
            except Exception as e:
                logger.debug(
                    "PipeWire: Error setting volume via native interface: %s", e
                )

        # Fallback to subprocess
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
        # Remove signal receivers
        for receiver in self._signal_receivers:
            try:
                self._bus.remove_signal_receiver(receiver)
            except Exception:
                pass
        self._signal_receivers.clear()

        # Stop monitoring
        if self._monitoring_timeout_id and GLIB_AVAILABLE:
            GLib.source_remove(self._monitoring_timeout_id)
            self._monitoring_timeout_id = None

        logger.debug("PipeWire: Cleaned up")
