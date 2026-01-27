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
from gi.repository import Gtk, Gst, Gio

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

APPLICATION_ID = "com.musicplayer.app"


class MusicPlayerApp(Adw.Application if USE_ADW else Gtk.Application):
    """Main application class."""

    def __init__(self) -> None:
        """
        Initialize the music player application.

        Sets up GTK application with file open support for drag-and-drop.
        Uses G_APPLICATION_HANDLES_OPEN flag to support file arguments.
        """
        super().__init__(
            application_id=APPLICATION_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)
        self.window: Optional[MainWindow] = None

    def do_startup(self) -> None:
        """
        Handle application startup.

        This is called once on the primary instance before activate/open.
        On secondary instances, this is NOT called - they just send
        activate/open to the primary and exit.
        """
        if USE_ADW:
            Adw.Application.do_startup(self)
        else:
            Gtk.Application.do_startup(self)
        logger.info("Music Player starting up (primary instance)")

    def _on_activate(self, app: Gtk.Application) -> None:
        """
        Handle application activation.

        Called when the app is launched without files, or when a secondary
        instance activates the primary. Presents the main window.

        Args:
            app: GTK application instance
        """
        if not self.window:
            self.window = MainWindow(app)
            logger.debug("Main window created")
        else:
            # Window already exists - this is activation from another instance
            logger.info("Presenting existing window (activated by another instance)")
        self.window.present()

    def _on_open(
        self, app: Gtk.Application, files: Any, n_files: int, hint: str
    ) -> None:
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

        # Add files to playlist via PlaylistView so both AppState and
        # PlaylistManager (and UI) stay in sync; avoids stale save/auto-save.
        for file_info in files:
            file_path = file_info.get_path()
            if file_path:
                from core.metadata import TrackMetadata

                track = TrackMetadata(file_path)
                self.window.playlist_view.add_track(track)

        self.window.present()


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    # Initialize config (creates directories, loads settings)
    config = get_config()

    # Initialize logging (uses config for log directory)
    from core.logging import LinuxLogger

    LinuxLogger(log_dir=config.log_dir)

    # Check if GTK can be initialized (display available, etc.)
    if not Gtk.init_check():
        logger.error(
            "Failed to initialize GTK. "
            "Ensure a display server (X11/Wayland) is running."
        )
        print(
            "Error: Cannot initialize GTK. Is a display server running?",
            file=sys.stderr,
        )
        return 1

    # Initialize GStreamer
    if not Gst.init_check(None):
        logger.error("Failed to initialize GStreamer.")
        print("Error: Cannot initialize GStreamer.", file=sys.stderr)
        return 1

    logger.debug("GTK and GStreamer initialized successfully")

    # Create the application
    app = MusicPlayerApp()

    # Register early to detect if another instance is running
    try:
        app.register(None)
        if app.get_is_remote():
            # Another instance is already running
            logger.info(
                "Another instance of Music Player is already running. "
                "Activating existing window."
            )
            print(
                "Another instance is already running. Activating existing window.",
                file=sys.stderr,
            )
    except Exception as e:
        logger.debug("Could not register application early: %s", e)

    # Run the application
    exit_code = app.run(sys.argv)

    if exit_code == 0:
        logger.info("Music Player exited normally")
    else:
        logger.warning("Music Player exited with code %d", exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
