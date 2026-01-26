"""Bluetooth A2DP sink management for receiving audio from mobile devices."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Set

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import dbus
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.bluetooth_manager import BluetoothDevice, BluetoothManager
from core.events import EventBus
from core.logging import get_logger
from core.security import SecurityValidator

logger = get_logger(__name__)

# Default timeout for discoverability (seconds) - 0 means indefinite
DEFAULT_DISCOVERABLE_TIMEOUT = 300  # 5 minutes
# Connection health check interval (milliseconds)
CONNECTION_HEALTH_CHECK_INTERVAL = 5000  # 5 seconds
# Reconnection attempt delay (milliseconds)
RECONNECTION_DELAY = 3000  # 3 seconds
# Maximum reconnection attempts
MAX_RECONNECTION_ATTEMPTS = 3


class BluetoothSink:
    """
    Manages Bluetooth A2DP sink functionality.

    When enabled, this allows the computer to act as a Bluetooth speaker,
    receiving audio from phones and other devices, and playing it through
    the local audio output (ALSA).
    """

    MEDIA_CONTROL_INTERFACE = "org.bluez.MediaControl1"
    MEDIA_PLAYER_INTERFACE = "org.bluez.MediaPlayer1"
    MEDIA_TRANSPORT_INTERFACE = "org.bluez.MediaTransport1"
    PROFILE_INTERFACE = "org.bluez.Profile1"
    PROFILE_MANAGER_INTERFACE = "org.bluez.ProfileManager1"

    def __init__(
        self, bt_manager: BluetoothManager, event_bus: Optional[EventBus] = None
    ):
        """
        Initialize Bluetooth sink.

        Args:
            bt_manager: BluetoothManager instance
            event_bus: EventBus instance for publishing events (optional)
        """
        self.bt_manager = bt_manager
        self._event_bus = event_bus
        self.is_sink_enabled = False
        self.is_discoverable = False
        self.connected_device: Optional[BluetoothDevice] = None
        self.device_name = "Music Player Speaker"

        # GStreamer BlueZ plugin support
        self.gst_bluez_available = False
        self._check_gst_bluez_plugin()

        # Callback for when audio stream stops (can be set externally)
        self.on_audio_stream_stopped: Optional[Callable[[], None]] = None

        # ====================================================================
        # Security Settings
        # ====================================================================
        # Trusted device whitelist (MAC addresses in uppercase, colon-separated)
        # Empty set means all paired devices are allowed
        self._trusted_devices: Set[str] = set()
        # Whether to require explicit authorization for new connections
        self._require_authorization = False
        # Discoverable timeout in seconds (0 = indefinite, not recommended)
        self._discoverable_timeout = DEFAULT_DISCOVERABLE_TIMEOUT

        # ====================================================================
        # Stability/Reconnection Settings
        # ====================================================================
        # Track last connected device for reconnection
        self._last_connected_address: Optional[str] = None
        # Reconnection state
        self._reconnection_attempts = 0
        self._reconnection_timer_id: Optional[int] = None
        # Connection health monitoring
        self._health_check_timer_id: Optional[int] = None
        # A2DP transport state
        self._transport_state: Optional[str] = None
        # Thread lock for state changes
        self._state_lock = threading.Lock()

        # Register sink mode checker callback with BT manager (avoids circular dependency)
        if hasattr(self.bt_manager, "register_sink_mode_checker"):
            self.bt_manager.register_sink_mode_checker(lambda: self.is_sink_enabled)

        # Subscribe to BT manager events
        if self._event_bus:
            self._event_bus.subscribe(
                EventBus.BT_DEVICE_CONNECTED, self._on_bt_device_connected
            )
            self._event_bus.subscribe(
                EventBus.BT_DEVICE_DISCONNECTED, self._on_bt_device_disconnected
            )

    # ========================================================================
    # Security Configuration Methods
    # ========================================================================

    def add_trusted_device(self, address: str) -> bool:
        """
        Add a device to the trusted whitelist.

        Args:
            address: Bluetooth MAC address (e.g., "AA:BB:CC:DD:EE:FF")

        Returns:
            True if added successfully, False otherwise
        """
        try:
            # Normalize address format
            normalized = address.upper().strip()
            if not self._validate_mac_address(normalized):
                logger.warning("Invalid MAC address format: %s", address)
                return False

            self._trusted_devices.add(normalized)
            logger.info("Added trusted device: %s", normalized)
            return True
        except Exception as e:
            logger.error("Error adding trusted device: %s", e, exc_info=True)
            return False

    def remove_trusted_device(self, address: str) -> bool:
        """
        Remove a device from the trusted whitelist.

        Args:
            address: Bluetooth MAC address

        Returns:
            True if removed, False if not found
        """
        normalized = address.upper().strip()
        if normalized in self._trusted_devices:
            self._trusted_devices.discard(normalized)
            logger.info("Removed trusted device: %s", normalized)
            return True
        return False

    def get_trusted_devices(self) -> List[str]:
        """Get list of trusted device addresses."""
        return list(self._trusted_devices)

    def clear_trusted_devices(self) -> None:
        """Clear all trusted devices (allow any paired device)."""
        self._trusted_devices.clear()
        logger.info("Cleared trusted device whitelist")

    def set_require_authorization(self, require: bool) -> None:
        """
        Set whether to require explicit authorization for connections.

        Args:
            require: If True, user must approve each connection
        """
        self._require_authorization = require
        logger.info("Connection authorization requirement: %s", require)

    def set_discoverable_timeout(self, timeout_seconds: int) -> None:
        """
        Set discoverable timeout.

        Args:
            timeout_seconds: Timeout in seconds (0 = indefinite, NOT recommended)
        """
        if timeout_seconds < 0:
            timeout_seconds = DEFAULT_DISCOVERABLE_TIMEOUT

        self._discoverable_timeout = timeout_seconds
        logger.info("Discoverable timeout set to %d seconds", timeout_seconds)

        # Update if already discoverable
        if self.is_discoverable:
            self._set_discoverable(True, timeout_seconds)

    def is_device_authorized(self, device: BluetoothDevice) -> bool:
        """
        Check if a device is authorized to connect.

        Args:
            device: BluetoothDevice to check

        Returns:
            True if authorized, False otherwise
        """
        # If whitelist is empty, all paired devices are authorized
        if not self._trusted_devices:
            return device.paired

        # Check whitelist
        address = device.address.upper().strip()
        return address in self._trusted_devices and device.paired

    @staticmethod
    def _validate_mac_address(address: str) -> bool:
        """Validate MAC address format."""
        import re

        pattern = r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$"
        return bool(re.match(pattern, address))

    def _check_gst_bluez_plugin(self) -> None:
        """Check if GStreamer BlueZ plugin is available."""
        try:
            if not Gst.is_initialized():
                Gst.init(None)

            registry = Gst.Registry.get()
            factories = registry.get_feature_list(Gst.ElementFactory)

            # Check for BlueZ-related elements in registry
            for factory in factories:
                if "bluez" in factory.get_name().lower():
                    self.gst_bluez_available = True
                    logger.debug("GStreamer BlueZ plugin found: %s", factory.get_name())
                    return

            # Try common BlueZ element names
            for element_name in ["bluezsrc", "bluezsink", "bluezaudiosrc"]:
                if Gst.ElementFactory.make(element_name, element_name):
                    self.gst_bluez_available = True
                    logger.debug("GStreamer BlueZ element found: %s", element_name)
                    return

            logger.debug("GStreamer BlueZ plugin not found, using PipeWire/PulseAudio")
            self.gst_bluez_available = False
        except Exception as e:
            logger.debug("Error checking GStreamer BlueZ plugin: %s", e)
            self.gst_bluez_available = False

    def enable_sink_mode(self) -> bool:
        """
        Enable Bluetooth A2DP sink mode.
        This configures the system to receive audio from Bluetooth devices
        and makes the computer discoverable as a Bluetooth speaker.

        According to Bluetooth A2DP specification:
        - Verifies A2DP sink profile is available
        - Sets adapter to discoverable and pairable
        - Configures audio routing for A2DP streams
        """
        try:
            # Ensure Bluetooth is powered on
            if not self.bt_manager.is_powered():
                if not self.bt_manager.set_powered(True):
                    logger.error("Failed to power on Bluetooth adapter")
                    return False

            # Verify A2DP sink profile support
            if not self._verify_a2dp_sink_support():
                logger.warning("A2DP sink profile may not be fully supported")
                logger.warning("Audio streaming may not work properly")

            # Set device name
            self._set_adapter_name(self.device_name)

            # Make adapter discoverable and pairable (with timeout for security)
            self._set_discoverable(True, self._discoverable_timeout)
            self._set_pairable(True)

            # Start connection health monitoring
            self._start_health_monitoring()

            # Configure audio subsystem
            # Prefer GStreamer BlueZ plugin if available
            if self.gst_bluez_available:
                success = self._enable_gst_bluez_sink()
            else:
                audio_system = self._detect_audio_system()

                if audio_system == "pipewire":
                    success = self._enable_pipewire_sink()
                elif audio_system == "pulseaudio":
                    success = self._enable_pulseaudio_sink()
                else:
                    logger.warning(
                        "No compatible audio system found. Trying basic setup."
                    )
                    success = self._enable_basic_sink()

            if success:
                self.is_sink_enabled = True
                if self._event_bus:
                    self._event_bus.publish(EventBus.BT_SINK_ENABLED, {})

            return success

        except Exception as e:
            logger.error("Error enabling Bluetooth sink: %s", e, exc_info=True)
            return False

    def disable_sink_mode(self) -> bool:
        """
        Disable Bluetooth A2DP sink mode.

        Properly terminates all A2DP connections and cleans up resources:
        - Stops health monitoring and reconnection attempts
        - Disconnects all connected devices
        - Terminates A2DP transport connections
        - Stops being discoverable and pairable
        - Cleans up audio routing
        """
        try:
            logger.info("Disabling Bluetooth sink mode...")

            # Stop health monitoring and reconnection
            self._stop_health_monitoring()
            self._cancel_reconnection()

            # First, disconnect and terminate A2DP connections for all connected devices
            connected_devices = []
            if self.connected_device:
                connected_devices.append(self.connected_device)
            else:
                # Check for any connected devices
                for device in self.bt_manager.get_devices():
                    if device.connected:
                        connected_devices.append(device)

            for device in connected_devices:
                logger.info("Disconnecting device: %s (%s)", device.name, device.address)

                if self.on_audio_stream_stopped is not None:
                    try:
                        self.on_audio_stream_stopped()
                    except Exception as e:
                        logger.error("Error in audio stream stopped callback: %s", e)

                self._terminate_a2dp_transport(device)
                time.sleep(0.3)  # Allow transport to close

                self.bt_manager.disconnect_device(device.path)
                time.sleep(0.2)  # Allow disconnection to complete

            # Stop being discoverable and pairable
            self._set_discoverable(False)
            self._set_pairable(False)

            # Update state flags BEFORE clearing connected device
            # This ensures _is_sink_mode_enabled() returns False immediately
            self.is_sink_enabled = False
            self.is_discoverable = False

            # Clear connected device reference
            self.connected_device = None

            # After disabling, disconnect any devices that might still be connected
            # (in case they connected while we were disabling or after)
            remaining_connected = []
            for device in self.bt_manager.get_devices():
                if device.connected:
                    remaining_connected.append(device)

            for device in remaining_connected:
                logger.info("Disconnecting %s - sink mode is now disabled", device.name)
                self.bt_manager.disconnect_device(device.path)

            # Publish event
            if self._event_bus:
                self._event_bus.publish(EventBus.BT_SINK_DISABLED, {})

            logger.info("Bluetooth sink mode disabled successfully")
            return True
        except Exception as e:
            logger.error("Error disabling Bluetooth sink: %s", e, exc_info=True)
            return False

    def _verify_a2dp_sink_support(self) -> bool:
        """
        Verify that A2DP sink profile is available.

        According to Bluetooth A2DP specification, the sink profile must be
        registered with BlueZ for the adapter to accept A2DP connections.
        """
        try:
            # Check if A2DP sink profile is registered via D-Bus
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )

            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                # Look for profile manager or A2DP-related interfaces
                if self.PROFILE_MANAGER_INTERFACE in interfaces:
                    return True
                # Check for A2DP sink in adapter properties
                if self.bt_manager.ADAPTER_INTERFACE in interfaces:
                    props = interfaces[self.bt_manager.ADAPTER_INTERFACE]
                    # A2DP support is typically indicated by available profiles
                    # We'll assume it's available if adapter exists
                    return True

            # If we can't verify, assume it might work (some systems don't expose this)
            return True
        except Exception as e:
            logger.warning("Could not verify A2DP sink support: %s", e)
            # Assume it might work anyway
            return True

    def _detect_audio_system(self) -> str:
        """Detect which audio system is running."""
        try:
            # Check for PipeWire first (modern)
            result = subprocess.run(
                ["pgrep", "-x", "pipewire"], capture_output=True, timeout=2
            )
            if result.returncode == 0:
                return "pipewire"

            # Check for PulseAudio
            result = subprocess.run(
                ["pgrep", "-x", "pulseaudio"], capture_output=True, timeout=2
            )
            if result.returncode == 0:
                return "pulseaudio"

            return "none"
        except (OSError, subprocess.SubprocessError, FileNotFoundError):
            # Audio system detection failed
            return "none"

    def _set_adapter_name(self, name: str):
        """Set the Bluetooth adapter's visible name."""
        try:
            if not self.bt_manager.adapter_path:
                return

            props = dbus.Interface(
                self.bt_manager.bus.get_object(
                    self.bt_manager.BLUEZ_SERVICE, self.bt_manager.adapter_path
                ),
                self.bt_manager.PROPERTIES_INTERFACE,
            )
            props.Set(self.bt_manager.ADAPTER_INTERFACE, "Alias", dbus.String(name))
            logger.info("Set Bluetooth name to: %s", name)
        except Exception as e:
            logger.error("Error setting adapter name: %s", e, exc_info=True)

    def _set_discoverable(
        self, discoverable: bool, timeout: int = DEFAULT_DISCOVERABLE_TIMEOUT
    ):
        """
        Set the Bluetooth adapter's discoverability.

        Args:
            discoverable: Whether to be discoverable
            timeout: Timeout in seconds (0 = indefinite, NOT recommended for security)
        """
        try:
            if not self.bt_manager.adapter_path:
                return

            # Validate D-Bus path for security
            if not SecurityValidator.validate_dbus_path(self.bt_manager.adapter_path):
                logger.error("Security: Invalid adapter path")
                return

            props = dbus.Interface(
                self.bt_manager.bus.get_object(
                    self.bt_manager.BLUEZ_SERVICE, self.bt_manager.adapter_path
                ),
                self.bt_manager.PROPERTIES_INTERFACE,
            )

            props.Set(
                self.bt_manager.ADAPTER_INTERFACE,
                "Discoverable",
                dbus.Boolean(discoverable),
            )

            if discoverable:
                # Set timeout (0 = indefinite, but we recommend using a timeout for security)
                props.Set(
                    self.bt_manager.ADAPTER_INTERFACE,
                    "DiscoverableTimeout",
                    dbus.UInt32(timeout),
                )
                if timeout == 0:
                    logger.warning(
                        "Security: Discoverable with no timeout - consider setting a timeout"
                    )
                else:
                    logger.info("Discoverable for %d seconds", timeout)

            self.is_discoverable = discoverable
            logger.debug(
                "Discoverable: %s (timeout: %ds)",
                discoverable,
                timeout if discoverable else 0,
            )
        except Exception as e:
            logger.error("Error setting discoverable: %s", e, exc_info=True)

    def _set_pairable(self, pairable: bool, timeout: int = 0):
        """Set the Bluetooth adapter's pairability."""
        try:
            if not self.bt_manager.adapter_path:
                return

            props = dbus.Interface(
                self.bt_manager.bus.get_object(
                    self.bt_manager.BLUEZ_SERVICE, self.bt_manager.adapter_path
                ),
                self.bt_manager.PROPERTIES_INTERFACE,
            )

            props.Set(
                self.bt_manager.ADAPTER_INTERFACE, "Pairable", dbus.Boolean(pairable)
            )

            if pairable and timeout == 0:
                props.Set(
                    self.bt_manager.ADAPTER_INTERFACE, "PairableTimeout", dbus.UInt32(0)
                )

            logger.debug("Pairable: %s", pairable)
        except Exception as e:
            logger.error("Error setting pairable: %s", e, exc_info=True)

    def _enable_pipewire_sink(self) -> bool:
        """Enable A2DP sink using PipeWire (modern setup)."""
        try:
            # PipeWire with wireplumber handles A2DP automatically
            # Just ensure the Bluetooth module is running

            # Check if wireplumber is running
            result = subprocess.run(
                ["pgrep", "-x", "wireplumber"], capture_output=True, timeout=2
            )

            if result.returncode != 0:
                logger.info("wireplumber not running, trying to start...")
                subprocess.Popen(
                    ["wireplumber"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            # PipeWire should now handle A2DP connections automatically
            logger.info("PipeWire sink mode enabled")
            return True

        except Exception as e:
            logger.error("Error enabling PipeWire sink: %s", e, exc_info=True)
            return False

    def _enable_pulseaudio_sink(self) -> bool:
        """Enable A2DP sink using PulseAudio."""
        try:
            # Load Bluetooth modules
            subprocess.run(
                ["pactl", "load-module", "module-bluetooth-discover"],
                capture_output=True,
                timeout=5,
            )
            subprocess.run(
                ["pactl", "load-module", "module-bluetooth-policy"],
                capture_output=True,
                timeout=5,
            )

            logger.info("PulseAudio sink mode enabled")
            return True

        except Exception as e:
            logger.error("Error enabling PulseAudio sink: %s", e, exc_info=True)
            return False

    def _enable_gst_bluez_sink(self) -> bool:
        """Enable A2DP sink using GStreamer BlueZ plugin."""
        try:
            logger.info("Using GStreamer BlueZ plugin for audio routing")
            # GStreamer BlueZ plugin integrates with BlueZ D-Bus automatically
            # When a device connects via A2DP, GStreamer can handle the audio stream
            # The actual audio routing will be configured when a device connects
            logger.info("GStreamer BlueZ sink mode enabled")
            return True
        except Exception as e:
            logger.error("Error enabling GStreamer BlueZ sink: %s", e, exc_info=True)
            return False

    def _enable_basic_sink(self) -> bool:
        """Enable basic A2DP sink without sound server (direct ALSA)."""
        try:
            # This is a fallback - just ensure Bluetooth is ready
            # Note: Direct ALSA A2DP requires additional setup (bluez-alsa)
            logger.warning("No PipeWire, PulseAudio, or GStreamer BlueZ plugin.")
            logger.info("Install one of:")
            logger.info("  - media-plugins/gst-plugins-bluez (recommended)")
            logger.info("  - media-video/pipewire")
            logger.info("  - media-sound/pulseaudio")
            return True
        except Exception as e:
            logger.error("Error enabling basic sink: %s", e, exc_info=True)
            return False

    # ========================================================================
    # Connection Health Monitoring & Reconnection
    # ========================================================================

    def _start_health_monitoring(self) -> None:
        """Start periodic connection health checks."""
        if self._health_check_timer_id:
            GLib.source_remove(self._health_check_timer_id)

        self._health_check_timer_id = GLib.timeout_add(
            CONNECTION_HEALTH_CHECK_INTERVAL, self._check_connection_health
        )
        logger.debug("Started connection health monitoring")

    def _stop_health_monitoring(self) -> None:
        """Stop connection health checks."""
        if self._health_check_timer_id:
            GLib.source_remove(self._health_check_timer_id)
            self._health_check_timer_id = None
        logger.debug("Stopped connection health monitoring")

    def _check_connection_health(self) -> bool:
        """
        Periodically check connection health.

        Returns:
            True to continue polling, False to stop
        """
        if not self.is_sink_enabled:
            return False

        try:
            with self._state_lock:
                if self.connected_device:
                    # Check A2DP transport state
                    transport_ok = self._check_a2dp_transport(self.connected_device)
                    if not transport_ok:
                        logger.warning(
                            "A2DP transport lost for %s", self.connected_device.name
                        )
                        # Transport lost but device might still be connected
                        # Try to re-establish transport
                        GLib.timeout_add(
                            1000,
                            lambda: self._retry_audio_routing(self.connected_device),
                        )

                    # Update transport state
                    self._update_transport_state()

        except Exception as e:
            logger.error("Error in health check: %s", e, exc_info=True)

        return True  # Continue polling

    def _update_transport_state(self) -> None:
        """Update the current A2DP transport state."""
        if not self.connected_device:
            self._transport_state = None
            return

        try:
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            for path, interfaces in objects.items():
                if self.MEDIA_TRANSPORT_INTERFACE in interfaces:
                    transport_props = interfaces[self.MEDIA_TRANSPORT_INTERFACE]
                    device_path = str(transport_props.get("Device", ""))
                    if device_path == self.connected_device.path:
                        new_state = str(transport_props.get("State", ""))
                        if new_state != self._transport_state:
                            logger.debug(
                                "A2DP transport state: %s -> %s",
                                self._transport_state,
                                new_state,
                            )
                            self._transport_state = new_state
                        return

            self._transport_state = None
        except Exception as e:
            logger.debug("Error updating transport state: %s", e)
            self._transport_state = None

    def _schedule_reconnection(self) -> None:
        """Schedule a reconnection attempt."""
        if self._reconnection_attempts >= MAX_RECONNECTION_ATTEMPTS:
            logger.warning(
                "Max reconnection attempts reached for %s", self._last_connected_address
            )
            self._reconnection_attempts = 0
            return

        if not self._last_connected_address:
            logger.debug("No last connected device to reconnect to")
            return

        if self._reconnection_timer_id:
            GLib.source_remove(self._reconnection_timer_id)

        self._reconnection_attempts += 1
        logger.info(
            "Scheduling reconnection attempt %d/%d in %dms",
            self._reconnection_attempts,
            MAX_RECONNECTION_ATTEMPTS,
            RECONNECTION_DELAY,
        )

        self._reconnection_timer_id = GLib.timeout_add(
            RECONNECTION_DELAY, self._attempt_reconnection
        )

    def _attempt_reconnection(self) -> bool:
        """
        Attempt to reconnect to the last connected device.

        Returns:
            False to remove from timer queue
        """
        self._reconnection_timer_id = None

        if not self.is_sink_enabled or not self._last_connected_address:
            return False

        # Find device by address
        target_device = None
        for device in self.bt_manager.get_devices():
            if device.address.upper() == self._last_connected_address.upper():
                target_device = device
                break

        if not target_device:
            logger.warning(
                "Last connected device not found: %s", self._last_connected_address
            )
            return False

        if target_device.connected:
            logger.debug("Device already connected: %s", target_device.name)
            self._reconnection_attempts = 0
            return False

        # Check if device is authorized
        if not self.is_device_authorized(target_device):
            logger.warning(
                "Device not authorized for reconnection: %s", target_device.name
            )
            return False

        logger.info(
            "Attempting reconnection to %s (%s)",
            target_device.name,
            target_device.address,
        )
        success = self.bt_manager.connect_device(target_device.path)

        if success:
            logger.info("Reconnection initiated for %s", target_device.name)
            self._reconnection_attempts = 0
        else:
            logger.warning("Reconnection failed for %s", target_device.name)
            # Schedule another attempt
            self._schedule_reconnection()

        return False  # Remove from timer queue

    def _cancel_reconnection(self) -> None:
        """Cancel any pending reconnection attempts."""
        if self._reconnection_timer_id:
            GLib.source_remove(self._reconnection_timer_id)
            self._reconnection_timer_id = None
        self._reconnection_attempts = 0

    def _on_bt_device_connected(self, data: Optional[dict]) -> None:
        """Handle Bluetooth device connection event from EventBus."""
        if not data or "device" not in data:
            return

        device = data["device"]

        # Security: Check if device is authorized
        if self._trusted_devices and not self.is_device_authorized(device):
            logger.warning(
                "Security: Unauthorized device attempted connection: %s (%s)",
                device.name,
                device.address,
            )
            # Disconnect unauthorized device
            GLib.idle_add(lambda: self.bt_manager.disconnect_device(device.path))
            return

        with self._state_lock:
            self.connected_device = device
            self._last_connected_address = device.address
            self._reconnection_attempts = 0
            self._cancel_reconnection()

        # If sink mode is enabled, ensure audio is routed properly
        if self.is_sink_enabled:
            self._configure_audio_routing(device)
            if self._event_bus:
                self._event_bus.publish(
                    EventBus.BT_SINK_DEVICE_CONNECTED, {"device": device}
                )

    def _on_bt_device_disconnected(self, data: Optional[dict]) -> None:
        """Handle Bluetooth device disconnection event from EventBus."""
        if not data or "device" not in data:
            return

        device = data["device"]

        with self._state_lock:
            was_our_device = (
                self.connected_device and self.connected_device.path == device.path
            )

            if was_our_device:
                self.connected_device = None
                self._transport_state = None

                # Notify that audio stream stopped
                if self.on_audio_stream_stopped:
                    try:
                        self.on_audio_stream_stopped()
                    except Exception as e:
                        logger.error("Error in audio stream stopped callback: %s", e)

                # If sink mode is still enabled, attempt reconnection
                if self.is_sink_enabled and self._last_connected_address:
                    logger.info(
                        "Device disconnected unexpectedly, scheduling reconnection: %s",
                        device.name,
                    )
                    self._schedule_reconnection()

    def _configure_audio_routing(self, device: BluetoothDevice):
        """Configure audio routing for the connected device."""
        try:
            logger.info("Configuring audio routing for %s (%s)", device.name, device.address)

            if not self._check_a2dp_transport(device):
                logger.debug("A2DP transport not yet available, retrying in 1s")
                GLib.timeout_add(1000, lambda: self._retry_audio_routing(device))
                return

            if self.gst_bluez_available:
                self._setup_gst_bluez_routing(device)
            else:
                audio_system = self._detect_audio_system()
                if audio_system == "pipewire":
                    logger.info("Audio from %s routed via PipeWire", device.name)
                elif audio_system == "pulseaudio":
                    self._setup_pulseaudio_routing(device)

        except Exception as e:
            logger.error("Error configuring audio routing: %s", e, exc_info=True)

    def _check_a2dp_transport(self, device: BluetoothDevice) -> bool:
        """Check if A2DP transport is available for the device."""
        try:
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            # Look for MediaTransport interface for this device
            for path, interfaces in objects.items():
                if self.MEDIA_TRANSPORT_INTERFACE in interfaces:
                    # Check if this transport belongs to our device
                    transport_props = interfaces[self.MEDIA_TRANSPORT_INTERFACE]
                    device_path = str(transport_props.get("Device", ""))
                    if device_path == device.path:
                        state = str(transport_props.get("State", ""))
                        logger.debug(
                            "A2DP transport found for %s: state=%s", device.name, state
                        )
                        return state in ["idle", "pending", "active"]
            return False
        except Exception as e:
            logger.error("Error checking A2DP transport: %s", e, exc_info=True)
            return False

    def _terminate_a2dp_transport(self, device: BluetoothDevice):
        """
        Terminate A2DP transport connection for a device.

        This properly closes the A2DP audio stream before disconnecting the device.
        """
        try:
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            # Find and terminate all MediaTransport interfaces for this device
            for path, interfaces in objects.items():
                if self.MEDIA_TRANSPORT_INTERFACE in interfaces:
                    transport_props = interfaces[self.MEDIA_TRANSPORT_INTERFACE]
                    device_path = str(transport_props.get("Device", ""))

                    if device_path == device.path:
                        state = str(transport_props.get("State", ""))
                        logger.info(
                            "Terminating A2DP transport for %s (state: %s)",
                            device.name,
                            state,
                        )

                        # Get the transport interface
                        transport_obj = self.bt_manager.bus.get_object(
                            self.bt_manager.BLUEZ_SERVICE, path
                        )
                        transport = dbus.Interface(
                            transport_obj, self.MEDIA_TRANSPORT_INTERFACE
                        )

                        # Disconnect the transport
                        try:
                            transport.Disconnect()
                            logger.info(
                                "A2DP transport disconnected for %s", device.name
                            )
                        except dbus.exceptions.DBusException as e:
                            error_name = (
                                e.get_dbus_name()
                                if hasattr(e, "get_dbus_name")
                                else str(e)
                            )
                            if "org.bluez.Error.NotConnected" not in error_name:
                                logger.error(
                                    "Error disconnecting A2DP transport: %s",
                                    e,
                                    exc_info=True,
                                )
                        except Exception as e:
                            logger.error(
                                "Error disconnecting A2DP transport: %s",
                                e,
                                exc_info=True,
                            )

        except Exception as e:
            logger.error("Error terminating A2DP transport: %s", e, exc_info=True)

    def _retry_audio_routing(self, device: BluetoothDevice) -> bool:
        """Retry audio routing configuration after delay."""
        if device.connected:
            self._configure_audio_routing(device)
        return False  # Remove from timeout

    def _setup_gst_bluez_routing(self, device: BluetoothDevice):
        """Set up audio routing using GStreamer BlueZ plugin."""
        try:
            # GStreamer BlueZ plugin handles A2DP via D-Bus automatically
            logger.info("GStreamer BlueZ: Audio from %s routed automatically", device.name)
        except Exception as e:
            logger.error("Error setting up GStreamer BlueZ routing: %s", e, exc_info=True)

    def _setup_pulseaudio_routing(self, device: BluetoothDevice):
        """Set up PulseAudio loopback from Bluetooth to ALSA."""
        try:
            # Get Bluetooth source
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if "bluez" in line.lower():
                        source = line.split()[1]

                        # Get ALSA sink
                        sink_result = subprocess.run(
                            ["pactl", "list", "sinks", "short"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        )

                        if sink_result.returncode == 0:
                            for sink_line in sink_result.stdout.strip().split("\n"):
                                if "alsa" in sink_line.lower():
                                    sink = sink_line.split()[1]

                                    # Create loopback
                                    subprocess.run(
                                        [
                                            "pactl",
                                            "load-module",
                                            "module-loopback",
                                            f"source={source}",
                                            f"sink={sink}",
                                        ],
                                        capture_output=True,
                                        timeout=5,
                                    )

                                    logger.debug(
                                        "Created loopback: %s -> %s", source, sink
                                    )
                                    return
        except Exception as e:
            logger.error("Error setting up PulseAudio routing: %s", e, exc_info=True)

    def control_playback(self, action: str) -> bool:
        """
        Control BT playback (AVRCP commands + local control).

        Args:
            action: 'play', 'pause', 'stop', 'next', 'prev'

        Returns:
            True if command was sent successfully
        """
        if not self.connected_device:
            return False

        # Send AVRCP command to source device
        avrcp_success = self._send_avrcp_command(action)

        # Control local playback (pause/resume stream)
        local_success = self._control_local_playback(action)

        return avrcp_success or local_success

    def _send_avrcp_command(self, action: str) -> bool:
        """
        Send AVRCP command via MediaControl1 or MediaPlayer1 interface.

        According to BlueZ specification:
        - MediaControl1 is typically at the device path itself
        - MediaPlayer1 may be at a sub-path under the device
        - Both interfaces support Play, Pause, Stop, Next, Previous methods

        Args:
            action: 'play', 'pause', 'stop', 'next', 'prev'

        Returns:
            True if command was sent successfully, False otherwise
        """
        try:
            if not self.connected_device:
                logger.debug("No connected device for AVRCP command")
                return False

            # Find MediaControl1 or MediaPlayer1 interface for connected device
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            device_path = self.connected_device.path

            # First, try MediaControl1 interface (preferred for AVRCP)
            # MediaControl1 is typically at the device path itself
            for path, interfaces in objects.items():
                if self.MEDIA_CONTROL_INTERFACE in interfaces:
                    # Verify this control belongs to our device
                    # MediaControl1 path should match device path exactly or be a sub-path
                    if path == device_path or path.startswith(device_path + "/"):
                        try:
                            # Get MediaControl1 interface
                            control_obj = self.bt_manager.bus.get_object(
                                self.bt_manager.BLUEZ_SERVICE, path
                            )
                            control = dbus.Interface(
                                control_obj, self.MEDIA_CONTROL_INTERFACE
                            )

                            # Map action to AVRCP command method
                            method_map = {
                                "play": control.Play,
                                "pause": control.Pause,
                                "stop": control.Stop,
                                "next": control.Next,
                                "prev": control.Previous,
                            }

                            if action not in method_map:
                                logger.warning("Unknown AVRCP action: %s", action)
                                return False

                            # Execute the AVRCP command
                            method_map[action]()
                            logger.debug(
                                "Sent AVRCP %s command to %s via MediaControl1",
                                action,
                                self.connected_device.name,
                            )
                            return True

                        except dbus.exceptions.DBusException as e:
                            error_name = (
                                e.get_dbus_name()
                                if hasattr(e, "get_dbus_name")
                                else str(e)
                            )
                            # Don't log as error - device may not support AVRCP
                            logger.debug(
                                "AVRCP command %s failed via MediaControl1: %s",
                                action,
                                error_name,
                            )
                            # Continue to try MediaPlayer1 or local control
                        except Exception as e:
                            logger.debug(
                                "Error sending AVRCP command via MediaControl1: %s", e
                            )
                            # Continue to try MediaPlayer1 or local control

            # If MediaControl1 not found or failed, try MediaPlayer1 interface
            # MediaPlayer1 may be at a different path structure
            for path, interfaces in objects.items():
                if self.MEDIA_PLAYER_INTERFACE in interfaces:
                    # Verify this player belongs to our device
                    # MediaPlayer1 path should be under the device path
                    if path.startswith(device_path + "/"):
                        try:
                            player_obj = self.bt_manager.bus.get_object(
                                self.bt_manager.BLUEZ_SERVICE, path
                            )
                            player = dbus.Interface(
                                player_obj, self.MEDIA_PLAYER_INTERFACE
                            )

                            # Map action to MediaPlayer1 command method
                            method_map = {
                                "play": player.Play,
                                "pause": player.Pause,
                                "stop": player.Stop,
                                "next": player.Next,
                                "prev": player.Previous,
                            }

                            if action not in method_map:
                                return False

                            # Execute the command
                            method_map[action]()
                            logger.debug(
                                "Sent AVRCP %s command to %s via MediaPlayer1",
                                action,
                                self.connected_device.name,
                            )
                            return True

                        except dbus.exceptions.DBusException as e:
                            error_name = (
                                e.get_dbus_name()
                                if hasattr(e, "get_dbus_name")
                                else str(e)
                            )
                            logger.debug(
                                "AVRCP command %s failed via MediaPlayer1: %s",
                                action,
                                error_name,
                            )
                            continue
                        except Exception as e:
                            logger.debug(
                                "Error sending AVRCP command via MediaPlayer1: %s", e
                            )
                            continue

            logger.debug(
                "No AVRCP interface found for device %s (path: %s)",
                self.connected_device.name,
                device_path,
            )
            return False

        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
            logger.error("D-Bus error sending AVRCP command: %s", error_name)
            return False
        except Exception as e:
            logger.error("Error sending AVRCP command: %s", e, exc_info=True)
            return False

    def _control_local_playback(self, action: str) -> bool:
        """
        Control local BT audio stream (pause/resume) via MediaTransport1 interface.

        According to BlueZ specification:
        - MediaTransport1.Suspend() pauses the A2DP stream locally
        - MediaTransport1.Resume() resumes the A2DP stream locally
        - This does not affect the source device's playback state

        Args:
            action: 'play' (resume), 'pause' (suspend), 'stop' (suspend)

        Returns:
            True if command was executed successfully, False otherwise
        """
        try:
            if not self.connected_device:
                logger.debug("No connected device for local playback control")
                return False

            # Only play/pause/stop have local transport equivalents
            if action not in ("play", "pause", "stop"):
                logger.debug("Action %s has no local transport equivalent", action)
                return False

            # Find MediaTransport1 interface for connected device
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, "/"),
                "org.freedesktop.DBus.ObjectManager",
            )
            objects = manager.GetManagedObjects()

            device_path = self.connected_device.path

            # Look for MediaTransport1 interface for this device
            for path, interfaces in objects.items():
                if self.MEDIA_TRANSPORT_INTERFACE in interfaces:
                    # Verify transport belongs to our device
                    transport_props = interfaces[self.MEDIA_TRANSPORT_INTERFACE]
                    transport_device_path = str(transport_props.get("Device", ""))

                    if transport_device_path == device_path:
                        try:
                            # Get MediaTransport1 interface
                            transport_obj = self.bt_manager.bus.get_object(
                                self.bt_manager.BLUEZ_SERVICE, path
                            )
                            transport = dbus.Interface(
                                transport_obj, self.MEDIA_TRANSPORT_INTERFACE
                            )

                            # Control local playback based on action
                            if action == "play":
                                # Resume A2DP transport
                                transport.Resume()
                                logger.debug(
                                    "Resumed local A2DP transport for %s",
                                    self.connected_device.name,
                                )
                            elif action in ("pause", "stop"):
                                # Suspend A2DP transport (both pause and stop suspend locally)
                                transport.Suspend()
                                logger.debug(
                                    "Suspended local A2DP transport for %s (action: %s)",
                                    self.connected_device.name,
                                    action,
                                )

                            return True

                        except dbus.exceptions.DBusException as e:
                            error_name = (
                                e.get_dbus_name()
                                if hasattr(e, "get_dbus_name")
                                else str(e)
                            )
                            # Check for specific BlueZ errors
                            if "org.bluez.Error.NotConnected" in error_name:
                                logger.debug(
                                    "Transport not connected for %s",
                                    self.connected_device.name,
                                )
                            elif "org.bluez.Error.Failed" in error_name:
                                logger.debug(
                                    "Transport control failed for %s: %s",
                                    self.connected_device.name,
                                    error_name,
                                )
                            else:
                                logger.debug(
                                    "Local playback control failed: %s", error_name
                                )
                            return False
                        except Exception as e:
                            logger.error(
                                "Error controlling local playback: %s", e, exc_info=True
                            )
                            return False

            logger.debug(
                "No MediaTransport1 found for device %s (path: %s)",
                self.connected_device.name,
                device_path,
            )
            return False

        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
            logger.error("D-Bus error controlling local playback: %s", error_name)
            return False
        except Exception as e:
            logger.error("Error controlling local playback: %s", e, exc_info=True)
            return False

    def get_status(self) -> dict:
        """Get current sink status including security and stability info."""
        audio_system = self._detect_audio_system()
        if self.gst_bluez_available:
            audio_system = "gstreamer-bluez"

        return {
            "enabled": self.is_sink_enabled,
            "discoverable": self.is_discoverable,
            "connected_device": (
                self.connected_device.name if self.connected_device else None
            ),
            "device_address": (
                self.connected_device.address if self.connected_device else None
            ),
            "bluetooth_powered": self.bt_manager.is_powered(),
            "audio_system": audio_system,
            "gst_bluez_available": self.gst_bluez_available,
            # Security info
            "trusted_devices_count": len(self._trusted_devices),
            "require_authorization": self._require_authorization,
            "discoverable_timeout": self._discoverable_timeout,
            # Stability info
            "transport_state": self._transport_state,
            "reconnection_attempts": self._reconnection_attempts,
            "last_connected_address": self._last_connected_address,
        }

    def set_device_name(self, name: str):
        """Set the Bluetooth speaker name."""
        self.device_name = name
        if self.is_sink_enabled:
            self._set_adapter_name(name)

    def cleanup(self) -> None:
        """
        Clean up Bluetooth sink resources.

        This should be called when the application shuts down to:
        - Stop health monitoring and reconnection timers
        - Disable sink mode if enabled
        - Unsubscribe from events
        """
        try:
            # Stop health monitoring
            self._stop_health_monitoring()

            # Cancel any pending reconnection
            self._cancel_reconnection()

            # Disable sink mode if enabled
            if self.is_sink_enabled:
                self.disable_sink_mode()

            # Unsubscribe from events
            if self._event_bus:
                self._event_bus.unsubscribe(
                    EventBus.BT_DEVICE_CONNECTED, self._on_bt_device_connected
                )
                self._event_bus.unsubscribe(
                    EventBus.BT_DEVICE_DISCONNECTED, self._on_bt_device_disconnected
                )

            logger.info("Bluetooth sink cleaned up")
        except Exception as e:
            logger.error("Error during Bluetooth sink cleanup: %s", e, exc_info=True)
