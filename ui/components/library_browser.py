"""Library browser component - sidebar with artist/album/track tree."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, GObject, Gdk
from typing import Optional, Callable
from core.metadata import TrackMetadata


class LibraryBrowser(Gtk.Box):
    """Sidebar component for browsing music library."""
    
    __gsignals__ = {
        'track-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'album-selected': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'add-track': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'add-album': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.set_size_request(30, -1)
        
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
        
        # Add right-click gesture for context menu
        gesture = Gtk.GestureClick()
        gesture.set_button(3)  # Right mouse button
        gesture.connect('pressed', self._on_right_click)
        self.tree_view.add_controller(gesture)
        
        # Context menu
        self.context_menu = None
        self.selected_path = None
        
        # Column
        column = Gtk.TreeViewColumn("Library")
        renderer = Gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.add_attribute(renderer, "text", 0)
        column.set_expand(True)
        column.set_resizable(True)
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
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click to show context menu."""
        # Get the path at click position
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if not path_info:
            return
        
        path, column, cell_x, cell_y = path_info
        self.selected_path = path
        
        # Get the item type and data
        model = self.tree_view.get_model()
        tree_iter = model.get_iter(path)
        if not tree_iter:
            return
        
        name, item_type, data = model.get(tree_iter, 0, 1, 2)
        
        # Create context menu
        self._show_context_menu(item_type, data, x, y)
    
    def _show_context_menu(self, item_type: str, data, x: float, y: float):
        """Show context menu for the selected item."""
        # Remove old menu if exists
        if self.context_menu:
            self.context_menu.unparent()
        
        # Create popover
        self.context_menu = Gtk.Popover()
        self.context_menu.set_parent(self.tree_view)
        
        # Create menu box
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        menu_box.set_margin_start(5)
        menu_box.set_margin_end(5)
        menu_box.set_margin_top(5)
        menu_box.set_margin_bottom(5)
        
        if item_type == 'track' and isinstance(data, TrackMetadata):
            # Track menu
            play_item = Gtk.Button(label="Play Now")
            play_item.connect('clicked', lambda w: self._on_menu_play_track(data))
            menu_box.append(play_item)
            
            add_item = Gtk.Button(label="Add to Playlist")
            add_item.connect('clicked', lambda w: self._on_menu_add_track(data))
            menu_box.append(add_item)
            
        elif item_type == 'album':
            # Album menu - get all tracks
            album_iter = self.tree_view.get_model().get_iter(self.selected_path)
            tracks = []
            child = self.store.iter_children(album_iter)
            while child:
                _, child_type, child_data = self.store.get(child, 0, 1, 2)
                if child_type == 'track' and isinstance(child_data, TrackMetadata):
                    tracks.append(child_data)
                child = self.store.iter_next(child)
            
            if tracks:
                play_item = Gtk.Button(label="Play Album")
                play_item.connect('clicked', lambda w: self._on_menu_play_album(tracks))
                menu_box.append(play_item)
                
                add_item = Gtk.Button(label="Add Album to Playlist")
                add_item.connect('clicked', lambda w: self._on_menu_add_album(tracks))
                menu_box.append(add_item)
        
        self.context_menu.set_child(menu_box)
        
        # Position and show menu
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self.context_menu.set_pointing_to(rect)
        self.context_menu.popup()
    
    def _on_menu_play_track(self, track: TrackMetadata):
        """Handle 'Play Now' from context menu."""
        self.context_menu.popdown()
        self.emit('track-selected', track)
    
    def _on_menu_add_track(self, track: TrackMetadata):
        """Handle 'Add to Playlist' from context menu."""
        self.context_menu.popdown()
        self.emit('add-track', track)
    
    def _on_menu_play_album(self, tracks):
        """Handle 'Play Album' from context menu."""
        self.context_menu.popdown()
        self.emit('album-selected', tracks)
    
    def _on_menu_add_album(self, tracks):
        """Handle 'Add Album to Playlist' from context menu."""
        self.context_menu.popdown()
        self.emit('add-album', tracks)

