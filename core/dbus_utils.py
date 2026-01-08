"""D-Bus utility functions for error handling and connection monitoring."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import time
from functools import wraps
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


class DBusConnectionMonitor:
    """Monitor D-Bus connection health and handle reconnections."""

    def __init__(self, bus: dbus.Bus):
        """
        Initialize connection monitor.

        Args:
            bus: D-Bus bus to monitor
        """
        self.bus = bus
        self._last_check = time.time()
        self._reconnect_callbacks: List[Callable] = []
        self._is_connected = True

    def check_connection(self) -> bool:
        """
        Check if D-Bus connection is healthy.

        Returns:
            True if connected, False otherwise
        """
        try:
            # Try to get a well-known name to test connection
            self.bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
            self._is_connected = True
            self._last_check = time.time()
            return True
        except Exception as e:
            logger.warning("D-Bus connection check failed: %s", e)
            self._is_connected = False
            return False

    def register_reconnect_callback(self, callback: Callable):
        """Register a callback to be called on reconnection."""
        self._reconnect_callbacks.append(callback)

    def trigger_reconnect(self):
        """Trigger reconnection callbacks."""
        for callback in self._reconnect_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error("Error in reconnect callback: %s", e, exc_info=True)


def dbus_retry(max_retries: int = 3, backoff: float = 0.5):
    """
    Decorator for D-Bus operations with retry logic.

    Args:
        max_retries: Maximum number of retry attempts
        backoff: Backoff delay in seconds (exponential)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = backoff

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except dbus.exceptions.DBusException as e:
                    last_exception = e
                    error_name = e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)

                    # Don't retry on certain errors
                    if "org.bluez.Error.DoesNotExist" in error_name:
                        raise  # Don't retry on non-existent resources
                    if "org.bluez.Error.NotReady" in error_name:
                        raise  # Don't retry on not ready

                    if attempt < max_retries - 1:
                        logger.debug(
                            "D-Bus operation failed (attempt %d/%d): %s, retrying in %.1fs",
                            attempt + 1,
                            max_retries,
                            error_name,
                            delay,
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(
                            "D-Bus operation failed after %d attempts: %s", max_retries, error_name
                        )
                except Exception as e:
                    # Non-D-Bus exceptions - don't retry
                    raise

            # All retries exhausted
            raise last_exception

        return wrapper

    return decorator


def dbus_safe_call(func: Callable, default_return: Any = None, log_errors: bool = True):
    """
    Safely call a D-Bus function with error handling.

    Args:
        func: Function to call
        default_return: Value to return on error
        log_errors: Whether to log errors

    Returns:
        Function result or default_return on error
    """
    try:
        return func()
    except dbus.exceptions.DBusException as e:
        if log_errors:
            error_name = e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
            logger.debug("D-Bus error in safe call: %s", error_name)
        return default_return
    except Exception as e:
        if log_errors:
            logger.error("Error in safe D-Bus call: %s", e, exc_info=True)
        return default_return


def validate_dbus_message(message: Any, required_interface: Optional[str] = None) -> bool:
    """
    Validate a D-Bus message for security.

    This function is intended for low-level D-Bus message validation.
    Note: When using dbus.service.Object, messages are handled automatically
    and methods receive regular Python arguments, not message objects.

    Args:
        message: D-Bus message object (low-level API) or any object with
                get_interface() and get_sender() methods
        required_interface: Required interface name (optional)

    Returns:
        True if message is valid, False otherwise
    """
    try:
        # Check if message has required interface
        if required_interface:
            if not hasattr(message, "get_interface"):
                logger.warning("D-Bus message object missing get_interface() method")
                return False
            if message.get_interface() != required_interface:
                logger.warning(
                    "D-Bus message has wrong interface: expected %s, got %s",
                    required_interface,
                    message.get_interface(),
                )
                return False

        # Validate sender (basic check)
        if not hasattr(message, "get_sender"):
            logger.warning("D-Bus message object missing get_sender() method")
            return False

        sender = message.get_sender()
        if sender and not sender.startswith(":"):
            # Well-known names should be validated
            # For now, just log suspicious senders
            if ".." in sender or "/" in sender:
                logger.warning("D-Bus message from suspicious sender: %s", sender)
                return False

        return True
    except Exception as e:
        logger.error("Error validating D-Bus message: %s", e, exc_info=True)
        return False
