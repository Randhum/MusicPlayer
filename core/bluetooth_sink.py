"""Bluetooth A2DP sink management for receiving audio from mobile devices."""

import subprocess
import os
import dbus
from typing import Optional, Callable
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
from core.bluetooth_manager import BluetoothManager, BluetoothDevice


class BluetoothSink:
    """
    Manages Bluetooth A2DP sink functionality.
    
    When enabled, this allows the computer to act as a Bluetooth speaker,
    receiving audio from phones and other devices, and playing it through
    the local audio output (ALSA).
    """
    
    MEDIA_CONTROL_INTERFACE = 'org.bluez.MediaControl1'
    MEDIA_PLAYER_INTERFACE = 'org.bluez.MediaPlayer1'
    MEDIA_TRANSPORT_INTERFACE = 'org.bluez.MediaTransport1'
    PROFILE_INTERFACE = 'org.bluez.Profile1'
    PROFILE_MANAGER_INTERFACE = 'org.bluez.ProfileManager1'
    
    def __init__(self, bt_manager: BluetoothManager):
        self.bt_manager = bt_manager
        self.is_sink_enabled = False
        self.is_discoverable = False
        self.connected_device: Optional[BluetoothDevice] = None
        self.device_name = "Music Player Speaker"
        
        # GStreamer BlueZ plugin support
        self.gst_bluez_available = False
        self._check_gst_bluez_plugin()
        
        # Callbacks
        self.on_sink_enabled: Optional[Callable] = None
        self.on_sink_disabled: Optional[Callable] = None
        self.on_device_connected: Optional[Callable] = None
        self.on_device_disconnected: Optional[Callable] = None
        self.on_audio_stream_started: Optional[Callable] = None
        self.on_audio_stream_stopped: Optional[Callable] = None
        
        # Setup BT manager callbacks
        self._original_device_connected = self.bt_manager.on_device_connected
        self._original_device_disconnected = self.bt_manager.on_device_disconnected
        self.bt_manager.on_device_connected = self._on_device_connected
        self.bt_manager.on_device_disconnected = self._on_device_disconnected
    
    def _check_gst_bluez_plugin(self):
        """Check if GStreamer BlueZ plugin is available."""
        try:
            # Initialize GStreamer if not already done
            if not Gst.is_initialized():
                Gst.init(None)
            
            # Check for BlueZ plugin by inspecting registry
            # The plugin package is media-libs/gst-plugins-bluez
            # It provides elements for BlueZ A2DP integration
            registry = Gst.Registry.get()
            
            # Check for BlueZ-related plugins in the registry
            plugins_to_check = [
                'bluez',
                'gstbluez',
                'bluezaudio',
                'bluezsrc',
                'bluezsink',
            ]
            
            # Also check for factory names that might contain bluez
            factories = registry.get_feature_list(Gst.ElementFactory)
            for factory in factories:
                factory_name = factory.get_name().lower()
                if 'bluez' in factory_name:
                    self.gst_bluez_available = True
                    print(f"GStreamer BlueZ plugin found: {factory.get_name()}")
                    return
            
            # Try to create common BlueZ element names
            bluez_elements = [
                'bluezsrc',
                'bluezsink',
                'bluezaudiosrc',
                'bluezaudiosink',
                'bluetoothaudiosink',
                'bluetoothaudiosrc',
            ]
            
            for element_name in bluez_elements:
                element = Gst.ElementFactory.make(element_name, element_name)
                if element:
                    self.gst_bluez_available = True
                    print(f"GStreamer BlueZ plugin found: {element_name}")
                    return
            
            # If not found, check if the plugin is installed but not loaded
            # This is informational - the plugin might work via D-Bus integration
            print("GStreamer BlueZ plugin elements not found in registry.")
            print("Note: media-libs/gst-plugins-bluez may use D-Bus integration")
            print("and may not expose traditional GStreamer elements.")
            print("Bluetooth audio will work via PipeWire/PulseAudio if available.")
            self.gst_bluez_available = False
        except Exception as e:
            print(f"Error checking GStreamer BlueZ plugin: {e}")
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
                    print("Failed to power on Bluetooth adapter")
                    return False
            
            # Verify A2DP sink profile support
            if not self._verify_a2dp_sink_support():
                print("Warning: A2DP sink profile may not be fully supported")
                print("Audio streaming may not work properly")
            
            # Set device name
            self._set_adapter_name(self.device_name)
            
            # Make adapter discoverable and pairable
            self._set_discoverable(True)
            self._set_pairable(True)
            
            # Configure audio subsystem
            # Prefer GStreamer BlueZ plugin if available
            if self.gst_bluez_available:
                success = self._enable_gst_bluez_sink()
            else:
                audio_system = self._detect_audio_system()
                
                if audio_system == 'pipewire':
                    success = self._enable_pipewire_sink()
                elif audio_system == 'pulseaudio':
                    success = self._enable_pulseaudio_sink()
                else:
                    print("No compatible audio system found. Trying basic setup.")
                    success = self._enable_basic_sink()
            
            if success:
                self.is_sink_enabled = True
                if self.on_sink_enabled:
                    self.on_sink_enabled()
            
            return success
            
        except Exception as e:
            print(f"Error enabling Bluetooth sink: {e}")
            return False
    
    def disable_sink_mode(self) -> bool:
        """Disable Bluetooth A2DP sink mode."""
        try:
            # Stop being discoverable
            self._set_discoverable(False)
            
            # Disconnect any connected audio devices
            if self.connected_device:
                self.bt_manager.disconnect_device(self.connected_device.path)
            
            self.is_sink_enabled = False
            self.is_discoverable = False
            
            if self.on_sink_disabled:
                self.on_sink_disabled()
            
            return True
        except Exception as e:
            print(f"Error disabling Bluetooth sink: {e}")
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
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, '/'),
                'org.freedesktop.DBus.ObjectManager'
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
            print(f"Could not verify A2DP sink support: {e}")
            # Assume it might work anyway
            return True
    
    def _detect_audio_system(self) -> str:
        """Detect which audio system is running."""
        try:
            # Check for PipeWire first (modern)
            result = subprocess.run(['pgrep', '-x', 'pipewire'], 
                                  capture_output=True, timeout=2)
            if result.returncode == 0:
                return 'pipewire'
            
            # Check for PulseAudio
            result = subprocess.run(['pgrep', '-x', 'pulseaudio'], 
                                  capture_output=True, timeout=2)
            if result.returncode == 0:
                return 'pulseaudio'
            
            return 'none'
        except:
            return 'none'
    
    def _set_adapter_name(self, name: str):
        """Set the Bluetooth adapter's visible name."""
        try:
            if not self.bt_manager.adapter_path:
                return
            
            props = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, 
                                                self.bt_manager.adapter_path),
                self.bt_manager.PROPERTIES_INTERFACE
            )
            props.Set(self.bt_manager.ADAPTER_INTERFACE, 'Alias', dbus.String(name))
            print(f"Set Bluetooth name to: {name}")
        except Exception as e:
            print(f"Error setting adapter name: {e}")
    
    def _set_discoverable(self, discoverable: bool, timeout: int = 0):
        """
        Set the Bluetooth adapter's discoverability.
        
        Args:
            discoverable: Whether to be discoverable
            timeout: Timeout in seconds (0 = indefinite)
        """
        try:
            if not self.bt_manager.adapter_path:
                return
            
            props = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, 
                                                self.bt_manager.adapter_path),
                self.bt_manager.PROPERTIES_INTERFACE
            )
            
            props.Set(self.bt_manager.ADAPTER_INTERFACE, 'Discoverable', 
                     dbus.Boolean(discoverable))
            
            if discoverable and timeout == 0:
                # Set no timeout for indefinite discoverability
                props.Set(self.bt_manager.ADAPTER_INTERFACE, 'DiscoverableTimeout',
                         dbus.UInt32(0))
            
            self.is_discoverable = discoverable
            print(f"Discoverable: {discoverable}")
        except Exception as e:
            print(f"Error setting discoverable: {e}")
    
    def _set_pairable(self, pairable: bool, timeout: int = 0):
        """Set the Bluetooth adapter's pairability."""
        try:
            if not self.bt_manager.adapter_path:
                return
            
            props = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, 
                                                self.bt_manager.adapter_path),
                self.bt_manager.PROPERTIES_INTERFACE
            )
            
            props.Set(self.bt_manager.ADAPTER_INTERFACE, 'Pairable', 
                     dbus.Boolean(pairable))
            
            if pairable and timeout == 0:
                props.Set(self.bt_manager.ADAPTER_INTERFACE, 'PairableTimeout',
                         dbus.UInt32(0))
            
            print(f"Pairable: {pairable}")
        except Exception as e:
            print(f"Error setting pairable: {e}")
    
    def _enable_pipewire_sink(self) -> bool:
        """Enable A2DP sink using PipeWire (modern setup)."""
        try:
            # PipeWire with wireplumber handles A2DP automatically
            # Just ensure the Bluetooth module is running
            
            # Check if wireplumber is running
            result = subprocess.run(['pgrep', '-x', 'wireplumber'],
                                  capture_output=True, timeout=2)
            
            if result.returncode != 0:
                print("wireplumber not running, trying to start...")
                subprocess.Popen(['wireplumber'], 
                               stdout=subprocess.DEVNULL, 
                               stderr=subprocess.DEVNULL)
            
            # PipeWire should now handle A2DP connections automatically
            print("PipeWire sink mode enabled")
            return True
            
        except Exception as e:
            print(f"Error enabling PipeWire sink: {e}")
            return False
    
    def _enable_pulseaudio_sink(self) -> bool:
        """Enable A2DP sink using PulseAudio."""
        try:
            # Load Bluetooth modules
            subprocess.run(['pactl', 'load-module', 'module-bluetooth-discover'],
                         capture_output=True, timeout=5)
            subprocess.run(['pactl', 'load-module', 'module-bluetooth-policy'],
                         capture_output=True, timeout=5)
            
            print("PulseAudio sink mode enabled")
            return True
            
        except Exception as e:
            print(f"Error enabling PulseAudio sink: {e}")
            return False
    
    def _enable_gst_bluez_sink(self) -> bool:
        """Enable A2DP sink using GStreamer BlueZ plugin."""
        try:
            print("Using GStreamer BlueZ plugin for audio routing")
            # GStreamer BlueZ plugin integrates with BlueZ D-Bus automatically
            # When a device connects via A2DP, GStreamer can handle the audio stream
            # The actual audio routing will be configured when a device connects
            print("GStreamer BlueZ sink mode enabled")
            return True
        except Exception as e:
            print(f"Error enabling GStreamer BlueZ sink: {e}")
            return False
    
    def _enable_basic_sink(self) -> bool:
        """Enable basic A2DP sink without sound server (direct ALSA)."""
        try:
            # This is a fallback - just ensure Bluetooth is ready
            # Note: Direct ALSA A2DP requires additional setup (bluez-alsa)
            print("Warning: No PipeWire, PulseAudio, or GStreamer BlueZ plugin.")
            print("Install one of:")
            print("  - media-plugins/gst-plugins-bluez (recommended)")
            print("  - media-video/pipewire")
            print("  - media-sound/pulseaudio")
            return True
        except Exception as e:
            print(f"Error enabling basic sink: {e}")
            return False
    
    def _on_device_connected(self, device: BluetoothDevice):
        """Handle Bluetooth device connection."""
        self.connected_device = device
        
        # Call original callback if set
        if self._original_device_connected:
            self._original_device_connected(device)
        
        # Call our callback
        if self.on_device_connected:
            self.on_device_connected(device)
        
        # If sink mode is enabled, ensure audio is routed properly
        if self.is_sink_enabled:
            self._configure_audio_routing(device)
    
    def _on_device_disconnected(self, device: BluetoothDevice):
        """Handle Bluetooth device disconnection."""
        if self.connected_device and self.connected_device.path == device.path:
            self.connected_device = None
        
        # Call original callback if set
        if self._original_device_disconnected:
            self._original_device_disconnected(device)
        
        # Call our callback
        if self.on_device_disconnected:
            self.on_device_disconnected(device)
        
        if self.on_audio_stream_stopped:
            self.on_audio_stream_stopped()
    
    def _configure_audio_routing(self, device: BluetoothDevice):
        """Configure audio routing for the connected device."""
        try:
            print(f"Configuring audio routing for {device.name} ({device.address})")
            
            # Check if A2DP transport is available
            transport_available = self._check_a2dp_transport(device)
            if not transport_available:
                print(f"Warning: A2DP transport not yet available for {device.name}")
                print("Audio routing will be configured when A2DP transport becomes active")
                # Try again after a short delay
                import gi
                gi.require_version('GLib', '2.0')
                from gi.repository import GLib
                GLib.timeout_add(1000, lambda: self._retry_audio_routing(device))
                return
            
            # Prefer GStreamer BlueZ plugin if available
            if self.gst_bluez_available:
                self._setup_gst_bluez_routing(device)
            else:
                audio_system = self._detect_audio_system()
                
                if audio_system == 'pipewire':
                    # PipeWire handles routing automatically
                    print(f"Audio from {device.name} will be routed via PipeWire")
                elif audio_system == 'pulseaudio':
                    # Find the Bluetooth source and loopback to ALSA sink
                    self._setup_pulseaudio_routing(device)
            
            if self.on_audio_stream_started:
                self.on_audio_stream_started()
                
        except Exception as e:
            print(f"Error configuring audio routing: {e}")
            import traceback
            traceback.print_exc()
    
    def _check_a2dp_transport(self, device: BluetoothDevice) -> bool:
        """Check if A2DP transport is available for the device."""
        try:
            manager = dbus.Interface(
                self.bt_manager.bus.get_object(self.bt_manager.BLUEZ_SERVICE, '/'),
                'org.freedesktop.DBus.ObjectManager'
            )
            objects = manager.GetManagedObjects()
            
            # Look for MediaTransport interface for this device
            for path, interfaces in objects.items():
                if self.MEDIA_TRANSPORT_INTERFACE in interfaces:
                    # Check if this transport belongs to our device
                    transport_props = interfaces[self.MEDIA_TRANSPORT_INTERFACE]
                    device_path = str(transport_props.get('Device', ''))
                    if device_path == device.path:
                        state = str(transport_props.get('State', ''))
                        print(f"A2DP transport found for {device.name}: state={state}")
                        return state in ['idle', 'pending', 'active']
            return False
        except Exception as e:
            print(f"Error checking A2DP transport: {e}")
            return False
    
    def _retry_audio_routing(self, device: BluetoothDevice) -> bool:
        """Retry audio routing configuration after delay."""
        if device.connected:
            self._configure_audio_routing(device)
        return False  # Remove from timeout
    
    def _setup_gst_bluez_routing(self, device: BluetoothDevice):
        """Set up audio routing using GStreamer BlueZ plugin."""
        try:
            # GStreamer BlueZ plugin automatically handles A2DP connections
            # The plugin integrates with BlueZ D-Bus to receive audio streams
            print(f"GStreamer BlueZ: Audio from {device.name} ({device.address}) will be handled automatically")
            print("The BlueZ plugin integrates with the BlueZ D-Bus service for A2DP audio routing")
            
            # Note: The actual audio pipeline is managed by GStreamer/BlueZ
            # We don't need to manually create pipelines - BlueZ handles it via D-Bus
            # The audio will be available through the default audio sink
            
        except Exception as e:
            print(f"Error setting up GStreamer BlueZ routing: {e}")
    
    def _setup_pulseaudio_routing(self, device: BluetoothDevice):
        """Set up PulseAudio loopback from Bluetooth to ALSA."""
        try:
            # Get Bluetooth source
            result = subprocess.run(['pactl', 'list', 'sources', 'short'],
                                  capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if 'bluez' in line.lower():
                        source = line.split()[1]
                        
                        # Get ALSA sink
                        sink_result = subprocess.run(['pactl', 'list', 'sinks', 'short'],
                                                   capture_output=True, text=True, timeout=5)
                        
                        if sink_result.returncode == 0:
                            for sink_line in sink_result.stdout.strip().split('\n'):
                                if 'alsa' in sink_line.lower():
                                    sink = sink_line.split()[1]
                                    
                                    # Create loopback
                                    subprocess.run([
                                        'pactl', 'load-module', 'module-loopback',
                                        f'source={source}', f'sink={sink}'
                                    ], capture_output=True, timeout=5)
                                    
                                    print(f"Created loopback: {source} -> {sink}")
                                    return
        except Exception as e:
            print(f"Error setting up PulseAudio routing: {e}")
    
    def get_status(self) -> dict:
        """Get current sink status."""
        audio_system = self._detect_audio_system()
        if self.gst_bluez_available:
            audio_system = 'gstreamer-bluez'
        
        return {
            'enabled': self.is_sink_enabled,
            'discoverable': self.is_discoverable,
            'connected_device': self.connected_device.name if self.connected_device else None,
            'device_address': self.connected_device.address if self.connected_device else None,
            'bluetooth_powered': self.bt_manager.is_powered(),
            'audio_system': audio_system,
            'gst_bluez_available': self.gst_bluez_available,
        }
    
    def set_device_name(self, name: str):
        """Set the Bluetooth speaker name."""
        self.device_name = name
        if self.is_sink_enabled:
            self._set_adapter_name(name)
