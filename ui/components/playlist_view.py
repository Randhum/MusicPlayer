"""Playlist view component - shows current queue/playlist."""

from pathlib import Path
from typing import Optional, Callable, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GObject, Gdk, GLib

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
        'refresh-playlist': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        
        # Header with action buttons
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.set_margin_start(5)
        header_box.set_margin_end(5)
        header_box.set_margin_top(5)
        header_box.set_margin_bottom(5)
        
        header_label = Gtk.Label(label="Playlist")
        header_label.add_css_class("title-2")
        header_label.set_halign(Gtk.Align.START)
        header_label.set_hexpand(True)
        header_box.append(header_label)
        
        # Action buttons
        self.refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_button.set_tooltip_text("Refresh from MOC")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.set_size_request(36, 36)  # Touch-friendly size
        self.refresh_button.connect('clicked', lambda w: self.emit('refresh-playlist'))
        header_box.append(self.refresh_button)
        
        self.clear_button = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_button.set_tooltip_text("Clear Playlist")
        self.clear_button.add_css_class("flat")
        self.clear_button.set_size_request(36, 36)  # Touch-friendly size
        self.clear_button.connect('clicked', lambda w: self.emit('clear-playlist'))
        header_box.append(self.clear_button)
        
        self.save_button = Gtk.Button.new_from_icon_name("document-save-symbolic")
        self.save_button.set_tooltip_text("Save Playlist")
        self.save_button.add_css_class("flat")
        self.save_button.set_size_request(36, 36)  # Touch-friendly size
        self.save_button.connect('clicked', lambda w: self.emit('save-playlist'))
        header_box.append(self.save_button)
        
        self.append(header_box)
        
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
        right_click_gesture = Gtk.GestureClick()
        right_click_gesture.set_button(3)  # Right mouse button
        right_click_gesture.connect('pressed', self._on_right_click)
        self.tree_view.add_controller(right_click_gesture)
        
        # Add long-press gesture for context menu (touch-friendly)
        long_press_gesture = Gtk.GestureLongPress()
        long_press_gesture.set_touch_only(True)  # Only for touch, not mouse
        long_press_gesture.connect('pressed', self._on_long_press)
        self.tree_view.add_controller(long_press_gesture)
        
        # Context menu
        self.context_menu = None
        self.selected_index = -1
        self._menu_showing = False  # Flag to prevent multiple menus
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
    
    def set_moc_mode(self, enabled: bool):
        """Show or hide the Refresh button based on whether MOC mode is active."""
        self.refresh_button.set_visible(enabled)
    
    def _update_button_states(self):
        """Update the state of action buttons based on playlist content."""
        has_tracks = len(self.tracks) > 0
        self.clear_button.set_sensitive(has_tracks)
        self.save_button.set_sensitive(has_tracks)
    
    def set_current_index(self, index: int):
        """Set the currently playing track index."""
        self.current_index = index
        self._update_selection()
    
    def _update_view(self):
        """Update the tree view with current tracks."""
        self.store.clear()
        for i, track in enumerate(self.tracks):
            # Use filename as fallback if title is missing
            title = track.title or Path(track.file_path).stem
            artist = track.artist or "Unknown Artist"
            duration = self._format_duration(track.duration) if track.duration else "--:--"
            self.store.append([i + 1, title, artist, duration])
        self._update_selection()
        # Update button states
        self._update_button_states()
    
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
        # Only show menu if not already showing
        if not self._menu_showing:
            self._show_context_menu_at_position(x, y)
    
    def _on_long_press(self, gesture, x, y):
        """Handle long-press to show context menu (touch-friendly)."""
        # Only show menu if not already showing
        if not self._menu_showing:
            self._show_context_menu_at_position(x, y)
    
    def _show_context_menu_at_position(self, x, y):
        """Show context menu at the given position."""
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
        # Prevent multiple menus
        if self._menu_showing:
            return
        
        # Properly close and remove old menu if exists
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
            try:
                if self.context_menu.get_parent():
                    self.context_menu.unparent()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
            self.context_menu = None
        
        # Set flag to prevent multiple menus
        self._menu_showing = True
        
        # Create popover
        self.context_menu = Gtk.Popover()
        # Set child first, then parent
        self.context_menu.set_has_arrow(True)
        
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
        
        # Set child before parent
        self.context_menu.set_child(menu_box)
        
        # Set parent after child is set
        self.context_menu.set_parent(self.tree_view)
        
        # Connect to closed signal for cleanup
        self.context_menu.connect('closed', self._on_popover_closed)
        
        # Position and show menu
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self.context_menu.set_pointing_to(rect)
        self.context_menu.popup()
    
    def _on_popover_closed(self, popover):
        """Handle popover closed signal for cleanup."""
        # Reset flag immediately
        self._menu_showing = False
        # Clean up after a short delay to avoid issues
        GLib.timeout_add(100, self._cleanup_popover)
    
    def _cleanup_popover(self):
        """Clean up the popover properly."""
        if self.context_menu:
            try:
                # Check if widget is still valid and has a parent
                parent = self.context_menu.get_parent()
                if parent is not None:
                    self.context_menu.unparent()
            except (AttributeError, RuntimeError):
                # Widget might have been destroyed already
                pass
            finally:
                self.context_menu = None
        # Ensure flag is reset
        self._menu_showing = False
        return False  # Don't repeat
    
    def _on_menu_play(self):
        """Handle 'Play' from context menu."""
        self._close_menu()
        if self.selected_index >= 0:
            self.emit('track-activated', self.selected_index)
    
    def _on_menu_remove(self):
        """Handle 'Remove' from context menu."""
        self._close_menu()
        if self.selected_index >= 0:
            self.emit('remove-track', self.selected_index)
    
    def _on_menu_move_up(self):
        """Handle 'Move Up' from context menu."""
        self._close_menu()
        if self.selected_index > 0:
            self.emit('move-track-up', self.selected_index)
    
    def _on_menu_move_down(self):
        """Handle 'Move Down' from context menu."""
        self._close_menu()
        if self.selected_index < len(self.tracks) - 1:
            self.emit('move-track-down', self.selected_index)
    
    def _on_menu_clear(self):
        """Handle 'Clear Playlist' from context menu."""
        self._close_menu()
        self.emit('clear-playlist')
    
    def _on_menu_save(self):
        """Handle 'Save Playlist' from context menu."""
        self._close_menu()
        self.emit('save-playlist')
    
    def _close_menu(self):
        """Close the context menu safely."""
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
        self._menu_showing = False

