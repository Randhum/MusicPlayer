"""Playlist view window."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from ui.components.playlist_view import PlaylistView
from core.metadata import TrackMetadata


class PlaylistWindow(Gtk.ApplicationWindow):
    """Window for viewing and managing the playlist."""
    
    def __init__(self, app, application):
        super().__init__(application=app)
        self.application = application
        self.set_title("Playlist")
        self.set_default_size(600, 500)
        
        # Create UI
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Playlist view component
        self.playlist_view = PlaylistView()
        self.playlist_view.connect('track-activated', self._on_track_activated)
        main_box.append(self.playlist_view)
        
        # Update with current playlist
        tracks = self.application.playlist_manager.get_playlist()
        current_index = self.application.playlist_manager.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
    
    def _on_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.application.playlist_manager.set_current_index(index)
        self.application.play_current_track()
    
    def update_playlist(self, tracks, current_index):
        """Update the playlist display."""
        self.playlist_view.set_playlist(tracks, current_index)

