#!/usr/bin/env python3
"""Music Player - Main entry point."""

import sys
import os
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gst', '1.0')
from gi.repository import Gtk, Gst

# Try to use libadwaita if available, otherwise fall back to Gtk.Application
try:
    gi.require_version('Adw', '1')
    from gi.repository import Adw
    USE_ADW = True
except ValueError:
    USE_ADW = False

from ui.main_window import MainWindow


class MusicPlayerApp(Gtk.Application if not USE_ADW else Adw.Application):
    """Main application class."""
    
    def __init__(self):
        super().__init__(
            application_id='com.musicplayer.app',
            flags=0
        )
        self.connect('activate', self._on_activate)
    
    def _on_activate(self, app):
        """Handle application activation."""
        window = MainWindow(app)
        window.present()


def main():
    """Main entry point."""
    # Check for display
    display = os.environ.get('DISPLAY')
    if not display:
        print("Error: No DISPLAY environment variable set.")
        print("If running over SSH, use X11 forwarding: ssh -X user@host")
        return 1
    
    print(f"Using X11 display: {display}")
    
    # Check for X11 authentication
    xauth_file = os.path.expanduser('~/.Xauthority')
    if not os.path.exists(xauth_file):
        print("Warning: ~/.Xauthority file not found.")
        print("X11 authentication may fail. To fix:")
        print("  1. Run: xauth generate :0 . trusted")
        print("  2. Or allow local connections: xhost +local:")
        print("  3. Or if on remote: ensure SSH X11 forwarding is enabled")
    elif not os.access(xauth_file, os.R_OK):
        print(f"Warning: Cannot read ~/.Xauthority (permission denied)")
        print("Fix permissions: chmod 600 ~/.Xauthority")
    
    # Set GDK backend to x11 explicitly
    os.environ.setdefault('GDK_BACKEND', 'x11')
    
    # Initialize GStreamer first (doesn't need display)
    Gst.init(None)
    
    # Initialize GTK explicitly - this must happen before creating any widgets
    # Use init_check to handle failures gracefully
    try:
        success, argv = Gtk.init_check(sys.argv)
        if not success:
            print("\nError: Failed to initialize GTK for X11.")
            print("\nPossible solutions:")
            print("1. Fix X11 authentication:")
            print("   xauth generate :0 . trusted")
            print("   # Or if that doesn't work:")
            print("   xhost +local:")
            print("\n2. Check X11 is running:")
            print("   echo $DISPLAY")
            print("   xdpyinfo")
            print("\n3. If using SSH, ensure X11 forwarding:")
            print("   ssh -X user@host")
            print("   # Or with trusted forwarding:")
            print("   ssh -Y user@host")
            print("\n4. Check X11 server is accessible:")
            print("   xset q")
            return 1
    except Exception as e:
        print(f"\nError initializing GTK: {e}")
        print("\nThis is likely an X11 authentication issue.")
        print("Try running: xhost +local:")
        print("Or: xauth generate :0 . trusted")
        return 1
    
    # Create and run the application
    # Note: app.run() will use the already-initialized GTK
    app = MusicPlayerApp()
    return app.run(argv if argv else sys.argv)


if __name__ == '__main__':
    sys.exit(main())

