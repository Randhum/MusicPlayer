"""Metadata panel component - displays now playing information."""

from typing import Optional

import gi

gi.require_version("GObject", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

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
        self._event_bus = event_bus
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
        
        # Track current track to detect changes
        self._current_track: Optional[TrackMetadata] = None

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
    
    def sync_with_state(self, current_track: Optional[TrackMetadata]) -> None:
        """
        Sync metadata panel with current track state.
        
        Call this after initialization to ensure panel shows current track
        if one is already playing.
        
        Args:
            current_track: Current track (e.g. from TRACK_CHANGED event), or None
        """
        if current_track:
            self.set_track(current_track)

    def _on_track_changed(self, data: Optional[dict]) -> None:
        """Handle track changed event - always updates labels to ensure they stay in sync."""
        try:
            if data and "track" in data:
                track = data["track"]
                # Always update, even if it's the same track object (metadata might have changed)
                # This ensures labels always reflect the current state
                self.set_track(track)
            else:
                # Track was cleared
                self.set_track(None)
        except Exception as e:
            logger.error("Error updating metadata panel: %s", e, exc_info=True)
            # On error, at least clear the display to avoid showing stale data
            self._clear()

    def set_track(self, track: Optional[TrackMetadata]):
        """Update display with track metadata."""
        if not track:
            self._current_track = None
            self._clear()
            return

        # Check if track actually changed (by file path) to avoid unnecessary art reloads
        # But always update labels (metadata might have been updated)
        old_track = self._current_track
        track_changed = (
            not old_track
            or not hasattr(old_track, 'file_path')
            or not hasattr(track, 'file_path')
            or (old_track.file_path != track.file_path)
        )
        
        # Check if album art path changed (before we update _current_track)
        old_art_path = getattr(old_track, 'album_art_path', None) if old_track else None
        new_art_path = getattr(track, 'album_art_path', None)
        art_path_changed = track_changed or (old_art_path != new_art_path)
        
        # Store current track (after checking for changes)
        self._current_track = track

        # Always update labels (even if same track - metadata might have been updated)
        from pathlib import Path

        # Handle missing file_path gracefully
        if not track.file_path:
            title = track.title or "Unknown Track"
        else:
            title = track.title or Path(track.file_path).stem
        
        self.title_label.set_text(title)
        self.artist_label.set_text(track.artist or "Unknown Artist")
        self.album_label.set_text(track.album or "Unknown Album")

        # Additional info
        genre_text = f"Genre: {track.genre}" if track.genre else ""
        self.genre_label.set_text(genre_text)

        year_text = f"Year: {track.year}" if track.year else ""
        self.year_label.set_text(year_text)

        # Update album art only if track changed or art path changed
        # This avoids unnecessary reloads of the same art
        if art_path_changed:
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
        self._current_track = None
