#!/usr/bin/env python3
"""Music Player - Main entry point."""

import sys
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
    # Initialize GStreamer before creating the application
    # This ensures it's ready when AudioPlayer is created
    Gst.init(None)
    
    app = MusicPlayerApp()
    # The application's run() method handles GTK initialization
    # Command-line arguments are passed to the application
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())

