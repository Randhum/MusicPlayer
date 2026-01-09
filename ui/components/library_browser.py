"""Library browser component - sidebar with artist/album/track tree."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from core.music_library import MusicLibrary
    from ui.components.playlist_view import PlaylistView
    from ui.components.player_controls import PlayerControls

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.metadata import TrackMetadata


class LibraryBrowser(Gtk.Box):
    """Sidebar component for browsing music library."""

    __gsignals__ = {
        "track-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "album-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(
        self,
        playlist_view: Optional["PlaylistView"] = None,
        player_controls: Optional["PlayerControls"] = None,
    ):
        """
        Initialize library browser.

        Args:
            playlist_view: Optional PlaylistView instance for adding tracks
            player_controls: Optional PlayerControls instance for playback coordination
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.set_size_request(300, -1)
        self.set_vexpand(True)  # Expand to fill available vertical space
        self.playlist_view = playlist_view
        self.player_controls = player_controls

        # Header
        header = Gtk.Label(label="Library")
        header.add_css_class("title-2")
        self.append(header)

        # Scrolled window for tree view
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)  # Make scrolled window expand vertically

        # Tree store: (name, type, data)
        # type: 'folder', 'track'
        # data: folder path or TrackMetadata
        self.store = Gtk.TreeStore(str, str, object)

        # Tree view
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(False)
        self.tree_view.connect("row-activated", self._on_row_activated)

        # Add gesture for single-click expand/collapse
        # We'll use a timeout to distinguish single from double clicks
        click_gesture = Gtk.GestureClick()
        click_gesture.set_button(1)  # Left mouse button
        click_gesture.connect("pressed", self._on_click_pressed)
        click_gesture.connect("released", self._on_click_released)
        self.tree_view.add_controller(click_gesture)

        # Set row height for touch-friendliness
        self.tree_view.set_row_separator_func(None)
        # Use CSS to set minimum row height
        self.tree_view.add_css_class("library-tree")

        # Add right-click gesture for context menu
        right_click_gesture = Gtk.GestureClick()
        right_click_gesture.set_button(3)  # Right mouse button
        right_click_gesture.connect("pressed", self._on_right_click)
        self.tree_view.add_controller(right_click_gesture)

        # Add long-press gesture for context menu (touch-friendly)
        long_press_gesture = Gtk.GestureLongPress()
        long_press_gesture.set_touch_only(True)  # Only for touch, not mouse
        long_press_gesture.connect("pressed", self._on_long_press)
        self.tree_view.add_controller(long_press_gesture)

        # Context menu
        self.context_menu = None
        self.selected_path = None
        self._menu_showing = False  # Flag to prevent multiple menus

        # Single-click expand/collapse state
        self._click_timeout_id = None
        self._click_path = None

        # Column
        column = Gtk.TreeViewColumn("Library")
        renderer = Gtk.CellRendererText()
        renderer.set_padding(8, 12)  # Add padding for touch-friendliness
        column.pack_start(renderer, True)
        column.add_attribute(renderer, "text", 0)
        column.set_expand(True)
        column.set_resizable(True)
        self.tree_view.append_column(column)

        scrolled.set_child(self.tree_view)
        self.append(scrolled)

    def populate(self, library: "MusicLibrary") -> None:
        """Populate the tree with folder structure."""
        self.store.clear()

        folder_structure = library.get_folder_structure()
        music_root = library.get_music_root()

        if not folder_structure or not music_root:
            return

        # Build folder tree structure
        folder_tree = {}
        root_path = Path(music_root)

        # Sort folder paths to maintain order
        sorted_folders = sorted(folder_structure.keys())

        # Create folder hierarchy
        for folder_path in sorted_folders:
            # Get folder parts (folder_path is relative to music_root)
            # Handle "." (current directory) as root
            if folder_path and folder_path != ".":
                parts = Path(folder_path).parts
            else:
                parts = []

            # Build tree structure
            current = folder_tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Store tracks for this folder
            if "tracks" not in current:
                current["tracks"] = []
            current["tracks"].extend(folder_structure[folder_path])

        # Populate tree view directly from folder_tree contents (skip root folder name)
        # Start from top-level items in the music directory
        for key, value in sorted(folder_tree.items()):
            if key != "tracks":
                self._populate_tree(None, value, key)

        # Also add root-level tracks if any
        if "tracks" in folder_tree:
            for track in folder_tree["tracks"]:
                track_name = track.title or Path(track.file_path).stem
                self.store.append(None, [track_name, "track", track])

    def _populate_tree(self, parent_iter, folder_tree, folder_name):
        """Recursively populate tree view from folder structure."""
        # Add folder node
        folder_iter = self.store.append(parent_iter, [folder_name, "folder", None])

        # Add tracks in this folder
        if "tracks" in folder_tree:
            for track in folder_tree["tracks"]:
                track_name = track.title or Path(track.file_path).stem
                self.store.append(folder_iter, [track_name, "track", track])

        # Add subfolders
        for key, value in sorted(folder_tree.items()):
            if key != "tracks":
                self._populate_tree(folder_iter, value, key)

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle click press - store path for potential expand/collapse."""
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if path_info:
            self._click_path = path_info[0]
        else:
            self._click_path = None

    def _on_click_released(self, gesture, n_press, x, y):
        """Handle click release - expand/collapse on single click after delay."""
        # Cancel any pending timeout
        if self._click_timeout_id:
            GLib.source_remove(self._click_timeout_id)
            self._click_timeout_id = None

        # Only handle single clicks (n_press == 1)
        if n_press == 1 and self._click_path:
            # Delay to allow double-click to cancel it
            self._click_timeout_id = GLib.timeout_add(250, self._expand_collapse_folder)

    def _expand_collapse_folder(self):
        """Expand or collapse folder after single-click delay."""
        self._click_timeout_id = None

        if not self._click_path:
            return False

        model = self.tree_view.get_model()
        tree_iter = model.get_iter(self._click_path)

        if tree_iter:
            name, item_type, data = model.get(tree_iter, 0, 1, 2)

            # Only handle folders for expand/collapse
            if item_type == "folder":
                if self.tree_view.row_expanded(self._click_path):
                    self.tree_view.collapse_row(self._click_path)
                else:
                    self.tree_view.expand_row(self._click_path, False)

        self._click_path = None
        return False  # Don't repeat

    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click)."""
        # Cancel any pending single-click expand/collapse
        if self._click_timeout_id:
            GLib.source_remove(self._click_timeout_id)
            self._click_timeout_id = None
            self._click_path = None

        model = tree_view.get_model()
        tree_iter = model.get_iter(path)
        if tree_iter:
            name, item_type, data = model.get(tree_iter, 0, 1, 2)

            if item_type == "track" and isinstance(data, TrackMetadata):
                if self.playlist_view:
                    self.playlist_view.replace_and_play_track(data)
                else:
                    # Fallback to signal if playlist_view not available
                    self.emit("track-selected", data)
            elif item_type == "folder":
                # Select all tracks in folder (recursively)
                folder_iter = tree_iter
                tracks = []
                self._collect_tracks(model, folder_iter, tracks)
                if tracks:
                    if self.playlist_view:
                        self.playlist_view.replace_and_play_album(tracks)
                    else:
                        # Fallback to signal if playlist_view not available
                        self.emit("album-selected", tracks)

    def _collect_tracks(self, model, parent_iter, tracks):
        """Recursively collect all tracks from a folder."""
        child = model.iter_children(parent_iter)
        while child:
            _, child_type, child_data = model.get(child, 0, 1, 2)
            if child_type == "track" and isinstance(child_data, TrackMetadata):
                tracks.append(child_data)
            elif child_type == "folder":
                # Recursively collect from subfolders
                self._collect_tracks(model, child, tracks)
            child = model.iter_next(child)

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

        # Create menu box
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        menu_box.set_margin_start(10)
        menu_box.set_margin_end(10)
        menu_box.set_margin_top(10)
        menu_box.set_margin_bottom(10)

        if item_type == "track" and isinstance(data, TrackMetadata):
            # Track menu
            play_item = Gtk.Button(label="Play Now")
            play_item.add_css_class("flat")
            play_item.set_size_request(150, 40)  # Larger for touch
            play_item.connect("clicked", lambda w: self._on_menu_play_track(data))
            menu_box.append(play_item)

            add_item = Gtk.Button(label="Add to Playlist")
            add_item.add_css_class("flat")
            add_item.set_size_request(150, 40)  # Larger for touch
            add_item.connect("clicked", lambda w: self._on_menu_add_track(data))
            menu_box.append(add_item)

        elif item_type == "folder":
            # Folder menu - get all tracks recursively
            folder_iter = self.tree_view.get_model().get_iter(self.selected_path)
            tracks = []
            self._collect_tracks(self.store, folder_iter, tracks)

            if tracks:
                play_item = Gtk.Button(label="Play Folder")
                play_item.add_css_class("flat")
                play_item.set_size_request(150, 40)  # Larger for touch
                play_item.connect("clicked", lambda w: self._on_menu_play_album(tracks))
                menu_box.append(play_item)

                add_item = Gtk.Button(label="Add Folder to Playlist")
                add_item.add_css_class("flat")
                add_item.set_size_request(150, 40)  # Larger for touch
                add_item.connect("clicked", lambda w: self._on_menu_add_album(tracks))
                menu_box.append(add_item)

        # Set child before parent
        self.context_menu.set_child(menu_box)

        # Set parent after child is set
        self.context_menu.set_parent(self.tree_view)

        # Connect to closed signal for cleanup
        self.context_menu.connect("closed", self._on_popover_closed)

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

    def _on_menu_play_track(self, track: TrackMetadata):
        """Handle 'Play Now' from context menu."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.replace_and_play_track(track)
        else:
            # Fallback to signal if playlist_view not available
            self.emit("track-selected", track)

    def _on_menu_add_track(self, track: TrackMetadata):
        """Handle 'Add to Playlist' from context menu."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.add_track(track)

    def _on_menu_play_album(self, tracks):
        """Handle 'Play Album' from context menu."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.replace_and_play_album(tracks)
        else:
            # Fallback to signal if playlist_view not available
            self.emit("album-selected", tracks)

    def _on_menu_add_album(self, tracks):
        """Handle 'Add Album to Playlist' from context menu."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.add_tracks(tracks)

    def _close_menu(self):
        """Close the context menu safely."""
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
        self._menu_showing = False
