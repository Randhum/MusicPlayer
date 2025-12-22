"""Library browser window."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from ui.components.library_browser import LibraryBrowser
from core.metadata import TrackMetadata


class LibraryWindow(Gtk.ApplicationWindow):
    """Window for browsing the music library."""
    
    def __init__(self, app, application):
        super().__init__(application=app)
        self.application = application
        self.set_title("Music Library")
        self.set_default_size(400, 600)
        
        # Create UI
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Library browser component
        self.library_browser = LibraryBrowser()
        self.library_browser.connect('track-selected', self._on_track_selected)
        self.library_browser.connect('album-selected', self._on_album_selected)
        self.library_browser.connect('add-track', self._on_add_track)
        self.library_browser.connect('add-album', self._on_add_album)
        main_box.append(self.library_browser)
        
        # Populate if library is already scanned
        if self.application.library.get_track_count() > 0:
            self.library_browser.populate(self.application.library)
    
    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection (double-click) - add to playlist and play."""
        # Add track to playlist
        self.application.add_track_to_playlist(track)
        # Set as current and play
        playlist = self.application.playlist_manager.get_playlist()
        self.application.playlist_manager.set_current_index(len(playlist) - 1)
        self.application.play_current_track()
    
    def _on_album_selected(self, browser, tracks):
        """Handle album selection (double-click) - add all tracks to playlist and play."""
        # Add tracks to playlist
        self.application.add_tracks_to_playlist(tracks)
        # Set first track as current and play
        playlist = self.application.playlist_manager.get_playlist()
        self.application.playlist_manager.set_current_index(len(playlist) - len(tracks))
        self.application.play_current_track()
    
    def _on_add_track(self, browser, track: TrackMetadata):
        """Handle adding track to playlist from context menu."""
        self.application.add_track_to_playlist(track)
    
    def _on_add_album(self, browser, tracks):
        """Handle adding album to playlist from context menu."""
        self.application.add_tracks_to_playlist(tracks)
    
    def refresh_library(self):
        """Refresh the library display."""
        self.library_browser.populate(self.application.library)

