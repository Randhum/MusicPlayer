#!/usr/bin/env python3
"""Music Player - main entry point. Event-driven; PlaylistManager + PlaybackController."""
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Gst, Gio
try:
    gi.require_version("Adw", "1")
    from gi.repository import Adw
    USE_ADW = True
except ValueError:
    USE_ADW = False
from typing import Optional, Any
from core.config import get_config
from core.logging import get_logger, LinuxLogger
from core.metadata import TrackMetadata
from ui.main_window import MainWindow

logger = get_logger(__name__)
APPLICATION_ID = "com.musicplayer.app"


class MusicPlayerApp(Adw.Application if USE_ADW else Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APPLICATION_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)
        self.window: Optional[MainWindow] = None

    def do_startup(self) -> None:
        if USE_ADW:
            Adw.Application.do_startup(self)
        else:
            Gtk.Application.do_startup(self)
        logger.info("Music Player starting up")

    def _on_activate(self, app: Gtk.Application) -> None:
        if not self.window:
            self.window = MainWindow(app)
        self.window.present()

    def _on_open(self, app: Gtk.Application, files: Any, n_files: int, hint: str) -> None:
        if not self.window:
            self.window = MainWindow(app)
        for file_info in files:
            path = file_info.get_path()
            if path:
                self.window.playlist_view.add_track(TrackMetadata(path))
        self.window.present()


def main() -> int:
    config = get_config()
    LinuxLogger(log_dir=config.log_dir)
    if not Gtk.init_check():
        logger.error("Failed to initialize GTK.")
        print("Error: Cannot initialize GTK. Is a display server running?", file=sys.stderr)
        return 1
    if not Gst.init_check(None):
        logger.error("Failed to initialize GStreamer.")
        print("Error: Cannot initialize GStreamer.", file=sys.stderr)
        return 1
    app = MusicPlayerApp()
    try:
        app.register(None)
        if app.get_is_remote():
            logger.info("Another instance already running.")
    except Exception:
        pass
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
