"""Bluetooth device management using D-Bus and BlueZ."""

from typing import List, Dict, Optional, Callable
import dbus
from dbus.mainloop.glib import DBusGMainLoop


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
    
    def __init__(self):
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
        
        self._setup_adapter()
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
    
    def _setup_signals(self):
        """Set up D-Bus signals for device changes."""
        try:
            # Set up properties changed signal
            self.bus.add_signal_receiver(
                self._on_properties_changed,
                dbus_interface=self.PROPERTIES_INTERFACE,
                signal_name='PropertiesChanged',
                path_keyword='path'
            )
            
            # Set up interfaces added/removed signals
            self.bus.add_signal_receiver(
                self._on_interfaces_added,
                signal_name='InterfacesAdded'
            )
            
            self.bus.add_signal_receiver(
                self._on_interfaces_removed,
                signal_name='InterfacesRemoved'
            )
        except Exception as e:
            print(f"Error setting up Bluetooth signals: {e}")
    
    def _on_properties_changed(self, interface, changed, invalidated, path):
        """Handle property changes on devices."""
        if interface == self.DEVICE_INTERFACE:
            device_path = str(path)
            if device_path in self.devices:
                device = self.devices[device_path]
                old_connected = device.connected
                
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
                    # Convert dbus types to Python types
                    props_dict = {}
                    for key, value in properties.items():
                        if isinstance(value, dbus.Boolean):
                            props_dict[key] = bool(value)
                        elif isinstance(value, (dbus.String, dbus.UTF8String)):
                            props_dict[key] = str(value)
                        else:
                            props_dict[key] = value
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
        """Pair with a Bluetooth device."""
        try:
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Pair()
            return True
        except Exception as e:
            print(f"Error pairing device: {e}")
            return False
    
    def connect_device(self, device_path: str) -> bool:
        """Connect to a Bluetooth device."""
        try:
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Connect()
            return True
        except Exception as e:
            print(f"Error connecting device: {e}")
            return False
    
    def disconnect_device(self, device_path: str) -> bool:
        """Disconnect from a Bluetooth device."""
        try:
            device_proxy = dbus.Interface(
                self.bus.get_object(self.BLUEZ_SERVICE, device_path),
                self.DEVICE_INTERFACE
            )
            device_proxy.Disconnect()
            return True
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
        except Exception as e:
            print(f"Error removing device: {e}")
            return False

