"""Playlist view component - shows current queue/playlist."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, GObject, Gdk
from typing import Optional, Callable, List
from core.metadata import TrackMetadata


class PlaylistView(Gtk.Box):
    """Component for displaying the current playlist/queue."""
    
    __gsignals__ = {
        'track-activated': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'remove-track': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'move-track-up': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'move-track-down': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'clear-playlist': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'save-playlist': (GObject.SignalFlags.RUN_FIRST, None, ()),
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
        # Add CSS class for touch-friendly styling
        self.tree_view.add_css_class("playlist-tree")
        
        # Add right-click gesture for context menu
        gesture = Gtk.GestureClick()
        gesture.set_button(3)  # Right mouse button
        gesture.connect('pressed', self._on_right_click)
        self.tree_view.add_controller(gesture)
        
        # Context menu
        self.context_menu = None
        self.selected_index = -1
        self.set_vexpand(True)  # Expand to fill available vertical space
        
        # Columns with touch-friendly padding
        col_index = Gtk.TreeViewColumn("#")
        renderer_index = Gtk.CellRendererText()
        renderer_index.set_padding(8, 12)  # Add padding for touch-friendliness
        col_index.pack_start(renderer_index, True)
        col_index.add_attribute(renderer_index, "text", 0)
        col_index.set_min_width(50)
        col_index.set_resizable(False)
        self.tree_view.append_column(col_index)
        
        col_title = Gtk.TreeViewColumn("Title")
        renderer_title = Gtk.CellRendererText()
        renderer_title.set_padding(8, 12)  # Add padding for touch-friendliness
        col_title.pack_start(renderer_title, True)
        col_title.add_attribute(renderer_title, "text", 1)
        col_title.set_expand(True)
        col_title.set_resizable(True)
        self.tree_view.append_column(col_title)
        
        col_artist = Gtk.TreeViewColumn("Artist")
        renderer_artist = Gtk.CellRendererText()
        renderer_artist.set_padding(8, 12)  # Add padding for touch-friendliness
        col_artist.pack_start(renderer_artist, True)
        col_artist.add_attribute(renderer_artist, "text", 2)
        col_artist.set_expand(True)
        col_artist.set_resizable(True)
        self.tree_view.append_column(col_artist)
        
        col_duration = Gtk.TreeViewColumn("Duration")
        renderer_duration = Gtk.CellRendererText()
        renderer_duration.set_padding(8, 12)  # Add padding for touch-friendliness
        col_duration.pack_start(renderer_duration, True)
        col_duration.add_attribute(renderer_duration, "text", 3)
        col_duration.set_min_width(80)
        col_duration.set_resizable(False)
        self.tree_view.append_column(col_duration)
        
        scrolled.set_child(self.tree_view)
        scrolled.set_vexpand(True)
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
        selection = self.tree_view.get_selection()
        selection.unselect_all()
        
        if 0 <= self.current_index < len(self.tracks):
            path = Gtk.TreePath.new_from_indices([self.current_index])
            selection.select_path(path)
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
    
    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click to show context menu."""
        # Get the path at click position
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if path_info:
            path, column, cell_x, cell_y = path_info
            indices = path.get_indices()
            if indices:
                self.selected_index = indices[0]
        else:
            self.selected_index = -1
        
        self._show_context_menu(x, y)
    
    def _show_context_menu(self, x: float, y: float):
        """Show context menu."""
        # Remove old menu if exists
        if self.context_menu:
            self.context_menu.unparent()
        
        # Create popover
        self.context_menu = Gtk.Popover()
        self.context_menu.set_parent(self.tree_view)
        
        # Create menu box with touch-friendly spacing
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        menu_box.set_margin_start(10)
        menu_box.set_margin_end(10)
        menu_box.set_margin_top(10)
        menu_box.set_margin_bottom(10)
        
        if self.selected_index >= 0:
            # Track-specific menu items
            play_item = Gtk.Button(label="Play")
            play_item.add_css_class("flat")
            play_item.set_size_request(150, 40)  # Larger for touch
            play_item.connect('clicked', lambda w: self._on_menu_play())
            menu_box.append(play_item)
            
            remove_item = Gtk.Button(label="Remove")
            remove_item.add_css_class("flat")
            remove_item.set_size_request(150, 40)  # Larger for touch
            remove_item.connect('clicked', lambda w: self._on_menu_remove())
            menu_box.append(remove_item)
            
            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            
            move_up_item = Gtk.Button(label="Move Up")
            move_up_item.add_css_class("flat")
            move_up_item.set_size_request(150, 40)  # Larger for touch
            move_up_item.connect('clicked', lambda w: self._on_menu_move_up())
            move_up_item.set_sensitive(self.selected_index > 0)
            menu_box.append(move_up_item)
            
            move_down_item = Gtk.Button(label="Move Down")
            move_down_item.add_css_class("flat")
            move_down_item.set_size_request(150, 40)  # Larger for touch
            move_down_item.connect('clicked', lambda w: self._on_menu_move_down())
            move_down_item.set_sensitive(self.selected_index < len(self.tracks) - 1)
            menu_box.append(move_down_item)
            
            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # General menu items
        clear_item = Gtk.Button(label="Clear Playlist")
        clear_item.add_css_class("flat")
        clear_item.set_size_request(150, 40)  # Larger for touch
        clear_item.connect('clicked', lambda w: self._on_menu_clear())
        clear_item.set_sensitive(len(self.tracks) > 0)
        menu_box.append(clear_item)
        
        save_item = Gtk.Button(label="Save Playlist...")
        save_item.add_css_class("flat")
        save_item.set_size_request(150, 40)  # Larger for touch
        save_item.connect('clicked', lambda w: self._on_menu_save())
        save_item.set_sensitive(len(self.tracks) > 0)
        menu_box.append(save_item)
        
        self.context_menu.set_child(menu_box)
        
        # Position and show menu
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self.context_menu.set_pointing_to(rect)
        self.context_menu.popup()
    
    def _on_menu_play(self):
        """Handle 'Play' from context menu."""
        self.context_menu.popdown()
        if self.selected_index >= 0:
            self.emit('track-activated', self.selected_index)
    
    def _on_menu_remove(self):
        """Handle 'Remove' from context menu."""
        self.context_menu.popdown()
        if self.selected_index >= 0:
            self.emit('remove-track', self.selected_index)
    
    def _on_menu_move_up(self):
        """Handle 'Move Up' from context menu."""
        self.context_menu.popdown()
        if self.selected_index > 0:
            self.emit('move-track-up', self.selected_index)
    
    def _on_menu_move_down(self):
        """Handle 'Move Down' from context menu."""
        self.context_menu.popdown()
        if self.selected_index < len(self.tracks) - 1:
            self.emit('move-track-down', self.selected_index)
    
    def _on_menu_clear(self):
        """Handle 'Clear Playlist' from context menu."""
        self.context_menu.popdown()
        self.emit('clear-playlist')
    
    def _on_menu_save(self):
        """Handle 'Save Playlist' from context menu."""
        self.context_menu.popdown()
        self.emit('save-playlist')

