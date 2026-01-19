#!/usr/bin/env python3
"""
Music Player - Main entry point.

This module initializes the application and creates the main window.
All component initialization (Bluetooth, audio players, etc.) is handled
by the MainWindow class.

Architecture:
- Event-driven architecture with EventBus for decoupled communication
- AppState provides single source of truth for application state
- PlaybackController routes playback commands to appropriate backends
- UI components are pure views that subscribe to events and publish actions
- No circular dependencies - components only depend on EventBus and AppState
"""

import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Gst

# Try to use libadwaita if available, otherwise fall back to Gtk.Application
try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    USE_ADW = True
except ValueError:
    USE_ADW = False

from typing import Optional, Any

from core.config import get_config
from core.logging import get_logger
from ui.main_window import MainWindow

logger = get_logger(__name__)


class MusicPlayerApp(Adw.Application if USE_ADW else Gtk.Application):
    """Main application class."""

    def __init__(self) -> None:
        """
        Initialize the music player application.

        Sets up GTK application with file open support for drag-and-drop.
        """
        super().__init__(application_id="com.musicplayer.app", flags=0)
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)
        self.window: Optional[MainWindow] = None

    def _on_activate(self, app: Gtk.Application) -> None:
        """
        Handle application activation.

        Args:
            app: GTK application instance
        """
        if not self.window:
            self.window = MainWindow(app)
        self.window.present()

    def _on_open(self, app: Gtk.Application, files: Any, n_files: int, hint: str) -> None:
        """
        Handle file open (drag-and-drop or command line).

        Args:
            app: GTK application instance
            files: List of Gio.File objects
            n_files: Number of files
            hint: Hint string (usually empty)
        """
        if not self.window:
            self.window = MainWindow(app)

        # Add files to playlist
        for file_info in files:
            file_path = file_info.get_path()
            if file_path:
                from core.metadata import TrackMetadata

                track = TrackMetadata(file_path)
                # Add track via AppState (which publishes events)
                self.window.app_state.add_track(track)

        self.window.present()


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success)
    """
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


if __name__ == "__main__":
    sys.exit(main())
