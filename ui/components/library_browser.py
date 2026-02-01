"""Library browser component - sidebar with artist/album/track tree."""

from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from core.music_library import MusicLibrary
    from ui.components.playlist_view import PlaylistView
    from ui.components.player_controls import PlayerControls

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from core.logging import get_logger
from core.metadata import TrackMetadata

logger = get_logger(__name__)


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
        self.scrolled = Gtk.ScrolledWindow()
        self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scrolled.set_vexpand(True)  # Make scrolled window expand vertically

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

        # Music root path (set when populating) for fallback folder path from tree
        self._music_root: Optional[Path] = None

        # Single-click expand/collapse state
        self._click_timeout_id = None
        self._click_in_progress = False

        # Column
        column = Gtk.TreeViewColumn("Library")
        renderer = Gtk.CellRendererText()
        renderer.set_padding(8, 12)  # Add padding for touch-friendliness
        column.pack_start(renderer, True)
        column.add_attribute(renderer, "text", 0)
        column.set_expand(True)
        column.set_resizable(True)
        self.tree_view.append_column(column)

        self.scrolled.set_child(self.tree_view)
        self.append(self.scrolled)

    def populate(self, library: "MusicLibrary") -> None:
        """Populate the tree with folder structure."""
        self.store.clear()

        folder_structure = library.get_folder_structure()
        music_root = library.get_music_root()

        if not folder_structure or not music_root:
            self._music_root = None
            return

        # Build folder tree structure
        self._music_root = Path(music_root)
        folder_tree = {}
        root_path = self._music_root

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

        # Populate tree view recursively from folder_tree (root has no folder row)
        self._populate_tree(None, folder_tree, None, root_path)

    def _populate_tree(
        self,
        parent_iter,
        folder_tree: dict,
        folder_name: Optional[str],
        folder_path: Path,
    ) -> None:
        """Recursively populate tree view from folder structure."""
        if folder_name is not None:
            folder_iter = self.store.append(
                parent_iter, [folder_name, "folder", str(folder_path)]
            )
        else:
            folder_iter = parent_iter  # root: no row, children attach to parent

        # Tracks in this folder (root-level tracks use parent_iter None)
        if "tracks" in folder_tree:
            target = folder_iter if folder_iter is not None else parent_iter
            for track in folder_tree["tracks"]:
                track_name = track.title or Path(track.file_path).stem
                self.store.append(target, [track_name, "track", track])

        # Recurse into subfolders
        for key, value in sorted(folder_tree.items()):
            if key != "tracks":
                subfolder_path = folder_path / key
                self._populate_tree(
                    folder_iter if folder_iter is not None else parent_iter,
                    value,
                    key,
                    subfolder_path,
                )

    def _on_click_pressed(self, gesture, n_press, x, y):
        """Handle click press - mark that a click is in progress."""
        # Note: We'll get the actual path from selection in the timeout handler
        # GTK handles selection correctly (accounting for scroll offset),
        # while get_path_at_pos with gesture coordinates may have offset issues
        self._click_in_progress = True

    def _on_click_released(self, gesture, n_press, x, y):
        """Handle click release - expand/collapse on single click after delay."""
        # Cancel any pending timeout
        if self._click_timeout_id:
            GLib.source_remove(self._click_timeout_id)
            self._click_timeout_id = None

        # Only handle single clicks (n_press == 1)
        if n_press == 1 and getattr(self, "_click_in_progress", False):
            # Delay to allow double-click to cancel it
            self._click_timeout_id = GLib.timeout_add(250, self._expand_collapse_folder)

        self._click_in_progress = False

    def _expand_collapse_folder(self):
        """Expand or collapse folder after single-click delay."""
        self._click_timeout_id = None

        selection = self.tree_view.get_selection()
        _, tree_iter = selection.get_selected()

        if tree_iter:
            name, item_type, data = self.store.get(tree_iter, 0, 1, 2)

            # Only handle folders for expand/collapse
            if item_type == "folder":
                path = self.store.get_path(tree_iter)
                if self.tree_view.row_expanded(path):
                    self.tree_view.collapse_row(path)
                else:
                    self.tree_view.expand_row(path, False)

        return False  # Don't repeat

    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click).

        - Track: tree stores TrackMetadata in column 2. We replace playlist with
          that track and play it via playlist_view, or emit "track-selected" if
          no playlist_view (e.g. standalone tests).
        - Folder: tree stores folder path string in column 2. We pass that path
          to playlist_view.replace_and_play_folder(path), which replaces the
          playlist with folder contents (from disk) and plays. If there is no
          playlist_view we collect tracks from the tree and emit "album-selected".
          If data is not a string (legacy/defensive), we collect tracks from the
          tree and call replace_and_play_album(tracks) or emit.
        """
        # Cancel any pending single-click expand/collapse
        if self._click_timeout_id:
            GLib.source_remove(self._click_timeout_id)
            self._click_timeout_id = None
        self._click_in_progress = False

        tree_iter = self.store.get_iter(path)
        if not tree_iter:
            return

        name, item_type, data = self.store.get(tree_iter, 0, 1, 2)

        if item_type == "track" and isinstance(data, TrackMetadata):
            if self.playlist_view:
                self.playlist_view.replace_and_play_track(data)
            else:
                self.emit("track-selected", data)
            return

        if item_type != "folder":
            return

        # Folder: we store folder path (str) in data; use it for replace_and_play_folder
        if data and isinstance(data, str):
            if self.playlist_view:
                self.playlist_view.replace_and_play_folder(data)
            else:
                tracks = []
                self._collect_tracks(self.store, tree_iter, tracks)
                if tracks:
                    self.emit("album-selected", tracks)
            return

        # Fallback if data is not a path string: collect tracks from tree
        tracks = []
        self._collect_tracks(self.store, tree_iter, tracks)
        if tracks:
            if self.playlist_view:
                self.playlist_view.replace_and_play_album(tracks)
            else:
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

    def _get_folder_path_from_iter(self, folder_iter) -> Optional[Path]:
        """Build full folder path from tree row by walking up to root. Returns None if no music root."""
        if self._music_root is None:
            return None
        parent = self.store.iter_parent(folder_iter)
        name = self.store.get(folder_iter, 0)[0]
        if parent is None:
            return self._music_root / name
        parent_path = self._get_folder_path_from_iter(parent)
        return (parent_path / name) if parent_path else None

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
        """Show context menu for the row at the given position.

        Uses the tree view's model (self.store): row at (x,y) via get_path_at_pos,
        else current selection. Stores selected_path and row data for the menu.
        """
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if path_info:
            path = path_info[0]
            tree_iter = self.store.get_iter(path)
        else:
            tree_iter = None
        if not tree_iter:
            selection = self.tree_view.get_selection()
            _, tree_iter = selection.get_selected()
        if not tree_iter:
            return

        self.selected_path = self.store.get_path(tree_iter)
        name, item_type, data = self.store.get(tree_iter, 0, 1, 2)

        self._show_context_menu(item_type, data, x, y)

    def _show_context_menu(self, item_type: str, data, x: float, y: float):
        """Show context menu for the selected item."""
        # Prevent multiple menus
        if self._menu_showing:
            return

        # Properly close and remove old menu if exists
        if self.context_menu:
            try:
                # Disconnect signal first to prevent recursive cleanup
                try:
                    self.context_menu.disconnect_by_func(self._on_popover_closed)
                except (TypeError, AttributeError):
                    # Signal not connected or widget destroyed
                    pass
                # Close the popover
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
            # Unparent and destroy the old popover completely
            try:
                parent = self.context_menu.get_parent()
                if parent is not None:
                    self.context_menu.unparent()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed or already unparented
                pass
            # Clear reference - this ensures we create a fresh popover
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

            add_item = Gtk.Button(label="Add Track to Playlist")
            add_item.add_css_class("flat")
            add_item.set_size_request(150, 40)  # Larger for touch
            add_item.connect("clicked", lambda w: self._on_menu_add_track(data))
            menu_box.append(add_item)

        elif item_type == "folder":
            # Folder menu - use folder path for MOC native append
            folder_path = data if isinstance(data, str) else None

            if folder_path:
                # Use folder path directly (MOC will handle recursively)
                play_item = Gtk.Button(label="Play Folder")
                play_item.add_css_class("flat")
                play_item.set_size_request(150, 40)  # Larger for touch
                play_item.connect(
                    "clicked",
                    lambda w, path=folder_path: self._on_menu_play_folder(path),
                )
                menu_box.append(play_item)

                add_item = Gtk.Button(label="Add Folder to Playlist")
                add_item.add_css_class("flat")
                add_item.set_size_request(150, 40)  # Larger for touch
                add_item.connect(
                    "clicked",
                    lambda w, path=folder_path: self._on_menu_add_folder(path),
                )
                menu_box.append(add_item)
            else:
                # Fallback: folder path not in data; get path from tree so MOC can append by path
                folder_iter = self.store.get_iter(self.selected_path) if self.selected_path else None
                tracks = []
                if folder_iter:
                    self._collect_tracks(self.store, folder_iter, tracks)
                folder_path_from_tree = (
                    self._get_folder_path_from_iter(folder_iter) if folder_iter else None
                )

                if tracks:
                    play_item = Gtk.Button(label="Play Folder")
                    play_item.add_css_class("flat")
                    play_item.set_size_request(150, 40)  # Larger for touch
                    play_item.connect(
                        "clicked", lambda w: self._on_menu_play_album(tracks)
                    )
                    menu_box.append(play_item)

                    add_item = Gtk.Button(label="Add Folder to Playlist")
                    add_item.add_css_class("flat")
                    add_item.set_size_request(150, 40)  # Larger for touch
                    if folder_path_from_tree:
                        add_item.connect(
                            "clicked",
                            lambda w, p=str(folder_path_from_tree): self._on_menu_add_folder(p),
                        )
                    else:
                        add_item.connect(
                            "clicked", lambda w: self._on_menu_add_album(tracks)
                        )
                    menu_box.append(add_item)

        # Set child first (must be done before setting parent)
        self.context_menu.set_child(menu_box)

        # Set parent - must be done after child is set
        # In GTK4, Popover should be parented to the scrolled window containing the tree view
        # This avoids CSS node conflicts when the tree view is inside a scrolled window
        try:
            self.context_menu.set_parent(self.scrolled)
        except (AttributeError, RuntimeError) as e:
            # If setting parent fails, we can't show the menu
            logger.warning("Failed to set popover parent: %s", e)
            self._menu_showing = False
            self.context_menu = None
            return

        # Connect to closed signal for cleanup (after parent is set)
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

    def _on_menu_play_folder(self, folder_path: str):
        """Handle 'Play Folder' from context menu using folder path."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.replace_and_play_folder(folder_path)

    def _on_menu_add_folder(self, folder_path: str):
        """Handle 'Add Folder to Playlist' from context menu using folder path."""
        self._close_menu()
        if self.playlist_view:
            self.playlist_view.add_folder(folder_path)

    def _close_menu(self):
        """Close the context menu safely."""
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
        self._menu_showing = False
