"""BlueZ Agent for handling Bluetooth pairing confirmations and passkeys."""

from typing import Callable, Optional

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from core.logging import get_logger

logger = get_logger(__name__)


class BluetoothAgent(dbus.service.Object):
    """
    BlueZ Agent for handling pairing requests.

    This agent handles:
    - PIN code requests
    - Passkey requests (6-digit numeric codes)
    - Passkey confirmations (display and confirm matching codes)
    - Authorization requests
    """

    AGENT_PATH = "/org/bluez/agent"
    AGENT_INTERFACE = "org.bluez.Agent1"
    AGENT_MANAGER_INTERFACE = "org.bluez.AgentManager1"
    AGENT_MANAGER_PATH = "/org/bluez"

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

    def _register_agent(self) -> None:
        """
        Register this agent with BlueZ.

        Registers the agent with the BlueZ AgentManager and requests it as the default agent.

        Raises:
            dbus.exceptions.DBusException: If registration fails
        """
        try:
            agent_manager = dbus.Interface(
                self.bus.get_object("org.bluez", self.AGENT_MANAGER_PATH),
                self.AGENT_MANAGER_INTERFACE,
            )
            # Register with capability "KeyboardDisplay" which supports:
            # - DisplayPasskey: Show passkey to user
            # - RequestConfirmation: Confirm matching passkeys
            # - RequestPasskey: Enter passkey from other device
            # - RequestPinCode: Enter PIN code
            # This is the most comprehensive capability for modern pairing
            agent_manager.RegisterAgent(self.AGENT_PATH, "KeyboardDisplay")
            agent_manager.RequestDefaultAgent(self.AGENT_PATH)
            logger.info(
                "Bluetooth Agent registered successfully with KeyboardDisplay capability"
            )
        except dbus.exceptions.DBusException as e:
            logger.error("Error registering Bluetooth Agent: %s", e)
            # Re-raise BlueZ-specific exceptions
            raise
        except Exception as e:
            logger.error("Error registering Bluetooth Agent: %s", e, exc_info=True)

    def unregister_agent(self):
        """Unregister this agent from BlueZ."""
        try:
            agent_manager = dbus.Interface(
                self.bus.get_object("org.bluez", self.AGENT_MANAGER_PATH),
                self.AGENT_MANAGER_INTERFACE,
            )
            agent_manager.UnregisterAgent(self.AGENT_PATH)
            logger.info("Bluetooth Agent unregistered successfully")
        except dbus.exceptions.DBusException as e:
            # Agent might already be unregistered, which is fine
            if "org.bluez.Error.DoesNotExist" not in str(e):
                logger.error("Error unregistering Bluetooth Agent: %s", e)
        except Exception as e:
            logger.error("Error unregistering Bluetooth Agent: %s", e, exc_info=True)

    def release(self):
        """Called when the agent is released."""
        logger.debug("Bluetooth Agent released")

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        """Release the agent."""
        self.release()

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device_path):
        """
        Request a PIN code for pairing.

        According to BlueZ specification:
        - PIN codes are typically 4-16 digits
        - Must return a string of digits
        - Raises org.bluez.Error.Canceled if user cancels
        - Raises org.bluez.Error.Rejected if invalid

        Args:
            device_path: D-Bus path of the device (object path)

        Returns:
            PIN code string (4-16 digits)
        """
        device_name = self._get_device_name(device_path)
        logger.info("PIN code requested for device: %s (%s)", device_name, device_path)

        if self.on_pin_request:
            try:
                pin = self.on_pin_request(device_name)
                if pin:
                    # Validate PIN: 4-16 digits (Bluetooth standard)
                    pin_str = str(pin).strip()
                    if not pin_str.isdigit():
                        raise dbus.exceptions.DBusException(
                            "org.bluez.Error.Rejected",
                            "PIN code must contain only digits",
                        )
                    if len(pin_str) < 4 or len(pin_str) > 16:
                        raise dbus.exceptions.DBusException(
                            "org.bluez.Error.Rejected", "PIN code must be 4-16 digits"
                        )
                    self.pin_code = pin_str
                    logger.debug("Returning PIN code for %s", device_name)
                    return pin_str
                else:
                    logger.warning("No PIN code provided for %s", device_name)
            except dbus.exceptions.DBusException:
                # Re-raise D-Bus exceptions
                raise
            except Exception as e:
                logger.error("Error in PIN request callback: %s", e, exc_info=True)

        # Default: raise exception to cancel pairing
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.Canceled", "PIN code request canceled"
        )

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device_path):
        """
        Request a passkey (6-digit number) for pairing.

        According to BlueZ specification:
        - Passkey must be exactly 6 digits (000000-999999)
        - Returns uint32 value
        - Raises org.bluez.Error.Canceled if user cancels
        - Raises org.bluez.Error.Rejected if invalid

        Args:
            device_path: D-Bus path of the device (object path)

        Returns:
            6-digit passkey as uint32 (0-999999)
        """
        device_name = self._get_device_name(device_path)
        logger.info("Passkey requested for device: %s (%s)", device_name, device_path)

        if self.on_passkey_request:
            try:
                passkey = self.on_passkey_request(device_name)
                if passkey is not None:
                    # Validate passkey: must be exactly 6 digits (0-999999)
                    if isinstance(passkey, str):
                        if not passkey.isdigit() or len(passkey) != 6:
                            raise dbus.exceptions.DBusException(
                                "org.bluez.Error.Rejected",
                                "Passkey must be exactly 6 digits",
                            )
                        passkey = int(passkey)
                    elif not isinstance(passkey, int):
                        raise dbus.exceptions.DBusException(
                            "org.bluez.Error.Rejected",
                            "Passkey must be a 6-digit number",
                        )

                    if not (0 <= passkey <= 999999):
                        raise dbus.exceptions.DBusException(
                            "org.bluez.Error.Rejected",
                            "Passkey must be between 000000 and 999999",
                        )

                    self.passkey = passkey
                    logger.debug("Returning passkey %06d for %s", passkey, device_name)
                    return dbus.UInt32(passkey)
                else:
                    logger.warning("No passkey provided for %s", device_name)
            except dbus.exceptions.DBusException:
                # Re-raise D-Bus exceptions
                raise
            except Exception as e:
                logger.error("Error in passkey request callback: %s", e, exc_info=True)

        # Default: raise exception to cancel pairing
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.Canceled", "Passkey request canceled"
        )

    @dbus.service.method(AGENT_INTERFACE, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device_path, passkey, entered):
        """
        Display a passkey that needs to be confirmed on the other device.

        According to BlueZ specification:
        - Called during Numeric Comparison pairing
        - passkey: uint32 (0-999999)
        - entered: uint16 (0-6) indicating digits entered so far
        - This is informational only, no return value

        Args:
            device_path: D-Bus path of the device (object path)
            passkey: 6-digit passkey to display (uint32)
            entered: Number of digits entered so far (uint16, 0-6)
        """
        # Convert dbus types to Python types
        passkey_int = (
            int(passkey)
            if isinstance(passkey, (dbus.UInt32, dbus.Int32))
            else int(passkey)
        )
        entered_int = (
            int(entered)
            if isinstance(entered, (dbus.UInt16, dbus.Int16))
            else int(entered)
        )

        device_name = self._get_device_name(device_path)
        logger.info(
            "Display passkey for %s: %06d (entered: %d/6)",
            device_name,
            passkey_int,
            entered_int,
        )

        if self.on_passkey_display:
            try:
                self.on_passkey_display(device_name, passkey_int)
            except Exception as e:
                logger.error("Error in passkey display callback: %s", e, exc_info=True)
                # Don't raise - this is informational only

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device_path, passkey):
        """
        Request confirmation that the passkey matches on both devices.

        According to BlueZ specification:
        - Called during Numeric Comparison pairing
        - passkey: uint32 (0-999999)
        - Raises org.bluez.Error.Rejected if user rejects
        - Returns normally if user confirms

        Args:
            device_path: D-Bus path of the device (object path)
            passkey: 6-digit passkey to confirm (uint32)
        """
        # Convert dbus type to Python type
        passkey_int = (
            int(passkey)
            if isinstance(passkey, (dbus.UInt32, dbus.Int32))
            else int(passkey)
        )

        device_name = self._get_device_name(device_path)
        logger.info(
            "Passkey confirmation requested for %s: %06d", device_name, passkey_int
        )

        # Use passkey confirmation callback if available
        if self.on_passkey_confirm:
            try:
                confirmed = self.on_passkey_confirm(device_name, passkey_int)
                if confirmed:
                    logger.info(
                        "Passkey %06d confirmed for %s", passkey_int, device_name
                    )
                    return  # Success - return normally
                else:
                    # User rejected - raise exception immediately
                    logger.info(
                        "Passkey %06d rejected by user for %s", passkey_int, device_name
                    )
                    raise dbus.exceptions.DBusException(
                        "org.bluez.Error.Rejected",
                        "Passkey confirmation rejected by user",
                    )
            except dbus.exceptions.DBusException:
                # Re-raise D-Bus exceptions (including our rejection)
                raise
            except Exception as e:
                logger.error(
                    "Error in passkey confirmation callback: %s", e, exc_info=True
                )
                # On error, reject the pairing
                raise dbus.exceptions.DBusException(
                    "org.bluez.Error.Rejected", f"Passkey confirmation failed: {e}"
                )
        elif self.on_authorization_request:
            # Fallback: use authorization request
            try:
                confirmed = self.on_authorization_request(
                    f"Does the passkey {passkey_int:06d} match what's shown on {device_name}?"
                )
                if confirmed:
                    return  # Success - return normally
                else:
                    # User rejected - raise exception immediately
                    logger.info(
                        "Passkey %06d rejected by user for %s", passkey_int, device_name
                    )
                    raise dbus.exceptions.DBusException(
                        "org.bluez.Error.Rejected",
                        "Passkey confirmation rejected by user",
                    )
            except dbus.exceptions.DBusException:
                # Re-raise D-Bus exceptions (including our rejection)
                raise
            except Exception as e:
                logger.error("Error in authorization callback: %s", e, exc_info=True)
                # On error, reject the pairing
                raise dbus.exceptions.DBusException(
                    "org.bluez.Error.Rejected", f"Passkey confirmation failed: {e}"
                )

        # Default: reject (raise exception) - no callback available
        logger.warning(
            "Passkey %06d rejected: no confirmation callback available", passkey_int
        )
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.Rejected",
            "Passkey confirmation rejected: no callback available",
        )

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device_path):
        """
        Request authorization for a device connection.

        According to BlueZ specification:
        - Called when a device requests connection authorization
        - Raises org.bluez.Error.Rejected if user rejects
        - Returns normally if user authorizes

        Args:
            device_path: D-Bus path of the device (object path)
        """
        device_name = self._get_device_name(device_path)
        logger.info(
            "Authorization requested for device: %s (%s)", device_name, device_path
        )

        if self.on_authorization_request:
            try:
                authorized = self.on_authorization_request(
                    f"Authorize connection to {device_name}?"
                )
                if authorized:
                    return
            except dbus.exceptions.DBusException:
                # Re-raise D-Bus exceptions
                raise
            except Exception as e:
                logger.error("Error in authorization callback: %s", e, exc_info=True)

        # Default: reject
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.Rejected", "Authorization rejected"
        )

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        """Cancel the current pairing request."""
        logger.info("Pairing request cancelled")

    def _get_device_name(self, device_path: str) -> str:
        """Get device name from D-Bus path."""
        try:
            device_obj = self.bus.get_object("org.bluez", device_path)
            props = dbus.Interface(device_obj, "org.freedesktop.DBus.Properties")
            name = props.Get("org.bluez.Device1", "Name")
            return str(name)
        except Exception:
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
            modal=True,
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
        passkey_label.set_markup(
            f"<span size='xx-large' weight='bold'>{passkey:06d}</span>"
        )
        passkey_label.add_css_class("title-1")
        content.append(passkey_label)

        # GTK4: Use response signal instead of run()
        response_received = {"value": None}

        def on_response(dialog, response_id):
            response_received["value"] = response_id
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for response using main loop
        while response_received["value"] is None:
            GLib.MainContext.default().iteration(True)

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
            modal=True,
        )
        dialog.add_buttons("_No", Gtk.ResponseType.NO, "_Yes", Gtk.ResponseType.YES)
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
        question_label = Gtk.Label(
            label=f"Does this passkey match what's shown on {device_name}?"
        )
        question_label.set_wrap(True)
        content.append(question_label)

        # Passkey label with large font
        passkey_label = Gtk.Label()
        passkey_label.set_markup(
            f"<span size='xx-large' weight='bold'>{passkey:06d}</span>"
        )
        passkey_label.add_css_class("title-1")
        content.append(passkey_label)

        # GTK4: Use response signal instead of run()
        # We need to use the default GLib main context to ensure GTK events are processed
        response_received = {"value": None}
        main_context = GLib.MainContext.default()
        main_loop = GLib.MainLoop(main_context)

        def on_response(dialog, response_id):
            # Only process if we haven't already received a response
            if response_received["value"] is None:
                logger.debug("Dialog response received: %s", response_id)
                response_received["value"] = response_id
                # Quit the main loop - dialog will be destroyed after
                main_loop.quit()

        def on_close_request(dialog):
            # Handle window close (X button) - treat as rejection
            # Only handle if we haven't received a response yet
            if response_received["value"] is None:
                logger.debug("Dialog closed by user (X button), treating as rejection")
                response_received["value"] = Gtk.ResponseType.NO
                main_loop.quit()
            # Always allow close - we've handled it
            return True

        dialog.connect("response", on_response)
        dialog.connect("close-request", on_close_request)

        # Make sure dialog is visible and modal
        dialog.set_modal(True)
        dialog.present()

        # Ensure dialog is shown and events are processed
        # Process pending events to make sure dialog appears
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)

        logger.debug("Waiting for user response...")
        # Run main loop until response is received
        # This will process GTK events in the default context
        main_loop.run()

        # Get the response
        response = response_received["value"]

        # Destroy the dialog
        dialog.destroy()

        # Map response to boolean
        if response == Gtk.ResponseType.YES:
            result = True
        elif response == Gtk.ResponseType.NO:
            result = False
        else:
            # Any other response (shouldn't happen, but be safe)
            logger.warning(
                "Unexpected dialog response: %s, treating as rejection", response
            )
            result = False

        logger.debug("Final result: response=%s, confirmed=%s", response, result)
        return result

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
            modal=True,
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, "_OK", Gtk.ResponseType.OK
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

        # GTK4: Use response signal instead of run()
        response_received = {"value": None}

        def on_response(dialog, response_id):
            response_received["value"] = response_id
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for response using main loop
        while response_received["value"] is None:
            GLib.MainContext.default().iteration(True)

        response = response_received["value"]
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
            modal=True,
        )
        dialog.add_buttons("_No", Gtk.ResponseType.NO, "_Yes", Gtk.ResponseType.YES)
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

        # GTK4: Use response signal instead of run()
        response_received = {"value": None}

        def on_response(dialog, response_id):
            response_received["value"] = response_id
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

        # Wait for response using main loop
        while response_received["value"] is None:
            GLib.MainContext.default().iteration(True)

        response = response_received["value"]
        dialog.destroy()

        return response == Gtk.ResponseType.YES
