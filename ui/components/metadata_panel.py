"""Metadata panel component - displays now playing information."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from core.metadata import TrackMetadata
from core.logging import get_logger

logger = get_logger(__name__)


class MetadataPanel(Gtk.Box):
    """Component for displaying track metadata and album art."""
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_size_request(250, -1)
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(10)
        self.set_margin_bottom(10)
        
        # Album art
        self.art_image = Gtk.Picture.new_for_filename(None)
        self.art_image.set_content_fit(Gtk.ContentFit.COVER)
        self.art_image.set_size_request(200, 200)
        self.art_image.add_css_class("album-art")
        self.append(self.art_image)
        
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
    
    def set_track(self, track: TrackMetadata):
        """Update display with track metadata."""
        if not track:
            self._clear()
            return
        
        # Set album art
        if track.album_art_path:
            try:
                self.art_image.set_filename(track.album_art_path)
            except Exception as e:
                logger.error("Error loading album art: %s", e, exc_info=True)
                self.art_image.set_filename(None)
        else:
            self.art_image.set_filename(None)
        
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
    
    def _clear(self):
        """Clear the display."""
        self.art_image.set_filename(None)
        self.title_label.set_text("")
        self.artist_label.set_text("")
        self.album_label.set_text("")
        self.genre_label.set_text("")
        self.year_label.set_text("")

