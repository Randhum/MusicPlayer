"""GTK 4 helpers to dismiss Gtk.Popover on outside taps (touch + mouse).

GestureClick on the toplevel often misses touch sequences or uses coordinates that
do not match gtk_widget_pick; raw GDK events + Native.pick() match the event surface.
"""

from __future__ import annotations

from typing import Optional, Tuple

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk


def pick_widget_under_pointer(
    window: Gtk.Window,
    event: Optional[Gdk.Event],
    fallback_x: float,
    fallback_y: float,
) -> Tuple[Optional[Gtk.Widget], bool]:
    """Return (widget_under_pointer, coordinates_are_reliable).

    When ``event`` is a press/touch-begin, use surface-relative coords and the
    corresponding native widget's pick (touch-safe). Otherwise fall back to
    ``window.pick(fallback_x, fallback_y)`` only when ``event`` is None.
    """
    if event is not None:
        et = event.get_event_type()
        if et in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN):
            pos_ok, sx, sy = event.get_position()
            surface = event.get_surface()
            if pos_ok and surface is not None:
                native = Gtk.Native.get_for_surface(surface)
                if native is not None:
                    return (
                        native.pick(sx, sy, Gtk.PickFlags.DEFAULT),
                        True,
                    )
        return None, False

    return window.pick(fallback_x, fallback_y, Gtk.PickFlags.DEFAULT), True


def popover_should_dismiss(
    picked: Optional[Gtk.Widget], popover: Gtk.Widget
) -> bool:
    """True if the pick target is strictly outside ``popover`` (or unknown empty)."""
    if picked is None:
        return True
    if picked == popover or picked.is_ancestor(popover):
        return False
    return True
