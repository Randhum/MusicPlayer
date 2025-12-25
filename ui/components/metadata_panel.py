"""Metadata panel component - displays now playing information."""

import threading
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

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
        
        # Container for album art with placeholder (using Stack to switch between them)
        self.art_stack = Gtk.Stack()
        self.art_stack.set_size_request(200, 200)
        self.art_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.art_stack.set_transition_duration(200)
        
        # Album art
        self.art_image = Gtk.Picture.new_for_filename(None)
        self.art_image.set_content_fit(Gtk.ContentFit.COVER)
        self.art_image.set_size_request(200, 200)
        self.art_image.add_css_class("album-art")
        self.art_stack.add_child(self.art_image)
        self.art_stack.set_visible_child(self.art_image)
        
        # Placeholder for when no art is available
        self.placeholder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.placeholder_box.set_size_request(200, 200)
        self.placeholder_box.add_css_class("album-art-placeholder")
        self.placeholder_box.set_valign(Gtk.Align.CENTER)
        self.placeholder_box.set_halign(Gtk.Align.CENTER)
        
        # Music icon in placeholder
        self.placeholder_icon = Gtk.Image.new_from_icon_name("audio-x-generic-symbolic")
        self.placeholder_icon.set_pixel_size(64)
        self.placeholder_icon.add_css_class("placeholder-icon")
        self.placeholder_box.append(self.placeholder_icon)
        
        # Placeholder text
        self.placeholder_label = Gtk.Label(label="No Cover Art")
        self.placeholder_label.add_css_class("placeholder-text")
        self.placeholder_label.set_margin_top(10)
        self.placeholder_box.append(self.placeholder_label)
        
        self.art_stack.add_child(self.placeholder_box)
        self.append(self.art_stack)
        
        # Track for automatic fetching
        self.current_track: Optional[TrackMetadata] = None
        self._fetching_metadata = False
        
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
        
        self.current_track = track
        
        # Set album art
        if track.album_art_path:
            try:
                self.art_image.set_filename(track.album_art_path)
                self.art_stack.set_visible_child(self.art_image)
            except Exception as e:
                logger.error("Error loading album art: %s", e, exc_info=True)
                self._show_placeholder()
        else:
            self._show_placeholder()
            # Try to fetch metadata automatically in background
            if not self._fetching_metadata:
                self._fetch_metadata_async(track)
        
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
    
    def _show_placeholder(self):
        """Show the placeholder instead of album art."""
        self.art_stack.set_visible_child(self.placeholder_box)
    
    def _fetch_metadata_async(self, track: TrackMetadata):
        """Fetch metadata asynchronously in the background."""
        if self._fetching_metadata:
            return
        
        self._fetching_metadata = True
        
        def fetch_in_thread():
            """Fetch metadata in a background thread."""
            try:
                from core.metadata_fetcher import MetadataFetcher
                fetcher = MetadataFetcher()
                
                # Only fetch if we have at least title or artist
                if not track.title and not track.artist:
                    return None
                
                metadata = fetcher.fetch_metadata(
                    title=track.title,
                    artist=track.artist,
                    album=track.album,
                    duration=track.duration
                )
                
                return metadata
            except Exception as e:
                logger.error("Error fetching metadata: %s", e, exc_info=True)
                return None
            finally:
                self._fetching_metadata = False
        
        def on_metadata_fetched(metadata):
            """Callback when metadata is fetched."""
            if metadata and self.current_track == track:
                # Update track with fetched metadata
                if metadata.get('album_art_path') and not track.album_art_path:
                    track.album_art_path = metadata['album_art_path']
                    # Update display
                    try:
                        self.art_image.set_filename(track.album_art_path)
                        self.art_stack.set_visible_child(self.art_image)
                        logger.info("Updated album art from online source")
                    except Exception as e:
                        logger.error("Error loading fetched album art: %s", e)
                
                # Update other metadata if missing
                if metadata.get('title') and not track.title:
                    track.title = metadata['title']
                    self.title_label.set_text(metadata['title'])
                
                if metadata.get('artist') and not track.artist:
                    track.artist = metadata['artist']
                    self.artist_label.set_text(metadata['artist'])
                
                if metadata.get('album') and not track.album:
                    track.album = metadata['album']
                    self.album_label.set_text(metadata['album'])
        
        # Run in background thread
        def run_fetch():
            metadata = fetch_in_thread()
            if metadata:
                GLib.idle_add(on_metadata_fetched, metadata)
        
        thread = threading.Thread(target=run_fetch, daemon=True)
        thread.start()
    
    def _clear(self):
        """Clear the display."""
        self.art_image.set_filename(None)
        self.title_label.set_text("")
        self.artist_label.set_text("")
        self.album_label.set_text("")
        self.genre_label.set_text("")
        self.year_label.set_text("")

