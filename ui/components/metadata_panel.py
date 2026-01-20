"""Metadata panel component - displays now playing information."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from typing import Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("GObject", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)


class MetadataPanel(Gtk.Box):
    """Component for displaying track metadata and album art."""

    def __init__(self, event_bus: Optional[EventBus] = None) -> None:
        """
        Initialize metadata panel.

        Creates UI elements for displaying track information and album art
        with lazy loading support.

        Args:
            event_bus: Optional EventBus instance for subscribing to track changes
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_size_request(250, -1)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(10)
        self.set_margin_bottom(10)

        # Subscribe to track changes
        if event_bus:
            event_bus.subscribe(EventBus.TRACK_CHANGED, self._on_track_changed)

        # Album art (lazy loaded)
        self.art_image = Gtk.Picture.new_for_filename(None)
        self.art_image.set_content_fit(Gtk.ContentFit.COVER)
        self.art_image.set_size_request(200, 200)
        self.art_image.add_css_class("album-art")
        self.append(self.art_image)

        # Track pending art path for lazy loading
        self._pending_art_path: Optional[str] = None

        # Connect to visibility changes for lazy loading
        self.connect("notify::visible", self._on_visibility_changed)

        # Track info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)

        self.title_label = Gtk.Label(label="")
        self.title_label.add_css_class("title-1")
        self.title_label.set_wrap(True)
        self.title_label.set_halign(Gtk.Align.START)
        info_box.append(self.title_label)

        self.artist_label = Gtk.Label(label="")
        self.artist_label.add_css_class("title-3")
        self.artist_label.set_wrap(True)
        self.artist_label.set_halign(Gtk.Align.START)
        info_box.append(self.artist_label)

        self.album_label = Gtk.Label(label="")
        self.album_label.add_css_class("subtitle")
        self.album_label.set_wrap(True)
        self.album_label.set_halign(Gtk.Align.START)
        info_box.append(self.album_label)

        # Additional info
        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        details_box.set_margin_top(10)

        self.genre_label = Gtk.Label(label="")
        self.genre_label.set_halign(Gtk.Align.START)
        details_box.append(self.genre_label)

        self.year_label = Gtk.Label(label="")
        self.year_label.set_halign(Gtk.Align.START)
        details_box.append(self.year_label)

        info_box.append(details_box)

        self.append(info_box)

    def _on_track_changed(self, data: Optional[dict]) -> None:
        """Handle track changed event."""
        if data and "track" in data:
            self.set_track(data["track"])
        else:
            self.set_track(None)

    def set_track(self, track: Optional[TrackMetadata]):
        """Update display with track metadata."""
        if not track:
            self._clear()
            return

        # Lazy load album art - only load when visible
        # Clear first to avoid showing wrong art
        self.art_image.set_filename(None)

        # Set album art lazily (only when panel is visible)
        if track.album_art_path and self.get_visible():
            self._load_album_art(track.album_art_path)
        elif track.album_art_path:
            # Store path for later loading
            self._pending_art_path = track.album_art_path
        else:
            self._pending_art_path = None

        # Set text labels - use filename as fallback for title
        from pathlib import Path

        title = track.title or Path(track.file_path).stem
        self.title_label.set_text(title)
        self.artist_label.set_text(track.artist or "Unknown Artist")
        self.album_label.set_text(track.album or "Unknown Album")

        # Additional info
        genre_text = f"Genre: {track.genre}" if track.genre else ""
        self.genre_label.set_text(genre_text)

        year_text = f"Year: {track.year}" if track.year else ""
        self.year_label.set_text(year_text)

    def _load_album_art(self, art_path: str) -> None:
        """
        Load album art (lazy loading).

        Args:
            art_path: Path to album art image file
        """
        try:
            self.art_image.set_filename(art_path)
        except Exception as e:
            logger.error("Error loading album art: %s", e, exc_info=True)
            self.art_image.set_filename(None)

    def _on_visibility_changed(
        self, widget: Gtk.Widget, param: GObject.ParamSpec
    ) -> None:
        """
        Handle visibility changes for lazy loading.

        Args:
            widget: Widget that changed visibility
            param: GObject parameter specification
        """
        if self.get_visible() and self._pending_art_path:
            self._load_album_art(self._pending_art_path)
            self._pending_art_path = None

    def _clear(self) -> None:
        """Clear all displayed information and reset state."""
        self.art_image.set_filename(None)
        self.title_label.set_text("")
        self.artist_label.set_text("")
        self.album_label.set_text("")
        self.genre_label.set_text("")
        self.year_label.set_text("")
        self._pending_art_path = None
