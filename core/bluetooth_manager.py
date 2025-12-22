"""Bluetooth device management using D-Bus and BlueZ."""

from typing import List, Dict, Optional, Callable
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from core.bluetooth_agent import BluetoothAgent, BluetoothAgentUI
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib


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
            print(f"Error setting up Bluetooth adapter: {e}")
    
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
            
            print("Bluetooth pairing agent set up successfully")
            if not self.adapter_path:
                print("Note: Adapter path not yet available, agent registered with default path")
        except Exception as e:
            print(f"Error setting up Bluetooth agent: {e}")
            import traceback
            traceback.print_exc()
            print("Pairing confirmations may not work properly")
    
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
            print(f"Error setting up Bluetooth signals: {e}")
    
    def _on_properties_changed(self, interface, changed, invalidated, path):
        """Handle property changes on devices."""
        if interface == self.DEVICE_INTERFACE:
            device_path = str(path)
            if device_path in self.devices:
                device = self.devices[device_path]
                old_connected = device.connected
                old_paired = device.paired
                
                # Update Connected state
                if 'Connected' in changed:
                    device.connected = bool(changed['Connected'])
                    device.properties['Connected'] = device.connected
                    
                    if device.connected and not old_connected:
                        self.connected_device = device
                        if self.on_device_connected:
                            self.on_device_connected(device)
                    elif not device.connected and old_connected:
                        if self.connected_device == device:
                            self.connected_device = None
                        if self.on_device_disconnected:
                            self.on_device_disconnected(device)
                
                # Update Paired state
                if 'Paired' in changed:
                    device.paired = bool(changed['Paired'])
                    device.properties['Paired'] = device.paired
                    
                    # Trust device after successful pairing (Bluetooth best practice)
                    if device.paired and not old_paired:
                        self._trust_device(device_path)
                        # After pairing and trusting, try to connect if not already connected
                        # This is important for A2DP sink mode - device needs to connect to stream audio
                        if not device.connected:
                            # Use GLib.idle_add to avoid blocking the signal handler
                            GLib.idle_add(self._auto_connect_after_pairing, device_path)
                
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
            print(f"Error refreshing Bluetooth devices: {e}")
    
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
            print(f"Error checking adapter power state: {e}")
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
            print(f"Error setting adapter power: {e}")
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
                print(f"Error starting discovery: {e}")
            return True
        except Exception as e:
            print(f"Error starting discovery: {e}")
            return False
    
    def stop_discovery(self) -> bool:
        """Stop Bluetooth device discovery."""
        if not self.adapter_proxy:
            return False
        
        try:
            self.adapter_proxy.StopDiscovery()
            return True
        except Exception as e:
            print(f"Error stopping discovery: {e}")
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
                print(f"Device {device_path} is already paired")
                return True  # Already paired is not an error
            elif 'org.bluez.Error.AuthenticationCanceled' in error_name:
                print(f"Pairing canceled by user")
            elif 'org.bluez.Error.AuthenticationFailed' in error_name:
                print(f"Pairing failed: authentication error")
            elif 'org.bluez.Error.AuthenticationTimeout' in error_name:
                print(f"Pairing failed: timeout")
            else:
                print(f"Error pairing device: {e}")
            return False
        except Exception as e:
            print(f"Error pairing device: {e}")
            return False
    
    def connect_device(self, device_path: str) -> bool:
        """
        Connect to a Bluetooth device.
        
        According to BlueZ specification:
        - Device should be paired before connecting
        - Raises org.bluez.Error.Failed if connection fails
        - Raises org.bluez.Error.AlreadyConnected if already connected
        - Raises org.bluez.Error.NotReady if adapter not ready
        """
        try:
            device = self.devices.get(device_path)
            device_name = device.name if device else "unknown"
            print(f"Attempting to connect device: {device_name} ({device_path})")
            print(f"  Paired: {device.paired if device else 'unknown'}")
            print(f"  Trusted: {device.trusted if device else 'unknown'}")
            print(f"  Currently connected: {device.connected if device else 'unknown'}")
            
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Connect()
            print(f"Connect() call succeeded for {device_name}")
            print("Note: Connection may take a few seconds to establish...")
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            error_msg = str(e)
            print(f"DBus error connecting device: {error_name}")
            print(f"  Error message: {error_msg}")
            
            if 'org.bluez.Error.AlreadyConnected' in error_name:
                print(f"Device {device_path} is already connected")
                return True  # Already connected is not an error
            elif 'org.bluez.Error.Failed' in error_name:
                print(f"Connection failed: {e}")
                print("  This might mean:")
                print("  - Device is not in range")
                print("  - Device rejected the connection")
                print("  - A2DP profile is not available")
            elif 'org.bluez.Error.NotReady' in error_name:
                print(f"Bluetooth adapter not ready")
            elif 'org.bluez.Error.InProgress' in error_name:
                print(f"Connection already in progress")
                return True  # In progress is okay
            else:
                print(f"Unknown error connecting device: {e}")
            return False
        except Exception as e:
            print(f"Exception connecting device: {e}")
            import traceback
            traceback.print_exc()
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
                print(f"Device {device_path} is not connected")
                return True  # Not connected is not an error for disconnect
            elif 'org.bluez.Error.Failed' in error_name:
                print(f"Disconnection failed: {e}")
            else:
                print(f"Error disconnecting device: {e}")
            return False
        except Exception as e:
            print(f"Error disconnecting device: {e}")
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
                print(f"Device {device_path} does not exist")
            else:
                print(f"Error removing device: {e}")
            return False
        except Exception as e:
            print(f"Error removing device: {e}")
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
            print(f"Device {device_path} marked as trusted")
            return True
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, 'get_dbus_name') else str(e)
            if 'org.bluez.Error.DoesNotExist' not in error_name:
                print(f"Error trusting device: {e}")
            return False
        except Exception as e:
            print(f"Error trusting device: {e}")
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
                print(f"Auto-connecting device {device.name} ({device.address}) after pairing...")
                # Small delay to ensure trust is set and device is ready
                GLib.timeout_add(500, lambda: self._do_auto_connect(device_path))
        except Exception as e:
            print(f"Error scheduling auto-connect after pairing: {e}")
        return False  # Remove from idle queue
    
    def _do_auto_connect(self, device_path: str) -> bool:
        """Actually perform the auto-connect (called after delay)."""
        try:
            device = self.devices.get(device_path)
            if device and device.paired and not device.connected:
                print(f"Connecting device {device.name}...")
                success = self.connect_device(device_path)
                if success:
                    print(f"Successfully connected {device.name}")
                else:
                    print(f"Failed to connect {device.name} - it may connect automatically later")
            return False  # Remove from timeout
        except Exception as e:
            print(f"Error in auto-connect: {e}")
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
                except:
                    pass
            self._signal_receivers.clear()
            
            # Stop discovery if active
            self.stop_discovery()
            
            print("Bluetooth manager cleaned up")
        except Exception as e:
            print(f"Error during Bluetooth cleanup: {e}")

