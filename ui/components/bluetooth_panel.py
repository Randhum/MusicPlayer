"""Bluetooth panel component - shows BT status and controls."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GObject, GLib
from typing import Optional
from core.bluetooth_manager import BluetoothDevice, BluetoothManager


class BluetoothPanel(Gtk.Box):
    """Component for Bluetooth status and device management."""
    
    __gsignals__ = {
        'device-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(self, bt_manager: BluetoothManager):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.bt_manager = bt_manager
        
        # Status indicator
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        self.status_icon = Gtk.Image.new_from_icon_name("bluetooth-disabled-symbolic")
        status_box.append(self.status_icon)
        
        self.status_label = Gtk.Label(label="Bluetooth")
        status_box.append(self.status_label)
        
        self.append(status_box)
        
        # Device list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_size_request(-1, 150)
        
        self.device_store = Gtk.ListStore(str, str, bool)  # path, name, connected
        self.device_view = Gtk.TreeView(model=self.device_store)
        self.device_view.set_headers_visible(False)
        self.device_view.connect('row-activated', self._on_device_activated)
        
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Devices", renderer, text=1)
        self.device_view.append_column(column)
        
        scrolled.set_child(self.device_view)
        self.append(scrolled)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        self.scan_button = Gtk.Button(label="Scan")
        self.scan_button.connect('clicked', self._on_scan_clicked)
        button_box.append(self.scan_button)
        
        self.connect_button = Gtk.Button(label="Connect")
        self.connect_button.connect('clicked', self._on_connect_clicked)
        button_box.append(self.connect_button)
        
        self.append(button_box)
        
        # Setup callbacks
        self.bt_manager.on_device_connected = self._on_device_connected
        self.bt_manager.on_device_disconnected = self._on_device_disconnected
        self.bt_manager.on_device_added = self._on_device_added
        
        self._update_status()
        self._refresh_devices()
    
    def _update_status(self):
        """Update Bluetooth status display."""
        powered = self.bt_manager.is_powered()
        connected = self.bt_manager.get_connected_device() is not None
        
        if connected:
            device = self.bt_manager.get_connected_device()
            self.status_label.set_text(f"Connected: {device.name}")
            self.status_icon.set_from_icon_name("bluetooth-active-symbolic")
        elif powered:
            self.status_label.set_text("Bluetooth On")
            self.status_icon.set_from_icon_name("bluetooth-symbolic")
        else:
            self.status_label.set_text("Bluetooth Off")
            self.status_icon.set_from_icon_name("bluetooth-disabled-symbolic")
    
    def _refresh_devices(self):
        """Refresh the device list."""
        self.device_store.clear()
        devices = self.bt_manager.get_devices()
        for device in devices:
            self.device_store.append([device.path, device.name, device.connected])
        self._update_status()
    
    def _on_device_activated(self, tree_view, path, column):
        """Handle device selection."""
        model = tree_view.get_model()
        tree_iter = model.get_iter(path)
        if tree_iter:
            device_path = model.get_value(tree_iter, 0)
            self.emit('device-selected', device_path)
    
    def _on_scan_clicked(self, button):
        """Handle scan button click."""
        if self.bt_manager.is_powered():
            self.bt_manager.start_discovery()
            # Stop discovery after 10 seconds
            GLib.timeout_add_seconds(10, lambda: self.bt_manager.stop_discovery() or False)
            self._refresh_devices()
        else:
            self.bt_manager.set_powered(True)
            self._update_status()
    
    def _on_connect_clicked(self, button):
        """Handle connect button click."""
        selection = self.device_view.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter:
            device_path = model.get_value(tree_iter, 0)
            device = None
            for d in self.bt_manager.get_devices():
                if d.path == device_path:
                    device = d
                    break
            
            if device:
                if device.connected:
                    self.bt_manager.disconnect_device(device_path)
                else:
                    if not device.paired:
                        self.bt_manager.pair_device(device_path)
                    self.bt_manager.connect_device(device_path)
                self._refresh_devices()
    
    def _on_device_connected(self, device: BluetoothDevice):
        """Handle device connection."""
        self._update_status()
        self._refresh_devices()
    
    def _on_device_disconnected(self, device: BluetoothDevice):
        """Handle device disconnection."""
        self._update_status()
        self._refresh_devices()
    
    def _on_device_added(self, device: BluetoothDevice):
        """Handle new device added."""
        self._refresh_devices()

