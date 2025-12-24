"""Bluetooth device management using D-Bus and BlueZ."""

from typing import List, Dict, Optional, Callable

import dbus
from dbus.mainloop.glib import DBusGMainLoop
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib

from core.bluetooth_agent import BluetoothAgent, BluetoothAgentUI
from core.logging import get_logger

logger = get_logger(__name__)


class BluetoothDevice:
    """Represents a Bluetooth device."""
    
    def __init__(self, path: str, properties: Dict):
        self.path = path
        self.address = properties.get('Address', '')
        self.name = properties.get('Name', 'Unknown Device')
        self.connected = properties.get('Connected', False)
        self.paired = properties.get('Paired', False)
        self.trusted = properties.get('Trusted', False)
        self.icon = properties.get('Icon', '')
        self.properties = properties
    
    def __repr__(self):
        return f"BluetoothDevice(name={self.name}, address={self.address}, connected={self.connected})"


class BluetoothManager:
    """Manages Bluetooth devices and connections using D-Bus."""
    
    BLUEZ_SERVICE = 'org.bluez'
    BLUEZ_OBJECT_PATH = '/org/bluez'
    ADAPTER_INTERFACE = 'org.bluez.Adapter1'
    DEVICE_INTERFACE = 'org.bluez.Device1'
    PROPERTIES_INTERFACE = 'org.freedesktop.DBus.Properties'
    
    def __init__(self, parent_window=None):
        """
        Initialize Bluetooth Manager.
        
        Args:
            parent_window: GTK window for pairing dialogs (optional)
        """
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.adapter_path: Optional[str] = None
        self.adapter_proxy: Optional[dbus.Interface] = None
        self.devices: Dict[str, BluetoothDevice] = {}
        self.connected_device: Optional[BluetoothDevice] = None
        
        # Callbacks
        self.on_device_connected: Optional[Callable] = None
        self.on_device_disconnected: Optional[Callable] = None
        self.on_device_added: Optional[Callable] = None
        self.on_device_removed: Optional[Callable] = None
        
        # Setup agent for pairing confirmations
        self.agent: Optional[BluetoothAgent] = None
        self.agent_ui: Optional[BluetoothAgentUI] = None
        self.parent_window = parent_window
        
        # Callback to check if sink mode is enabled (set by BluetoothSink)
        self._sink_mode_checker: Optional[Callable[[], bool]] = None
        
        # Track signal receivers for cleanup
        self._signal_receivers = []
        
        self._setup_adapter()
        self._setup_agent()
        self._setup_signals()
        self._refresh_devices()
    
    def _setup_adapter(self):
        """Set up the Bluetooth adapter."""
        try:
            # Get the default adapter
            manager = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, '/'),
                'org.freedesktop.DBus.ObjectManager'
            )
            
            objects = manager.GetManagedObjects()
            for path, interfaces in objects.items():
                if self.ADAPTER_INTERFACE in interfaces:
                    self.adapter_path = path
                    break
            
            if self.adapter_path:
                adapter_obj = self.bus.get_object(self.BLUEZ_SERVICE, self.adapter_path)
                self.adapter_proxy = dbus.Interface(adapter_obj, self.ADAPTER_INTERFACE)
        except Exception as e:
            logger.error("Error setting up Bluetooth adapter: %s", e, exc_info=True)
    
    def _setup_agent(self):
        """Set up the Bluetooth Agent for handling pairing confirmations."""
        try:
            # Create UI handler for pairing dialogs first
            self.agent_ui = BluetoothAgentUI(self.parent_window)
            
            # Create and register the agent (adapter_path may be None initially)
            # The agent will still register, but we'll update it if adapter is found later
            adapter_path = self.adapter_path or '/org/bluez/hci0'  # Default adapter path
            self.agent = BluetoothAgent(self.bus, adapter_path)
            
            # Set up agent callbacks to use UI - this must be done immediately
            # so callbacks are available when pairing requests arrive
            self.agent.on_passkey_display = self.agent_ui.show_passkey_display
            self.agent.on_passkey_confirm = self.agent_ui.show_passkey_confirmation
            self.agent.on_passkey_request = self._handle_passkey_request
            self.agent.on_authorization_request = self.agent_ui.show_authorization_request
            self.agent.on_pin_request = self.agent_ui.show_pin_request
            
            logger.info("Bluetooth pairing agent set up successfully")
            if not self.adapter_path:
                logger.warning("Adapter path not yet available, agent registered with default path")
        except Exception as e:
            logger.error("Error setting up Bluetooth agent: %s", e, exc_info=True)
            logger.warning("Pairing confirmations may not work properly")
    
    def _handle_passkey_request(self, device_name: str) -> Optional[int]:
        """
        Handle passkey request - show dialog to enter passkey.
        
        Args:
            device_name: Name of the device requesting passkey
            
        Returns:
            Passkey as integer, or None if cancelled
        """
        if not self.agent_ui:
            return None
        
        # For passkey requests, we typically need to display what the other device shows
        # But if we need to enter one, show a dialog
        dialog = Gtk.Dialog(
            title=f"Pairing with {device_name}",
            transient_for=self.parent_window,
            modal=True
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_OK", Gtk.ResponseType.OK
        )
        
        content = dialog.get_content_area()
        label = Gtk.Label(label=f"Enter the 6-digit passkey shown on {device_name}:")
        content.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("000000")
        entry.set_max_length(6)
        entry.set_activates_default(True)
        content.append(entry)
        
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry.grab_focus()
        
        # GTK4: Use response signal instead of run()
        from gi.repository import GLib
        response_received = {'value': None}
        
        def on_response(dialog, response_id):
            response_received['value'] = response_id
            dialog.close()
        
        dialog.connect('response', on_response)
        dialog.present()
        
        # Wait for response using main loop
        while response_received['value'] is None:
            GLib.MainContext.default().iteration(True)
        
        response = response_received['value']
        passkey_str = entry.get_text() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        
        if passkey_str:
            try:
                return int(passkey_str)
            except ValueError:
                return None
        return None
    
    def _setup_signals(self):
        """Set up D-Bus signals for device changes."""
        try:
            # Set up properties changed signal
            receiver = self.bus.add_signal_receiver(
                self._on_properties_changed,
                dbus_interface=self.PROPERTIES_INTERFACE,
                signal_name='PropertiesChanged',
                path_keyword='path'
            )
            self._signal_receivers.append(receiver)
            
            # Set up interfaces added/removed signals
            receiver = self.bus.add_signal_receiver(
                self._on_interfaces_added,
                signal_name='InterfacesAdded',
                bus_name=self.BLUEZ_SERVICE
            )
            self._signal_receivers.append(receiver)
            
            receiver = self.bus.add_signal_receiver(
                self._on_interfaces_removed,
                signal_name='InterfacesRemoved',
                bus_name=self.BLUEZ_SERVICE
            )
            self._signal_receivers.append(receiver)
        except Exception as e:
            logger.error("Error setting up Bluetooth signals: %s", e, exc_info=True)
    
    def _on_properties_changed(self, interface, changed, invalidated, path):
        """Handle property changes on devices."""
        if interface == self.DEVICE_INTERFACE:
            device_path = str(path)
            if device_path in self.devices:
                device = self.devices[device_path]
                old_connected = device.connected
                old_paired = device.paired
                
                # Connected state handling moved above (after Paired state)
                
                # Update Paired state
                if 'Paired' in changed:
                    device.paired = bool(changed['Paired'])
                    device.properties['Paired'] = device.paired
                    
                    # Trust device after successful pairing (Bluetooth best practice)
                    if device.paired and not old_paired:
                        self._trust_device(device_path)
                        # After pairing and trusting, try to connect if not already connected
                        # BUT only if sink mode is enabled (soft-switch behavior)
                        if not device.connected:
                            # Check if sink mode is enabled before auto-connecting
                            if self._is_sink_mode_enabled():
                                # Use GLib.idle_add to avoid blocking the signal handler
                                GLib.idle_add(self._auto_connect_after_pairing, device_path)
                            else:
                                logger.debug("Device %s paired but sink mode is disabled - not auto-connecting", device.name)
                
                # Update Connected state
                if 'Connected' in changed:
                    new_connected = bool(changed['Connected'])
                    device.connected = new_connected
                    device.properties['Connected'] = device.connected
                    
                    # If device connected but sink mode is disabled, disconnect it
                    if new_connected and not old_connected:
                        if not self._is_sink_mode_enabled():
                            logger.info("Device %s connected but sink mode is disabled - disconnecting", device.name)
                            # Disconnect in the next event loop iteration to avoid blocking
                            GLib.idle_add(self._disconnect_if_sink_disabled, device_path)
                            return  # Don't process connection callbacks
                        
                        self.connected_device = device
                        if self.on_device_connected:
                            self.on_device_connected(device)
                    elif not new_connected and old_connected:
                        if self.connected_device == device:
                            self.connected_device = None
                        if self.on_device_disconnected:
                            self.on_device_disconnected(device)
                
                # Update Trusted state
                if 'Trusted' in changed:
                    device.trusted = bool(changed['Trusted'])
                    device.properties['Trusted'] = device.trusted
    
    def _on_interfaces_added(self, path, interfaces):
        """Handle new interfaces (devices) being added."""
        if self.DEVICE_INTERFACE in interfaces:
            self._refresh_devices()
            device_path = str(path)
            device = self.devices.get(device_path)
            if device and self.on_device_added:
                self.on_device_added(device)
    
    def _on_interfaces_removed(self, path, interfaces):
        """Handle interfaces (devices) being removed."""
        if self.DEVICE_INTERFACE in interfaces:
            device_path = str(path)
            if device_path in self.devices:
                device = self.devices[device_path]
                del self.devices[device_path]
                if self.connected_device == device:
                    self.connected_device = None
                if self.on_device_removed:
                    self.on_device_removed(device)
    
    def _convert_dbus_value(self, value):
        """Convert a dbus value to a native Python type."""
        if isinstance(value, dbus.Boolean):
            return bool(value)
        elif isinstance(value, dbus.String):
            return str(value)
        elif isinstance(value, (dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Int16, dbus.Int32, dbus.Int64)):
            return int(value)
        elif isinstance(value, dbus.Double):
            return float(value)
        elif isinstance(value, (list, tuple)):
            return [self._convert_dbus_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._convert_dbus_value(v) for k, v in value.items()}
        else:
            try:
                return str(value)
            except:
                return value
    
    def _refresh_devices(self):
        """Refresh the list of Bluetooth devices."""
        try:
            manager = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, '/'),
                'org.freedesktop.DBus.ObjectManager'
            )
            
            objects = manager.GetManagedObjects()
            self.devices.clear()
            
            for path, interfaces in objects.items():
                if self.DEVICE_INTERFACE in interfaces:
                    properties = interfaces[self.DEVICE_INTERFACE]
                    device_path = str(path)
                    # Convert dbus types to Python types using helper function
                    props_dict = {}
                    for key, value in properties.items():
                        props_dict[key] = self._convert_dbus_value(value)
                    device = BluetoothDevice(device_path, props_dict)
                    self.devices[device_path] = device
                    
                    if device.connected:
                        self.connected_device = device
        except Exception as e:
            logger.error("Error refreshing Bluetooth devices: %s", e, exc_info=True)
    
    def is_powered(self) -> bool:
        """Check if Bluetooth adapter is powered."""
        if not self.adapter_path:
            return False
        
        try:
            props = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, self.adapter_path),
                self.PROPERTIES_INTERFACE
            )
            powered = props.Get(self.ADAPTER_INTERFACE, 'Powered')
            return bool(powered)
        except Exception as e:
            logger.error("Error checking adapter power state: %s", e, exc_info=True)
            return False
    
    def set_powered(self, powered: bool) -> bool:
        """Set Bluetooth adapter power state."""
        if not self.adapter_path:
            return False
        
        try:
            props = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, self.adapter_path),
                self.PROPERTIES_INTERFACE
            )
            props.Set(self.ADAPTER_INTERFACE, 'Powered', dbus.Boolean(powered))
            return True
        except Exception as e:
            logger.error("Error setting adapter power: %s", e, exc_info=True)
            return False
    
    def start_discovery(self) -> bool:
        """Start Bluetooth device discovery."""
        if not self.adapter_proxy:
            return False
        
        try:
            self.adapter_proxy.StartDiscovery()
            return True
        except dbus.exceptions.DBusException as e:
            # Already discovering is not an error
            if 'org.bluez.Error.InProgress' not in str(e):
                logger.warning("Error starting discovery: %s", e)
            return True
        except Exception as e:
            logger.error("Error starting discovery: %s", e, exc_info=True)
            return False
    
    def stop_discovery(self) -> bool:
        """Stop Bluetooth device discovery."""
        if not self.adapter_proxy:
            return False
        
        try:
            self.adapter_proxy.StopDiscovery()
            return True
        except Exception as e:
            logger.error("Error stopping discovery: %s", e, exc_info=True)
            return False
    
    def get_devices(self) -> List[BluetoothDevice]:
        """Get list of all known Bluetooth devices."""
        return list(self.devices.values())
    
    def get_connected_device(self) -> Optional[BluetoothDevice]:
        """Get the currently connected device."""
        return self.connected_device
    
    def pair_device(self, device_path: str) -> bool:
        """
        Pair with a Bluetooth device.
        
        According to BlueZ specification:
        - Raises org.bluez.Error.AlreadyExists if already paired
        - Raises org.bluez.Error.AuthenticationFailed if pairing fails
        - Raises org.bluez.Error.AuthenticationCanceled if user cancels
        - Raises org.bluez.Error.AuthenticationTimeout if timeout
        """
        try:
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Pair()
            # Note: Trusting happens automatically in _on_properties_changed
            # when Paired property changes to True
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if 'org.bluez.Error.AlreadyExists' in error_name:
                logger.info("Device %s is already paired", device_path)
                return True  # Already paired is not an error
            elif 'org.bluez.Error.AuthenticationCanceled' in error_name:
                logger.info("Pairing canceled by user")
            elif 'org.bluez.Error.AuthenticationFailed' in error_name:
                logger.warning("Pairing failed: authentication error")
            elif 'org.bluez.Error.AuthenticationTimeout' in error_name:
                logger.warning("Pairing failed: timeout")
            else:
                logger.error("Error pairing device: %s", e)
            return False
        except Exception as e:
            logger.error("Error pairing device: %s", e, exc_info=True)
            return False
    
    def connect_device(self, device_path: str) -> bool:
        """
        Connect to a Bluetooth device.
        
        According to BlueZ specification:
        - Device should be paired before connecting
        - Raises org.bluez.Error.Failed if connection fails
        - Raises org.bluez.Error.AlreadyConnected if already connected
        - Raises org.bluez.Error.NotReady if adapter not ready
        
        Note: For A2DP sink mode, this will only succeed if sink mode is enabled.
        """
        try:
            device = self.devices.get(device_path)
            device_name = device.name if device else "unknown"
            logger.debug("Attempting to connect device: %s (%s)", device_name, device_path)
            logger.debug("  Paired: %s, Trusted: %s, Connected: %s",
                        device.paired if device else 'unknown',
                        device.trusted if device else 'unknown',
                        device.connected if device else 'unknown')
            
            # Check if sink mode is enabled (soft-switch behavior)
            if not self._is_sink_mode_enabled():
                logger.warning("Connection rejected: Sink mode is disabled")
                logger.info("Enable speaker mode first to allow device connections")
                return False
            
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Connect()
            logger.info("Connect() call succeeded for %s", device_name)
            logger.debug("Connection may take a few seconds to establish...")
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            error_msg = str(e)
            logger.error("DBus error connecting device: %s", error_name)
            logger.debug("  Error message: %s", error_msg)
            
            if 'org.bluez.Error.AlreadyConnected' in error_name:
                logger.info("Device %s is already connected", device_path)
                return True  # Already connected is not an error
            elif 'org.bluez.Error.Failed' in error_name:
                logger.warning("Connection failed: %s", e)
                logger.info("  This might mean:")
                logger.info("  - Device is not in range")
                logger.info("  - Device rejected the connection")
                logger.info("  - A2DP profile is not available")
            elif 'org.bluez.Error.NotReady' in error_name:
                logger.warning("Bluetooth adapter not ready")
            elif 'org.bluez.Error.InProgress' in error_name:
                logger.info("Connection already in progress")
                return True  # In progress is okay
            else:
                logger.error("Unknown error connecting device: %s", e)
            return False
        except Exception as e:
            logger.exception("Exception connecting device: %s", e)
            return False
    
    def disconnect_device(self, device_path: str) -> bool:
        """
        Disconnect from a Bluetooth device.
        
        According to BlueZ specification:
        - Raises org.bluez.Error.NotConnected if not connected
        - Raises org.bluez.Error.Failed if disconnection fails
        """
        try:
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Disconnect()
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if 'org.bluez.Error.NotConnected' in error_name:
                logger.info("Device %s is not connected", device_path)
                return True  # Not connected is not an error for disconnect
            elif 'org.bluez.Error.Failed' in error_name:
                logger.warning("Disconnection failed: %s", e)
            else:
                logger.error("Error disconnecting device: %s", e)
            return False
        except Exception as e:
            logger.error("Error disconnecting device: %s", e, exc_info=True)
            return False
    
    def remove_device(self, device_path: str) -> bool:
        """Remove a Bluetooth device."""
        if not self.adapter_proxy:
            return False
        
        try:
            self.adapter_proxy.RemoveDevice(device_path)
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if 'org.bluez.Error.DoesNotExist' in error_name:
                logger.info("Device %s does not exist", device_path)
            else:
                logger.error("Error removing device: %s", e)
            return False
        except Exception as e:
            logger.error("Error removing device: %s", e, exc_info=True)
            return False
    
    def _trust_device(self, device_path: str) -> bool:
        """
        Mark a device as trusted after successful pairing.
        
        This is a Bluetooth best practice - trusted devices can reconnect
        automatically without user intervention.
        """
        try:
            device_obj = self.bus.get_object(self.BLUEZ_SERVICE, device_path)
            props = dbus.Interface(device_obj, self.PROPERTIES_INTERFACE)
            props.Set(self.DEVICE_INTERFACE, 'Trusted', dbus.Boolean(True))
            logger.info("Device %s marked as trusted", device_path)
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if 'org.bluez.Error.DoesNotExist' not in error_name:
                logger.error("Error trusting device: %s", e)
            return False
        except Exception as e:
            logger.error("Error trusting device: %s", e, exc_info=True)
            return False
    
    def _auto_connect_after_pairing(self, device_path: str) -> bool:
        """
        Automatically connect a device after pairing.
        
        This is called via GLib.idle_add to avoid blocking signal handlers.
        Returns False to remove from idle queue.
        
        In sink mode, this ensures devices connect after pairing so they can
        stream audio via A2DP.
        """
        try:
            device = self.devices.get(device_path)
            if device and device.paired and not device.connected:
                logger.info("Auto-connecting device %s (%s) after pairing...", device.name, device.address)
                # Small delay to ensure trust is set and device is ready
                GLib.timeout_add(500, lambda: self._do_auto_connect(device_path))
        except Exception as e:
            logger.error("Error scheduling auto-connect after pairing: %s", e, exc_info=True)
        return False  # Remove from idle queue
    
    def _do_auto_connect(self, device_path: str) -> bool:
        """Actually perform the auto-connect (called after delay)."""
        try:
            device = self.devices.get(device_path)
            if device and device.paired and not device.connected:
                # Double-check sink mode is still enabled before connecting
                if not self._is_sink_mode_enabled():
                    logger.debug("Sink mode disabled - not connecting %s", device.name)
                    return False
                
                logger.info("Connecting device %s...", device.name)
                success = self.connect_device(device_path)
                if success:
                    logger.info("Successfully connected %s", device.name)
                else:
                    logger.warning("Failed to connect %s - it may connect automatically later", device.name)
            return False  # Remove from timeout
        except Exception as e:
            logger.error("Error in auto-connect: %s", e, exc_info=True)
            return False
    
    def register_sink_mode_checker(self, checker: Callable[[], bool]):
        """
        Register a callback function to check if sink mode is enabled.
        
        This avoids circular dependencies by using a callback instead of
        storing a direct reference to the BluetoothSink instance.
        
        Args:
            checker: Callable that returns True if sink mode is enabled, False otherwise
        """
        self._sink_mode_checker = checker
    
    def _is_sink_mode_enabled(self) -> bool:
        """
        Check if sink mode is enabled via registered callback.
        
        Returns False if no callback is registered.
        """
        if self._sink_mode_checker:
            try:
                return self._sink_mode_checker()
            except Exception as e:
                logger.error("Error checking sink mode: %s", e, exc_info=True)
                return False
        return False
    
    def _disconnect_if_sink_disabled(self, device_path: str) -> bool:
        """Disconnect a device if sink mode is disabled."""
        try:
            if not self._is_sink_mode_enabled():
                device = self.devices.get(device_path)
                if device and device.connected:
                    logger.info("Disconnecting %s - sink mode is disabled", device.name)
                    self.disconnect_device(device_path)
            return False  # Remove from idle queue
        except Exception as e:
            logger.error("Error disconnecting device: %s", e, exc_info=True)
            return False
    
    def cleanup(self):
        """
        Clean up Bluetooth resources.
        
        This should be called when the application shuts down to:
        - Unregister the Bluetooth agent
        - Remove signal receivers
        - Disconnect devices if needed
        """
        try:
            # Unregister agent
            if self.agent:
                self.agent.unregister_agent()
            
            # Remove signal receivers
            for receiver in self._signal_receivers:
                try:
                    self.bus.remove_signal_receiver(receiver)
                except (AttributeError, RuntimeError, dbus.exceptions.DBusException):
                    # Receiver may have already been removed or bus destroyed
                    pass
            self._signal_receivers.clear()
            
            # Stop discovery if active
            self.stop_discovery()
            
            logger.info("Bluetooth manager cleaned up")
        except Exception as e:
            logger.error("Error during Bluetooth cleanup: %s", e, exc_info=True)

