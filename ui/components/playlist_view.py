"""Playlist view component - shows current queue/playlist."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GObject
from typing import Optional, Callable, List
from core.metadata import TrackMetadata


class PlaylistView(Gtk.Box):
    """Component for displaying the current playlist/queue."""
    
    __gsignals__ = {
        'track-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        
        # Header
        header = Gtk.Label(label="Playlist")
        header.add_css_class("title-2")
        self.append(header)
        
        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        # List store: (index, title, artist, duration)
        self.store = Gtk.ListStore(int, str, str, str)
        
        # Tree view
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(True)
        self.tree_view.connect('row-activated', self._on_row_activated)
        
        # Columns
        renderer = Gtk.CellRendererText()
        
        col_index = Gtk.TreeViewColumn("#", renderer, text=0)
        col_index.set_min_width(40)
        self.tree_view.append_column(col_index)
        
        col_title = Gtk.TreeViewColumn("Title", renderer, text=1)
        col_title.set_expand(True)
        self.tree_view.append_column(col_title)
        
        col_artist = Gtk.TreeViewColumn("Artist", renderer, text=2)
        col_artist.set_expand(True)
        self.tree_view.append_column(col_artist)
        
        col_duration = Gtk.TreeViewColumn("Duration", renderer, text=3)
        col_duration.set_min_width(80)
        self.tree_view.append_column(col_duration)
        
        scrolled.set_child(self.tree_view)
        self.append(scrolled)
        
        self.tracks: List[TrackMetadata] = []
        self.current_index: int = -1
    
    def set_playlist(self, tracks: List[TrackMetadata], current_index: int = -1):
        """Set the playlist tracks."""
        self.tracks = tracks
        self.current_index = current_index
        self._update_view()
    
    def set_current_index(self, index: int):
        """Set the currently playing track index."""
        self.current_index = index
        self._update_selection()
    
    def _update_view(self):
        """Update the tree view with current tracks."""
        self.store.clear()
        for i, track in enumerate(self.tracks):
            title = track.title or "Unknown Track"
            artist = track.artist or "Unknown Artist"
            duration = self._format_duration(track.duration) if track.duration else "--:--"
            self.store.append([i + 1, title, artist, duration])
        self._update_selection()
    
    def _update_selection(self):
        """Update the selection to highlight current track."""
        if 0 <= self.current_index < len(self.tracks):
            path = Gtk.TreePath.new_from_indices([self.current_index])
            self.tree_view.set_cursor(path, None, False)
            self.tree_view.scroll_to_cell(path, None, False, 0.0, 0.0)
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click)."""
        indices = path.get_indices()
        if indices:
            index = indices[0]
            self.emit('track-activated', index)

