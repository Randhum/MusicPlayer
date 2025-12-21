"""Library browser component - sidebar with artist/album/track tree."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GObject
from typing import Optional, Callable
from core.metadata import TrackMetadata


class LibraryBrowser(Gtk.Box):
    """Sidebar component for browsing music library."""
    
    __gsignals__ = {
        'track-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'album-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.set_size_request(250, -1)
        
        # Header
        header = Gtk.Label(label="Library")
        header.add_css_class("title-2")
        self.append(header)
        
        # Scrolled window for tree view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        
        # Tree store: (name, type, data)
        # type: 'artist', 'album', 'track'
        # data: artist name, album name, or TrackMetadata
        self.store = Gtk.TreeStore(str, str, object)
        
        # Tree view
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(False)
        self.tree_view.connect('row-activated', self._on_row_activated)
        
        # Column
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Library", renderer, text=0)
        self.tree_view.append_column(column)
        
        scrolled.set_child(self.tree_view)
        self.append(scrolled)
    
    def populate(self, library):
        """Populate the tree with library data."""
        self.store.clear()
        
        artists = library.get_artists()
        for artist_name in artists:
            artist_iter = self.store.append(None, [artist_name, 'artist', artist_name])
            
            albums = library.get_albums(artist_name)
            for album_name in albums:
                album_iter = self.store.append(artist_iter, [album_name, 'album', album_name])
                
                tracks = library.get_tracks(artist_name, album_name)
                for track in tracks:
                    track_name = track.title or "Unknown Track"
                    self.store.append(album_iter, [track_name, 'track', track])
    
    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click)."""
        model = tree_view.get_model()
        tree_iter = model.get_iter(path)
        if tree_iter:
            name, item_type, data = model.get(tree_iter, 0, 1, 2)
            
            if item_type == 'track' and isinstance(data, TrackMetadata):
                self.emit('track-selected', data)
            elif item_type == 'album':
                # Select all tracks in album
                album_iter = tree_iter
                tracks = []
                child = model.iter_children(album_iter)
                while child:
                    _, child_type, child_data = model.get(child, 0, 1, 2)
                    if child_type == 'track' and isinstance(child_data, TrackMetadata):
                        tracks.append(child_data)
                    child = model.iter_next(child)
                if tracks:
                    self.emit('album-selected', tracks)

