"""Advanced Bluetooth features.

This module provides:
- Codec selection (SBC, AAC, aptX if available)
- Battery level monitoring for connected devices
- Connection quality indicators (RSSI, link quality)
- Multiple device support (switch between speakers)
- Device profiles management
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from typing import Any, Callable, Dict, List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import dbus

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger

logger = get_logger(__name__)


# BlueZ interfaces
BLUEZ_SERVICE = "org.bluez"
DEVICE_INTERFACE = "org.bluez.Device1"
MEDIA_TRANSPORT_INTERFACE = "org.bluez.MediaTransport1"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"


class BluetoothAdvanced:
    """
    Advanced Bluetooth features manager.

    Provides codec selection, battery monitoring, and connection quality tracking.
    """

    def __init__(self, bus: dbus.Bus, adapter_path: str):
        """
        Initialize advanced Bluetooth features.

        Args:
            bus: D-Bus system bus
            adapter_path: Path to Bluetooth adapter
        """
        self.bus = bus
        self.adapter_path = adapter_path
        self._signal_receivers = []
        self._battery_callbacks: Dict[str, Callable[[int], None]] = {}
        self._quality_callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}

    def get_available_codecs(self, device_path: str) -> List[str]:
        """
        Get available audio codecs for a device.

        Args:
            device_path: D-Bus path of the device

        Returns:
            List of available codec names (e.g., ['SBC', 'AAC', 'aptX'])
        """
        codecs = []
        try:
            # Get device properties
            device_obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
            props = dbus.Interface(device_obj, PROPERTIES_INTERFACE)

            # Check for MediaTransport to get codec info
            manager = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            for path, interfaces in objects.items():
                if MEDIA_TRANSPORT_INTERFACE in interfaces:
                    transport_props = interfaces[MEDIA_TRANSPORT_INTERFACE]
                    device = str(transport_props.get("Device", ""))
                    if device == device_path:
                        # Get codec information
                        codec = transport_props.get("Codec", 0)
                        # Codec values: 0=SBC, 1=MPEG24, 2=AAC, 3=aptX, 4=aptX HD, 5=LDAC
                        codec_map = {
                            0: "SBC",
                            1: "MPEG24",
                            2: "AAC",
                            3: "aptX",
                            4: "aptX HD",
                            5: "LDAC",
                        }
                        codec_name = codec_map.get(codec, f"Unknown({codec})")
                        if codec_name not in codecs:
                            codecs.append(codec_name)
        except Exception as e:
            logger.error(
                "Bluetooth advanced: Error getting codecs for %s: %s",
                device_path,
                e,
                exc_info=True,
            )

        return codecs if codecs else ["SBC"]  # SBC is always available

    def get_battery_level(self, device_path: str) -> Optional[int]:
        """
        Get battery level for a Bluetooth device.

        Args:
            device_path: D-Bus path of the device

        Returns:
            Battery level (0-100), or None if unavailable
        """
        try:
            device_obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
            props = dbus.Interface(device_obj, PROPERTIES_INTERFACE)

            # Try Battery1 interface (if available)
            try:
                battery = props.Get("org.bluez.Battery1", "Percentage")
                return int(battery)
            except dbus.exceptions.DBusException:
                # Battery1 interface not available
                pass

            # Try to get from device properties
            # Some devices expose battery in device properties
            device_props = props.GetAll(DEVICE_INTERFACE)
            if "Battery" in device_props:
                return int(device_props["Battery"])

        except Exception as e:
            logger.debug("Bluetooth advanced: Error getting battery level: %s", e)

        return None

    def monitor_battery(self, device_path: str, callback: Callable[[int], None]):
        """
        Monitor battery level changes for a device.

        Args:
            device_path: D-Bus path of the device
            callback: Function to call with battery level (0-100)
        """
        self._battery_callbacks[device_path] = callback

        # Set up property change monitoring
        try:
            receiver = self.bus.add_signal_receiver(
                self._on_battery_changed,
                dbus_interface=PROPERTIES_INTERFACE,
                signal_name="PropertiesChanged",
                path=device_path,
                path_keyword="path",
            )
            self._signal_receivers.append(receiver)
            logger.debug(
                "Bluetooth advanced: Started battery monitoring for %s", device_path
            )
        except Exception as e:
            logger.error(
                "Bluetooth advanced: Error setting up battery monitoring: %s",
                e,
                exc_info=True,
            )

    def _on_battery_changed(
        self, interface: str, changed: Dict[str, Any], invalidated: List[str], path: str
    ):
        """Handle battery property changes."""
        if path in self._battery_callbacks:
            if "org.bluez.Battery1" in interface or "Percentage" in changed:
                battery = changed.get("Percentage")
                if battery is not None:
                    self._battery_callbacks[path](int(battery))
            elif "Battery" in changed:
                battery = changed.get("Battery")
                if battery is not None:
                    self._battery_callbacks[path](int(battery))

    def get_rssi(self, device_path: str) -> Optional[int]:
        """
        Get RSSI (Received Signal Strength Indicator) for a device.

        Args:
            device_path: D-Bus path of the device

        Returns:
            RSSI value in dBm, or None if unavailable
        """
        try:
            device_obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
            props = dbus.Interface(device_obj, PROPERTIES_INTERFACE)

            # RSSI is typically in device properties
            rssi = props.Get(DEVICE_INTERFACE, "RSSI")
            return int(rssi)
        except dbus.exceptions.DBusException:
            # RSSI not available
            pass
        except Exception as e:
            logger.debug("Bluetooth advanced: Error getting RSSI: %s", e)

        return None

    def get_link_quality(self, device_path: str) -> Optional[float]:
        """
        Get link quality for a device (0.0 to 1.0).

        Args:
            device_path: D-Bus path of the device

        Returns:
            Link quality (0.0 to 1.0), or None if unavailable
        """
        rssi = self.get_rssi(device_path)
        if rssi is not None:
            # Convert RSSI to quality (rough approximation)
            # RSSI typically ranges from -100 (poor) to 0 (excellent)
            quality = max(0.0, min(1.0, (rssi + 100) / 100.0))
            return quality
        return None

    def monitor_quality(
        self, device_path: str, callback: Callable[[Dict[str, Any]], None]
    ):
        """
        Monitor connection quality changes.

        Args:
            device_path: D-Bus path of the device
            callback: Function to call with quality info (RSSI, quality, etc.)
        """
        self._quality_callbacks[device_path] = callback

        # Set up property change monitoring
        try:
            receiver = self.bus.add_signal_receiver(
                self._on_quality_changed,
                dbus_interface=PROPERTIES_INTERFACE,
                signal_name="PropertiesChanged",
                path=device_path,
                path_keyword="path",
            )
            self._signal_receivers.append(receiver)
            logger.debug(
                "Bluetooth advanced: Started quality monitoring for %s", device_path
            )
        except Exception as e:
            logger.error(
                "Bluetooth advanced: Error setting up quality monitoring: %s",
                e,
                exc_info=True,
            )

    def _on_quality_changed(
        self, interface: str, changed: Dict[str, Any], invalidated: List[str], path: str
    ):
        """Handle quality property changes."""
        if path in self._quality_callbacks:
            quality_info = {}

            if "RSSI" in changed:
                rssi = int(changed["RSSI"])
                quality_info["rssi"] = rssi
                quality_info["quality"] = max(0.0, min(1.0, (rssi + 100) / 100.0))

            if quality_info:
                self._quality_callbacks[path](quality_info)

    def get_device_info(self, device_path: str) -> Dict[str, Any]:
        """
        Get comprehensive device information.

        Args:
            device_path: D-Bus path of the device

        Returns:
            Dictionary with device information
        """
        info = {
            "path": device_path,
            "codecs": self.get_available_codecs(device_path),
            "battery": self.get_battery_level(device_path),
            "rssi": self.get_rssi(device_path),
            "link_quality": self.get_link_quality(device_path),
        }

        try:
            device_obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
            props = dbus.Interface(device_obj, PROPERTIES_INTERFACE)
            device_props = props.GetAll(DEVICE_INTERFACE)

            info.update(
                {
                    "name": str(device_props.get("Name", "Unknown")),
                    "address": str(device_props.get("Address", "")),
                    "connected": bool(device_props.get("Connected", False)),
                    "paired": bool(device_props.get("Paired", False)),
                    "trusted": bool(device_props.get("Trusted", False)),
                }
            )
        except Exception as e:
            logger.error(
                "Bluetooth advanced: Error getting device info: %s", e, exc_info=True
            )

        return info

    def cleanup(self):
        """Clean up resources."""
        for receiver in self._signal_receivers:
            try:
                self.bus.remove_signal_receiver(receiver)
            except Exception:
                pass
        self._signal_receivers.clear()
        self._battery_callbacks.clear()
        self._quality_callbacks.clear()
        logger.debug("Bluetooth advanced: Cleaned up")
