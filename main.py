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

from core.config import get_config
from core.logging import get_logger
from ui.main_window import MainWindow

logger = get_logger(__name__)


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
    
    def _on_open(self, app, files, n_files, hint):
        """Handle file open (drag-and-drop or command line)."""
        if not self.window:
            self.window = MainWindow(app)
        
        # Add files to playlist
        for file_info in files:
            file_path = file_info.get_path()
            if file_path:
                from core.metadata import TrackMetadata
                track = TrackMetadata(file_path)
                self.window.playlist_manager.add_track(track)
        
        self.window._update_playlist_view()
        self.window.present()


def main():
    """Main entry point."""
    # Initialize config (creates directories, loads settings)
    config = get_config()
    
    # Initialize logging (uses config for log directory)
    from core.logging import LinuxLogger
    LinuxLogger(log_dir=config.log_dir)
    
    # Initialize GStreamer
    Gst.init(None)
    
    # Create and run the application
    app = MusicPlayerApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
