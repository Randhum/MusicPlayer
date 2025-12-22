"""BlueZ Agent for handling Bluetooth pairing confirmations and passkeys."""

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from typing import Optional, Callable
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib


class BluetoothAgent(dbus.service.Object):
    """
    BlueZ Agent for handling pairing requests.
    
    This agent handles:
    - PIN code requests
    - Passkey requests (6-digit numeric codes)
    - Passkey confirmations (display and confirm matching codes)
    - Authorization requests
    """
    
    AGENT_PATH = '/org/bluez/agent'
    AGENT_INTERFACE = 'org.bluez.Agent1'
    AGENT_MANAGER_INTERFACE = 'org.bluez.AgentManager1'
    AGENT_MANAGER_PATH = '/org/bluez'
    
    def __init__(self, bus: dbus.Bus, adapter_path: str):
        """
        Initialize the Bluetooth Agent.
        
        Args:
            bus: D-Bus system bus
            adapter_path: Path to the Bluetooth adapter
        """
        self.bus = bus
        self.adapter_path = adapter_path
        self.passkey: Optional[int] = None
        self.pin_code: Optional[str] = None
        
        # Callbacks for UI interaction
        self.on_passkey_request: Optional[Callable[[str], Optional[int]]] = None
        self.on_passkey_display: Optional[Callable[[str, int], None]] = None
        self.on_passkey_confirm: Optional[Callable[[str, int], bool]] = None
        self.on_pin_request: Optional[Callable[[str], Optional[str]]] = None
        self.on_authorization_request: Optional[Callable[[str], bool]] = None
        
        # Register the agent object
        dbus.service.Object.__init__(self, bus, self.AGENT_PATH)
        
        # Register with BlueZ AgentManager
        self._register_agent()
    
    def _register_agent(self):
        """Register this agent with BlueZ."""
        try:
            agent_manager = dbus.Interface(
                self.bus.get_object('org.bluez', self.AGENT_MANAGER_PATH),
                self.AGENT_MANAGER_INTERFACE
            )
            # Register with capability "KeyboardDisplay" which supports:
            # - DisplayPasskey: Show passkey to user
            # - RequestConfirmation: Confirm matching passkeys
            # - RequestPasskey: Enter passkey from other device
            # - RequestPinCode: Enter PIN code
            # This is the most comprehensive capability for modern pairing
            agent_manager.RegisterAgent(self.AGENT_PATH, "KeyboardDisplay")
            agent_manager.RequestDefaultAgent(self.AGENT_PATH)
            print("Bluetooth Agent registered successfully with KeyboardDisplay capability")
        except Exception as e:
            print(f"Error registering Bluetooth Agent: {e}")
            import traceback
            traceback.print_exc()
    
    def release(self):
        """Called when the agent is released."""
        print("Bluetooth Agent released")
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='', out_signature='')
    def Release(self):
        """Release the agent."""
        self.release()
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='o', out_signature='s')
    def RequestPinCode(self, device_path):
        """
        Request a PIN code for pairing.
        
        Args:
            device_path: D-Bus path of the device
            
        Returns:
            PIN code string
        """
        device_name = self._get_device_name(device_path)
        print(f"PIN code requested for device: {device_name} ({device_path})")
        
        if self.on_pin_request:
            try:
                pin = self.on_pin_request(device_name)
                if pin:
                    self.pin_code = pin
                    print(f"Returning PIN code for {device_name}")
                    return pin
                else:
                    print(f"No PIN code provided for {device_name}")
            except Exception as e:
                print(f"Error in PIN request callback: {e}")
                import traceback
                traceback.print_exc()
        
        # Default: raise exception to cancel pairing
        raise dbus.exceptions.DBusException(
            'org.bluez.Error.Canceled',
            'PIN code request canceled'
        )
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='o', out_signature='u')
    def RequestPasskey(self, device_path):
        """
        Request a passkey (6-digit number) for pairing.
        
        Args:
            device_path: D-Bus path of the device
            
        Returns:
            6-digit passkey (0-999999)
        """
        device_name = self._get_device_name(device_path)
        print(f"Passkey requested for device: {device_name} ({device_path})")
        
        if self.on_passkey_request:
            try:
                passkey = self.on_passkey_request(device_name)
                if passkey and 0 <= passkey <= 999999:
                    self.passkey = passkey
                    print(f"Returning passkey {passkey:06d} for {device_name}")
                    return dbus.UInt32(passkey)
                else:
                    print(f"Invalid passkey returned: {passkey}")
            except Exception as e:
                print(f"Error in passkey request callback: {e}")
                import traceback
                traceback.print_exc()
        
        # Default: raise exception to cancel pairing
        raise dbus.exceptions.DBusException(
            'org.bluez.Error.Canceled',
            'Passkey request canceled'
        )
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='ouq', out_signature='')
    def DisplayPasskey(self, device_path, passkey, entered):
        """
        Display a passkey that needs to be confirmed on the other device.
        
        Args:
            device_path: D-Bus path of the device
            passkey: 6-digit passkey to display
            entered: Number of digits entered so far (0-6)
        """
        device_name = self._get_device_name(device_path)
        print(f"Display passkey for {device_name}: {passkey:06d} (entered: {entered})")
        
        if self.on_passkey_display:
            self.on_passkey_display(device_name, passkey)
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='ou', out_signature='')
    def RequestConfirmation(self, device_path, passkey):
        """
        Request confirmation that the passkey matches on both devices.
        
        Args:
            device_path: D-Bus path of the device
            passkey: 6-digit passkey to confirm
        """
        device_name = self._get_device_name(device_path)
        print(f"Passkey confirmation requested for {device_name}: {passkey:06d}")
        
        # Use passkey confirmation callback if available
        if self.on_passkey_confirm:
            try:
                confirmed = self.on_passkey_confirm(device_name, passkey)
                if confirmed:
                    print(f"Passkey {passkey:06d} confirmed for {device_name}")
                    return
                else:
                    print(f"Passkey {passkey:06d} rejected for {device_name}")
            except Exception as e:
                print(f"Error in passkey confirmation callback: {e}")
                import traceback
                traceback.print_exc()
        elif self.on_authorization_request:
            # Fallback: use authorization request
            try:
                confirmed = self.on_authorization_request(
                    f"Does the passkey {passkey:06d} match what's shown on {device_name}?"
                )
                if confirmed:
                    return
            except Exception as e:
                print(f"Error in authorization callback: {e}")
                import traceback
                traceback.print_exc()
        
        # Default: reject (raise exception)
        raise dbus.exceptions.DBusException(
            'org.bluez.Error.Rejected',
            'Passkey confirmation rejected'
        )
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='o', out_signature='')
    def RequestAuthorization(self, device_path):
        """
        Request authorization for a device connection.
        
        Args:
            device_path: D-Bus path of the device
        """
        device_name = self._get_device_name(device_path)
        print(f"Authorization requested for device: {device_name} ({device_path})")
        
        if self.on_authorization_request:
            authorized = self.on_authorization_request(f"Authorize connection to {device_name}?")
            if authorized:
                return
        
        # Default: reject
        raise dbus.exceptions.DBusException(
            'org.bluez.Error.Rejected',
            'Authorization rejected'
        )
    
    @dbus.service.method(AGENT_INTERFACE, in_signature='', out_signature='')
    def Cancel(self):
        """Cancel the current pairing request."""
        print("Pairing request cancelled")
    
    def _get_device_name(self, device_path: str) -> str:
        """Get device name from D-Bus path."""
        try:
            device_obj = self.bus.get_object('org.bluez', device_path)
            props = dbus.Interface(device_obj, 'org.freedesktop.DBus.Properties')
            name = props.Get('org.bluez.Device1', 'Name')
            return str(name)
        except:
            return "Unknown Device"


class BluetoothAgentUI:
    """
    UI handler for Bluetooth pairing dialogs.
    
    This class creates GTK dialogs for pairing confirmations.
    """
    
    def __init__(self, parent_window: Optional[Gtk.Window] = None):
        """
        Initialize the UI handler.
        
        Args:
            parent_window: Parent window for dialogs (optional)
        """
        self.parent_window = parent_window
        self.current_dialog: Optional[Gtk.Dialog] = None
    
    def show_passkey_display(self, device_name: str, passkey: int) -> None:
        """
        Display a passkey that the user needs to enter on the other device.
        
        Args:
            device_name: Name of the device
            passkey: 6-digit passkey to display
        """
        dialog = Gtk.Dialog(
            title=f"Pairing with {device_name}",
            transient_for=self.parent_window,
            modal=True
        )
        dialog.add_buttons("_OK", Gtk.ResponseType.OK)
        
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        
        # Title label
        title_label = Gtk.Label(label=f"Pairing with {device_name}")
        title_label.add_css_class("title-2")
        content.append(title_label)
        
        # Instruction label
        instruction_label = Gtk.Label(label=f"Enter this passkey on {device_name}:")
        instruction_label.set_wrap(True)
        content.append(instruction_label)
        
        # Passkey label with large font
        passkey_label = Gtk.Label()
        passkey_label.set_markup(f"<span size='xx-large' weight='bold'>{passkey:06d}</span>")
        passkey_label.add_css_class("title-1")
        content.append(passkey_label)
        
        dialog.run()
        dialog.destroy()
    
    def show_passkey_confirmation(self, device_name: str, passkey: int) -> bool:
        """
        Show a dialog asking the user to confirm a passkey matches.
        
        Args:
            device_name: Name of the device
            passkey: 6-digit passkey to confirm
            
        Returns:
            True if confirmed, False otherwise
        """
        dialog = Gtk.Dialog(
            title=f"Pairing with {device_name}",
            transient_for=self.parent_window,
            modal=True
        )
        dialog.add_buttons(
            "_No", Gtk.ResponseType.NO,
            "_Yes", Gtk.ResponseType.YES
        )
        dialog.set_default_response(Gtk.ResponseType.YES)
        
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        
        # Title label
        title_label = Gtk.Label(label=f"Pairing with {device_name}")
        title_label.add_css_class("title-2")
        content.append(title_label)
        
        # Question label
        question_label = Gtk.Label(label=f"Does this passkey match what's shown on {device_name}?")
        question_label.set_wrap(True)
        content.append(question_label)
        
        # Passkey label with large font
        passkey_label = Gtk.Label()
        passkey_label.set_markup(f"<span size='xx-large' weight='bold'>{passkey:06d}</span>")
        passkey_label.add_css_class("title-1")
        content.append(passkey_label)
        
        response = dialog.run()
        dialog.destroy()
        
        return response == Gtk.ResponseType.YES
    
    def show_pin_request(self, device_name: str) -> Optional[str]:
        """
        Show a dialog asking the user to enter a PIN code.
        
        Args:
            device_name: Name of the device
            
        Returns:
            PIN code string, or None if cancelled
        """
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
        label = Gtk.Label(label=f"Enter PIN code for {device_name}:")
        content.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("0000")
        entry.set_max_length(16)
        entry.set_activates_default(True)
        content.append(entry)
        
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry.grab_focus()
        
        response = dialog.run()
        pin = entry.get_text() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        
        return pin
    
    def show_authorization_request(self, message: str) -> bool:
        """
        Show a dialog asking the user to authorize a connection.
        
        Args:
            message: Authorization message
            
        Returns:
            True if authorized, False otherwise
        """
        dialog = Gtk.Dialog(
            title="Bluetooth Authorization",
            transient_for=self.parent_window,
            modal=True
        )
        dialog.add_buttons(
            "_No", Gtk.ResponseType.NO,
            "_Yes", Gtk.ResponseType.YES
        )
        dialog.set_default_response(Gtk.ResponseType.YES)
        
        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        
        # Message label
        message_label = Gtk.Label(label=message)
        message_label.set_wrap(True)
        content.append(message_label)
        
        response = dialog.run()
        dialog.destroy()
        
        return response == Gtk.ResponseType.YES

