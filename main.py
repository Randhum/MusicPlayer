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


class MusicPlayerApp(Adw.Application if USE_ADW else Gtk.Application):
    """Main application class."""
    
    def __init__(self):
        super().__init__(
            application_id='com.musicplayer.app',
            flags=0
        )
        self.connect('activate', self._on_activate)
        self.window = None
    
    def _on_activate(self, app):
        """Handle application activation."""
        if not self.window:
            self.window = MainWindow(app)
        self.window.present()


def main():
    """Main entry point."""
    # Initialize GStreamer
    Gst.init(None)
    
    # Create and run the application
    app = MusicPlayerApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
