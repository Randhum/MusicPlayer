"""Bluetooth panel component - shows BT status and controls."""

from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GObject, GLib

from core.bluetooth_manager import BluetoothDevice, BluetoothManager
from core.bluetooth_sink import BluetoothSink


class BluetoothPanel(Gtk.Box):
    """Component for Bluetooth status and device management."""
    
    __gsignals__ = {
        'device-selected': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }
    
    def __init__(self, bt_manager: BluetoothManager, bt_sink: Optional[BluetoothSink] = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.bt_manager = bt_manager
        self.bt_sink = bt_sink
        self.sink_toggle: Optional[Gtk.ToggleButton] = None
        self.sink_status: Optional[Gtk.Label] = None
        
        # Status indicator
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        self.status_icon = Gtk.Image.new_from_icon_name("bluetooth-disabled-symbolic")
        status_box.append(self.status_icon)
        
        self.status_label = Gtk.Label(label="Bluetooth")
        status_box.append(self.status_label)
        
        self.append(status_box)
        
        # Device list (read-only, populated only when speaker mode is enabled)
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
        
        # Sink mode toggle
        if self.bt_sink:
            sink_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            sink_box.set_margin_top(5)
            
            self.sink_toggle = Gtk.ToggleButton(label="Enable Speaker Mode")
            self.sink_toggle.connect('toggled', self._on_sink_toggled)
            sink_box.append(self.sink_toggle)
            
            self.sink_status = Gtk.Label(label="")
            sink_box.append(self.sink_status)
            
            self.append(sink_box)
            
            # Setup sink callbacks
            self.bt_sink.on_sink_enabled = self._on_sink_enabled
            self.bt_sink.on_sink_disabled = self._on_sink_disabled
            self.bt_sink.on_device_connected = self._on_sink_device_connected
        
        # Setup callbacks
        self.bt_manager.on_device_connected = self._on_device_connected
        self.bt_manager.on_device_disconnected = self._on_device_disconnected
        self.bt_manager.on_device_added = self._on_device_added
        
        # Start with Bluetooth UI in an inactive state; it becomes active with speaker mode
        self._set_inactive_state()
    
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
    
    def _on_sink_toggled(self, button):
        """Handle sink mode toggle."""
        if not self.bt_sink or not self.sink_status:
            return
        
        if button.get_active():
            # Enable sink mode
            if self.bt_sink.enable_sink_mode():
                self.sink_status.set_text("Speaker mode enabled")
            else:
                button.set_active(False)
                if self.sink_status:
                    self.sink_status.set_text("Failed to enable")
        else:
            # Disable sink mode
            self.bt_sink.disable_sink_mode()
            if self.sink_status:
                self.sink_status.set_text("Speaker mode disabled")
    
    def _on_sink_enabled(self):
        """Handle sink enabled."""
        if self.sink_toggle:
            self.sink_toggle.set_active(True)
        if self.sink_status:
            self.sink_status.set_text("Speaker mode: Ready for connection")
        # When speaker mode is enabled, update BT state and show known devices
        self._refresh_devices()
    
    def _on_sink_disabled(self):
        """Handle sink disabled."""
        if self.sink_toggle:
            self.sink_toggle.set_active(False)
        if self.sink_status:
            self.sink_status.set_text("")
        # When speaker mode is disabled, clear UI back to inactive state
        self._set_inactive_state()
    
    def _on_sink_device_connected(self, device: BluetoothDevice):
        """Handle device connected in sink mode."""
        if self.sink_status:
            self.sink_status.set_text(f"Receiving audio from: {device.name}")
        self._update_status()

    def _set_inactive_state(self):
        """Put the Bluetooth UI into an inactive state until speaker mode is enabled."""
        self.device_store.clear()
        self.status_label.set_text("Speaker mode disabled")
        self.status_icon.set_from_icon_name("bluetooth-disabled-symbolic")

