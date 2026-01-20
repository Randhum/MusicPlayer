"""Playlist view component - shows current queue/playlist."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
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
from core.app_state import AppState
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.playlist_manager import PlaylistManager

logger = get_logger(__name__)


class PlaylistView(Gtk.Box):
    """Component for displaying the current playlist/queue."""

    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "current-index-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(
        self,
        app_state: AppState,
        event_bus: EventBus,
        playlist_manager: PlaylistManager,
        window: Optional[Gtk.Window] = None,
    ):
        """
        Initialize playlist view.

        Args:
            app_state: AppState instance for reading playlist state
            event_bus: EventBus instance for publishing actions and subscribing to events
            playlist_manager: PlaylistManager instance for file persistence (save/load)
            window: Optional Gtk.Window instance for dialog parents
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self._state = app_state
        self._events = event_bus
        self.playlist_manager = playlist_manager  # Only for file persistence
        self.window = window

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
        self.refresh_button.connect("clicked", lambda w: self._handle_refresh())
        header_box.append(self.refresh_button)

        self.clear_button = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self.clear_button.set_tooltip_text("Clear Playlist")
        self.clear_button.add_css_class("flat")
        self.clear_button.set_size_request(36, 36)  # Touch-friendly size
        self.clear_button.connect("clicked", lambda w: self._handle_clear())
        header_box.append(self.clear_button)

        self.save_button = Gtk.Button.new_from_icon_name("document-save-symbolic")
        self.save_button.set_tooltip_text("Save Playlist")
        self.save_button.add_css_class("flat")
        self.save_button.set_size_request(36, 36)  # Touch-friendly size
        self.save_button.connect("clicked", lambda w: self._show_save_dialog())
        header_box.append(self.save_button)

        self.load_button = Gtk.Button.new_from_icon_name("document-open-symbolic")
        self.load_button.set_tooltip_text("Load Saved Playlist")
        self.load_button.add_css_class("flat")
        self.load_button.set_size_request(36, 36)  # Touch-friendly size
        self.load_button.connect("clicked", lambda w: self._show_load_dialog())
        header_box.append(self.load_button)

        self.append(header_box)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        # List store: (index, title, artist, duration)
        self.store = Gtk.ListStore(int, str, str, str)

        # Tree view
        self.tree_view = Gtk.TreeView(model=self.store)
        self.tree_view.set_headers_visible(True)
        self.tree_view.connect("row-activated", self._on_row_activated)
        # Add CSS class for touch-friendly styling
        self.tree_view.add_css_class("playlist-tree")

        # Add right-click gesture for context menu
        right_click_gesture = Gtk.GestureClick()
        right_click_gesture.set_button(3)  # Right mouse button
        right_click_gesture.connect("pressed", self._on_right_click)
        self.tree_view.add_controller(right_click_gesture)

        # Add left-click gesture for selection (works better than GestureDrag for coordinates)
        left_click_gesture = Gtk.GestureClick()
        left_click_gesture.set_button(1)  # Left mouse button
        left_click_gesture.connect("pressed", self._on_left_click_pressed)
        self.tree_view.add_controller(left_click_gesture)

        # Add drag gesture for long-press-to-reorder
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.set_button(1)  # Left mouse button
        drag_gesture.connect("drag-begin", self._on_drag_begin)
        drag_gesture.connect("drag-update", self._on_drag_update)
        drag_gesture.connect("drag-end", self._on_drag_end)
        self.tree_view.add_controller(drag_gesture)

        # Store selected row from left-click for use in drag-begin
        self._click_selected_index = -1

        # Playback state
        self._playback_in_progress = False  # Guard to prevent concurrent playback
        self._playback_lock = False  # Prevent concurrent play_track_at_index calls

        # Single-tap behavior configuration
        # True = single tap plays track, False = single tap only selects (double-tap to play)
        self._single_tap_plays = False

        # Tap/double-tap detection state
        self._tap_pending = False  # True when waiting for potential double-tap
        self._tap_timeout_id = None  # GLib timeout source ID
        self._pending_tap_index = -1  # Index of track for pending single-tap
        self._double_tap_window = 300  # ms to wait for second tap

        # Drag-to-reorder state
        self._drag_mode = False  # True when long-press activated drag mode
        self._drag_source_index = -1  # Index of row being dragged
        self._drag_target_index = -1  # Index where row will be dropped
        self._drag_start_time = (
            0  # Timestamp when drag started (for long-press detection)
        )
        self._long_press_threshold = 500000  # 500ms in microseconds
        self._drop_target_index = -1  # Index of row being highlighted as drop target

        # Context menu
        self.context_menu = None
        self.selected_index = -1
        self._menu_showing = False  # Flag to prevent multiple menus
        self.set_vexpand(True)  # Expand to fill available vertical space

        # Blinking highlight for current playing track when another row is selected
        self._blink_timeout_id = None
        self._blink_state = False  # Toggle state for blinking
        self._row_css_classes = {}  # Track CSS classes per row path
        self._setup_blinking_highlight()

        # Columns with touch-friendly padding
        col_index = Gtk.TreeViewColumn("#")
        renderer_index = Gtk.CellRendererText()
        renderer_index.set_padding(8, 12)  # Add padding for touch-friendliness
        col_index.pack_start(renderer_index, True)
        col_index.add_attribute(renderer_index, "text", 0)
        col_index.set_cell_data_func(renderer_index, self._cell_data_func)
        col_index.set_min_width(50)
        col_index.set_resizable(False)
        self.tree_view.append_column(col_index)

        col_title = Gtk.TreeViewColumn("Title")
        renderer_title = Gtk.CellRendererText()
        renderer_title.set_padding(8, 12)  # Add padding for touch-friendliness
        col_title.pack_start(renderer_title, True)
        col_title.add_attribute(renderer_title, "text", 1)
        col_title.set_cell_data_func(renderer_title, self._cell_data_func)
        col_title.set_expand(True)
        col_title.set_resizable(True)
        self.tree_view.append_column(col_title)

        col_artist = Gtk.TreeViewColumn("Artist")
        renderer_artist = Gtk.CellRendererText()
        renderer_artist.set_padding(8, 12)  # Add padding for touch-friendliness
        col_artist.pack_start(renderer_artist, True)
        col_artist.add_attribute(renderer_artist, "text", 2)
        col_artist.set_cell_data_func(renderer_artist, self._cell_data_func)
        col_artist.set_expand(True)
        col_artist.set_resizable(True)
        self.tree_view.append_column(col_artist)

        col_duration = Gtk.TreeViewColumn("Duration")
        renderer_duration = Gtk.CellRendererText()
        renderer_duration.set_padding(8, 12)  # Add padding for touch-friendliness
        col_duration.pack_start(renderer_duration, True)
        col_duration.add_attribute(renderer_duration, "text", 3)
        col_duration.set_cell_data_func(renderer_duration, self._cell_data_func)
        col_duration.set_min_width(80)
        col_duration.set_resizable(False)
        self.tree_view.append_column(col_duration)

        scrolled.set_child(self.tree_view)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        # Shuffle queue is managed by PlaybackController, not here

        # Subscribe to playlist changes
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)
        self._events.subscribe(
            EventBus.CURRENT_INDEX_CHANGED, self._on_current_index_changed
        )
        self._events.subscribe(EventBus.SHUFFLE_CHANGED, self._on_shuffle_changed)

        # Initialize UI from state
        self._sync_from_state()

    # ============================================================================
    # Public API - State Reading (Wrapper methods for PlaylistManager)
    # ============================================================================

    def get_playlist(self) -> List[TrackMetadata]:
        """Get the current playlist from AppState."""
        return self._state.playlist

    def get_current_index(self) -> int:
        """Get the current track index from AppState."""
        return self._state.current_index

    def get_current_track(self) -> Optional[TrackMetadata]:
        """Get the currently playing track from AppState."""
        return self._state.current_track

    def get_next_track(self) -> Optional[TrackMetadata]:
        """
        Get the next track from AppState (sequential only).

        Note: Shuffle logic is handled by PlaybackController, not here.
        """
        playlist = self._state.playlist
        current_index = self._state.current_index
        if current_index < len(playlist) - 1:
            return playlist[current_index + 1]
        return None

    def get_previous_track(self) -> Optional[TrackMetadata]:
        """
        Get the previous track from AppState.

        Note: In shuffle mode, previous track behavior is not well-defined,
        so this returns the sequential previous track regardless of shuffle state.
        """
        playlist = self._state.playlist
        current_index = self._state.current_index
        if current_index > 0:
            return playlist[current_index - 1]
        return None

    def set_shuffle_enabled(self, enabled: bool):
        """Enable or disable shuffle mode."""
        self._state.set_shuffle_enabled(enabled)
        # Shuffle queue is managed by PlaybackController

    def get_shuffle_enabled(self) -> bool:
        """Get current shuffle state."""
        return self._state.shuffle_enabled

    # ============================================================================
    # Public API - State Updates
    # ============================================================================

    def set_playlist(self, tracks: List[TrackMetadata], current_index: int = -1):
        """
        Set the playlist tracks and update the view.

        This method updates AppState and the visual representation.
        Note: This is called by event handlers when playlist changes.
        """
        # Update state (this will trigger events)
        self._state.set_playlist(tracks, current_index)
        # Shuffle queue regeneration is handled by PlaybackController
        self._update_view()

    def set_current_index(self, index: int):
        """
        Set the currently playing track index.

        Updates AppState and the UI view.
        In shuffle mode, removes the index from the shuffle queue if present.
        """
        old_index = self._state.current_index
        self._state.set_current_index(index)
        # Shuffle queue management is handled by PlaybackController
        self._update_selection()
        # Emit signal for external coordination (if needed)
        if old_index != index:
            self.emit("current-index-changed", index)

    # ============================================================================
    # Public API - Playlist Operations (Wrapper methods that update both data and UI)
    # ============================================================================

    def add_track(self, track: TrackMetadata, position: Optional[int] = None):
        """Add a track to the playlist (updates AppState and UI)."""
        self._state.add_track(track, position)
        # Also update playlist_manager for persistence
        self.playlist_manager.add_track(track, position)
        # Shuffle queue regeneration is handled by PlaybackController
        self._update_view()

    def add_tracks(self, tracks: List[TrackMetadata]):
        """Add multiple tracks to the playlist (updates AppState and UI)."""
        for track in tracks:
            self._state.add_track(track)
            self.playlist_manager.add_track(track)
        # Shuffle queue regeneration is handled by PlaybackController
        self._update_view()

    def remove_track(self, index: int):
        """Remove a track from the playlist (updates AppState and UI)."""
        self._state.remove_track(index)
        self.playlist_manager.remove_track(index)
        # Shuffle queue regeneration is handled by PlaybackController
        self._update_view()

    def move_track(self, from_index: int, to_index: int):
        """Move a track in the playlist (updates AppState and UI)."""
        self._state.move_track(from_index, to_index)
        
        # Optimize UI update: move the row in the store instead of rebuilding everything
        if from_index != to_index and 0 <= from_index < len(self.store) and 0 <= to_index < len(self.store):
            try:
                from_path = Gtk.TreePath.new_from_indices([from_index])
                from_iter = self.store.get_iter(from_path)
                
                if from_iter:
                    # Get the row data
                    row_data = list(self.store[from_iter])
                    # Remove from old position
                    self.store.remove(from_iter)
                    
                    # Insert at new position
                    if to_index > from_index:
                        # Moving down - target index decreased by 1 after removal
                        to_path = Gtk.TreePath.new_from_indices([to_index - 1])
                    else:
                        # Moving up
                        to_path = Gtk.TreePath.new_from_indices([to_index])
                    
                    to_iter = self.store.get_iter(to_path) if to_path else None
                    
                    if to_iter:
                        self.store.insert_before(to_iter, row_data)
                    else:
                        # Fallback: append if insert fails
                        self.store.append(row_data)
                    
                    # Update row numbers efficiently
                    self._update_row_numbers()
                    self._update_selection()
                    self._update_button_states()
                else:
                    # Fallback: full update if iter access fails
                    self._update_view()
            except (ValueError, AttributeError, RuntimeError):
                # Fallback: full update on any error
                self._update_view()
        else:
            # Fallback: full update if indices invalid
            self._update_view()
        
        # Defer file sync to avoid blocking UI (run in idle callback)
        GLib.idle_add(self._sync_playlist_manager_move, from_index, to_index)

    def clear(self):
        """Clear the playlist (updates AppState and UI)."""
        self._state.clear_playlist()
        self.playlist_manager.clear()
        # Shuffle queue clearing is handled by PlaybackController
        self._update_view()

    def _handle_clear(self):
        """Handle clear operation."""
        # Publish stop action
        self._events.publish(EventBus.ACTION_STOP)
        # Clear playlist
        self.clear()

    def save_playlist(self, name: str) -> bool:
        """Save the current playlist."""
        return self.playlist_manager.save_playlist(name)

    def load_playlist(self, name: str) -> bool:
        """Load a saved playlist (updates data and UI)."""
        result = self.playlist_manager.load_playlist(name)
        if result:
            # Sync loaded playlist from PlaylistManager to AppState and UI
            tracks = self.playlist_manager.get_playlist()
            current_index = self.playlist_manager.get_current_index()
            self.set_playlist(tracks, current_index)
        return result

    def list_playlists(self) -> List[str]:
        """List all saved playlists."""
        return self.playlist_manager.list_playlists()

    # ============================================================================
    # Public API - High-Level Playback Operations
    # ============================================================================

    def play_track_at_index(self, index: int) -> None:
        """Play track at the given index - publishes action event."""
        # Prevent concurrent calls from gesture + row-activated
        if self._playback_lock:
            return

        playlist = self._state.playlist
        if not 0 <= index < len(playlist):
            return

        self._playback_lock = True

        # Set index first
        self._state.set_current_index(index)

        # Publish play track action
        self._events.publish(EventBus.ACTION_PLAY_TRACK, {"index": index})

        # Emit signal for external coordination
        self.emit("track-activated", index)

        # Release lock after 500ms
        GLib.timeout_add(500, self._release_playback_lock)

    def replace_and_play_track(self, track: TrackMetadata) -> None:
        """Replace playlist with single track and play it."""
        self.clear()
        self.add_track(track)
        # play_track_at_index will set the index and publish action
        self.play_track_at_index(0)

    def replace_and_play_album(self, tracks: List[TrackMetadata]) -> None:
        """Replace playlist with album tracks and play first track."""
        self.clear()
        self.add_tracks(tracks)
        # play_track_at_index will set the index and publish action
        self.play_track_at_index(0)

    def add_folder(self, folder_path: str) -> None:
        """
        Add a folder to the playlist.

        If MOC is active, uses MOC's native folder append (recursively adds all tracks).
        Otherwise, falls back to collecting tracks and adding individually.

        Args:
            folder_path: Path to the folder to add.
        """
        if self._state.active_backend == "moc":
            # Use MOC's native folder append via event
            self._events.publish(
                EventBus.ACTION_APPEND_FOLDER, {"folder_path": folder_path}
            )
        else:
            # Fallback: collect tracks and add individually
            folder = Path(folder_path)
            if not folder.exists() or not folder.is_dir():
                return
            tracks = []
            for ext in ["*.mp3", "*.ogg", "*.flac", "*.m4a", "*.wav", "*.opus"]:
                tracks.extend([TrackMetadata(str(p)) for p in folder.rglob(ext)])
            if tracks:
                self.add_tracks(tracks)

    def replace_and_play_folder(self, folder_path: str) -> None:
        """
        Replace playlist with folder contents and play first track.

        If MOC is active, uses MOC's native folder append (recursively adds all tracks).
        Otherwise, falls back to collecting tracks and adding individually.

        Args:
            folder_path: Path to the folder to play.
        """
        self.clear()
        if self._state.active_backend == "moc":
            # Use MOC's native folder append via event
            self._events.publish(
                EventBus.ACTION_APPEND_FOLDER, {"folder_path": folder_path}
            )
            # Wait a moment for MOC to process, then play first track
            GLib.timeout_add(300, lambda: self.play_track_at_index(0) or False)
        else:
            # Fallback: collect tracks and add individually
            folder = Path(folder_path)
            if not folder.exists() or not folder.is_dir():
                return
            tracks = []
            for ext in ["*.mp3", "*.ogg", "*.flac", "*.m4a", "*.wav", "*.opus"]:
                tracks.extend([TrackMetadata(str(p)) for p in folder.rglob(ext)])
            if tracks:
                self.add_tracks(tracks)
                self.play_track_at_index(0)

    # ============================================================================
    # UI Configuration
    # ============================================================================

    def set_moc_mode(self, enabled: bool):
        """Show or hide the Refresh button based on whether MOC mode is active."""
        self.refresh_button.set_visible(enabled)

    # ============================================================================
    # Internal Methods
    # ============================================================================

    def _sync_from_state(self):
        """Sync the view from AppState."""
        # Shuffle queue is managed by PlaybackController
        self._update_view()

    def _on_playlist_changed(self, data: Optional[dict]) -> None:
        """Handle playlist changed event."""
        if data:
            tracks = data.get("tracks", [])
            index = data.get("index", -1)
            # Shuffle queue regeneration is handled by PlaybackController
            self._update_view()

    def _on_current_index_changed(self, data: Optional[dict]) -> None:
        """Handle current index changed event."""
        if data:
            index = data.get("index", -1)
            self._update_selection()

    def _on_shuffle_changed(self, data: Optional[dict]) -> None:
        """Handle shuffle changed event."""
        if data:
            enabled = data.get("enabled", False)
            self.set_shuffle_enabled(enabled)

    def _update_row_numbers(self):
        """Update row numbers in the store after a move operation."""
        # Update the index column (column 0) for all rows
        for i in range(len(self.store)):
            path = Gtk.TreePath.new_from_indices([i])
            tree_iter = self.store.get_iter(path)
            if tree_iter:
                self.store.set_value(tree_iter, 0, i + 1)
    
    def _sync_playlist_manager_move(self, from_index: int, to_index: int):
        """Sync move operation to PlaylistManager (called asynchronously)."""
        try:
            self.playlist_manager.move_track(from_index, to_index)
        except Exception as e:
            logger.warning("Failed to sync move to PlaylistManager: %s", e)
        return False  # Don't repeat
    
    def _update_button_states(self):
        """Update the state of action buttons based on playlist content."""
        has_tracks = len(self._state.playlist) > 0
        self.clear_button.set_sensitive(has_tracks)
        self.save_button.set_sensitive(has_tracks)

    def _update_view(self):
        """Update the tree view with current tracks."""
        self.store.clear()
        tracks = self._state.playlist
        for i, track in enumerate(tracks):
            # Use filename as fallback if title is missing
            title = track.title or Path(track.file_path).stem
            artist = track.artist or "Unknown Artist"
            duration = (
                self._format_duration(track.duration) if track.duration else "--:--"
            )
            self.store.append([i + 1, title, artist, duration])
        self._update_selection()
        # Update button states
        self._update_button_states()

    def _update_selection(self):
        """Update the selection to highlight current track or show blinking highlight."""
        selection = self.tree_view.get_selection()
        tracks = self._state.playlist
        current_index = self._state.current_index

        # Get currently selected row (if any)
        model, tree_iter = selection.get_selected()
        selected_path = None
        selected_index = -1
        if tree_iter:
            selected_path = model.get_path(tree_iter)
            indices = selected_path.get_indices()
            if indices:
                selected_index = indices[0]

        # If current playing track is selected, show normal selection
        if selected_index == current_index and current_index >= 0:
            # Current track is selected - normal selection, no blinking
            self._stop_blinking_highlight()
            # Ensure it's selected in the selection model
            path = Gtk.TreePath.new_from_indices([current_index])
            selection.select_path(path)
            self.tree_view.set_cursor(path, None, False)
        elif (
            current_index >= 0
            and 0 <= current_index < len(tracks)
            and selected_index >= 0
            and selected_index != current_index
        ):
            # Another row is selected - show blinking blue highlight on current track
            current_path = Gtk.TreePath.new_from_indices([current_index])
            self._start_blinking_highlight(current_path)

            # Keep the user's selection visible
            if selected_path:
                self.tree_view.set_cursor(selected_path, None, False)
        elif current_index >= 0 and 0 <= current_index < len(tracks):
            # No other row selected - select current track normally
            self._stop_blinking_highlight()
            path = Gtk.TreePath.new_from_indices([current_index])
            selection.select_path(path)
            self.tree_view.set_cursor(path, None, False)
        else:
            # No current track - stop blinking
            self._stop_blinking_highlight()

        # Scroll to current track if it exists
        if 0 <= current_index < len(tracks):
            path = Gtk.TreePath.new_from_indices([current_index])
            self.tree_view.scroll_to_cell(path, None, False, 0.0, 0.0)

    def _setup_blinking_highlight(self):
        """Setup blinking highlight system."""
        self._blink_path = None  # Track which path is blinking

    def _cell_data_func(self, column, cell, model, tree_iter, data):
        """Cell data function to apply background color for current playing track."""
        # Get row index from model
        path = model.get_path(tree_iter)
        indices = path.get_indices()
        if not indices:
            return
        row_index = indices[0]

        # Get current playing index and selected index
        current_index = self._state.current_index
        selection = self.tree_view.get_selection()
        model_sel, tree_iter_sel = selection.get_selected()
        selected_index = -1
        if tree_iter_sel:
            path_sel = model_sel.get_path(tree_iter_sel)
            indices_sel = path_sel.get_indices()
            if indices_sel:
                selected_index = indices_sel[0]

        # Apply background color based on state
        # Priority: drop target > current playing (blinking) > normal
        
        # Check if this is the drop target during drag
        if self._drag_mode and row_index == self._drop_target_index and self._drop_target_index >= 0:
            # Dark highlight for drop target
            cell.set_property("cell-background-rgba", Gdk.RGBA(0.2, 0.2, 0.2, 0.7))
        elif (
            row_index == current_index
            and current_index >= 0
            and selected_index != current_index
            and selected_index >= 0
        ):
            # This is the current playing track and another row is selected - apply blinking blue
            if self._blink_state:
                # Brighter blue (blink on)
                cell.set_property("cell-background-rgba", Gdk.RGBA(0.2, 0.6, 0.9, 0.6))
            else:
                # Dimmer blue (blink off)
                cell.set_property("cell-background-rgba", Gdk.RGBA(0.2, 0.6, 0.9, 0.3))
        else:
            # Clear background
            cell.set_property("cell-background-rgba", None)

    def _start_blinking_highlight(self, path: Gtk.TreePath):
        """Start blinking highlight on the given path."""
        # Stop any existing blinking
        self._stop_blinking_highlight()

        self._blink_path = path
        self._blink_state = True

        # Force initial redraw by invalidating the row
        try:
            if 0 <= path.get_indices()[0] < len(self._state.playlist):
                tree_iter = self.store.get_iter(path)
                if tree_iter:
                    self.store.row_changed(path, tree_iter)
        except (ValueError, AttributeError, RuntimeError):
            # Fallback: just queue a redraw
            self.tree_view.queue_draw()

        # Start timeout for blinking (1000ms interval - slower blink)
        self._blink_timeout_id = GLib.timeout_add(1000, self._blink_toggle)

    def _stop_blinking_highlight(self):
        """Stop blinking highlight."""
        if self._blink_timeout_id:
            GLib.source_remove(self._blink_timeout_id)
            self._blink_timeout_id = None

        if self._blink_path:
            self._blink_path = None

        self._blink_state = False
        # Trigger redraw to clear highlight
        self.tree_view.queue_draw()

    def _blink_toggle(self):
        """Toggle blink state - called by timeout."""
        if self._blink_path:
            self._blink_state = not self._blink_state
            # Force cell renderers to update by invalidating the row
            # This ensures the cell_data_func is called again
            try:
                # Get the row at the blink path and invalidate it
                if 0 <= self._blink_path.get_indices()[0] < len(self._state.playlist):
                    # Invalidate the row to force redraw
                    self.store.row_changed(
                        self._blink_path, 
                        self.store.get_iter(self._blink_path)
                    )
            except (ValueError, AttributeError, RuntimeError):
                # Fallback: just queue a redraw
                self.tree_view.queue_draw()
            return True  # Continue timeout
        return False  # Stop timeout

    def _format_duration(self, seconds: float) -> str:
        """Format duration in seconds to MM:SS."""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def _release_playback_lock(self):
        """Release playback lock."""
        self._playback_lock = False
        return False  # Don't repeat

    def _reset_playback_guard(self):
        """Reset the playback guard after a delay."""
        self._playback_in_progress = False
        return False  # Don't repeat

    def _cancel_tap_timeout(self):
        """Cancel any pending single-tap timeout."""
        if self._tap_timeout_id:
            GLib.source_remove(self._tap_timeout_id)
            self._tap_timeout_id = None
        self._tap_pending = False
        self._pending_tap_index = -1

    def _on_single_tap_timeout(self):
        """Execute single-tap playback after timeout (no double-tap detected)."""
        self._tap_timeout_id = None
        self._tap_pending = False
        index = self._pending_tap_index
        self._pending_tap_index = -1

        if index >= 0 and not self._playback_lock:
            playlist = self._state.playlist
            if 0 <= index < len(playlist):
                self.play_track_at_index(index)
        return False  # Don't repeat

    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click or Enter key)."""
        # Cancel any pending single-tap timeout to prevent double-play
        self._cancel_tap_timeout()
        
        # Always use selection model to get the correct row (most reliable)
        # First, ensure selection is set to the activated path
        selection = self.tree_view.get_selection()
        selection.select_path(path)
        self.tree_view.set_cursor(path, None, False)
        
        # Now read from selection model (most reliable)
        model, tree_iter = selection.get_selected()
        
        if tree_iter:
            # Use selection model path (most reliable)
            selected_path = model.get_path(tree_iter)
            indices = selected_path.get_indices()
            if indices:
                index = indices[0]
                # Only play if not already locked (prevents double-play from double-tap detection)
                if not self._playback_lock:
                    self.play_track_at_index(index)
                return
        
        # Fallback: if selection failed, use path from signal directly
        indices = path.get_indices()
        if indices:
            index = indices[0]
            # Only play if not already locked
            if not self._playback_lock:
                self.play_track_at_index(index)

    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click to show context menu."""
        # Only show menu if not already showing
        if not self._menu_showing:
            self._show_context_menu_at_position(x, y)

    def _on_left_click_pressed(self, gesture, n_press, x, y):
        """Handle left-click press - select the row at the click position."""
        # Use get_path_at_pos with the click coordinates
        # GestureClick coordinates work correctly with TreeView
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))

        if path_info:
            path = path_info[0]
            indices = path.get_indices()
            if indices:
                self._click_selected_index = indices[0]
                # Update selection model to match
                selection = self.tree_view.get_selection()
                selection.select_path(path)
                # Set cursor to visually select the row
                self.tree_view.set_cursor(path, None, False)
                return

        self._click_selected_index = -1

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Handle drag begin - record start time for long-press detection."""
        self._drag_start_time = GLib.get_monotonic_time()
        self._drag_mode = False
        self._drag_source_index = -1
        self._drag_target_index = -1

        # Always use selection model to get the source row (most reliable)
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()

        if tree_iter:
            path = model.get_path(tree_iter)
            indices = path.get_indices()
            if indices:
                self._drag_source_index = indices[0]
                self._drag_target_index = self._drag_source_index
                return

        # Fallback: use click selected index if available
        if self._click_selected_index >= 0:
            self._drag_source_index = self._click_selected_index
            self._drag_target_index = self._click_selected_index
            return

        # Last resort: try get_path_at_pos (may be inaccurate)
        path_info = self.tree_view.get_path_at_pos(int(start_x), int(start_y))
        if path_info:
            path = path_info[0]
            indices = path.get_indices()
            if indices:
                self._drag_source_index = indices[0]
                self._drag_target_index = self._drag_source_index
                # Update selection to match
                selection.select_path(path)
                self.tree_view.set_cursor(path, None, False)

    def _on_drag_update(self, gesture, offset_x, offset_y):
        """Handle drag update - enter drag mode if held long enough and moved."""
        if self._drag_source_index < 0:
            return

        # Check if user has held long enough to enter drag mode
        current_time = GLib.get_monotonic_time()
        time_held = current_time - self._drag_start_time

        # Check if movement is significant (more than a few pixels)
        movement = abs(offset_x) + abs(offset_y)

        # Enter drag mode if: held for long-press threshold AND moved significantly
        if (
            not self._drag_mode
            and time_held >= self._long_press_threshold
            and movement > 10
        ):
            self._drag_mode = True
            try:
                self.tree_view.add_css_class("dragging")
            except (AttributeError, RuntimeError):
                # Widget might be destroyed or removed from parent
                pass

        # If in drag mode, track where the row would be dropped
        if not self._drag_mode:
            return

        # Calculate target row based on Y position and visible rows
        # This avoids using get_path_at_pos with GestureDrag coordinates which are unreliable
        success, start_x, start_y = gesture.get_start_point()
        if not success:
            return

        current_y = start_y + offset_y

        # Get visible range to calculate which row we're over
        visible_range = self.tree_view.get_visible_range()
        playlist = self._state.playlist
        if not playlist or not visible_range:
            return

        start_path, end_path = visible_range
        if not start_path or not end_path:
            return

        start_idx = start_path.get_indices()[0]
        end_idx = end_path.get_indices()[0]

        # Get cell area to determine row height
        start_rect = self.tree_view.get_cell_area(start_path, None)
        if start_rect.height <= 0:
            return

        row_height = start_rect.height
        # Get tree view bounds
        allocation = self.tree_view.get_allocation()
        if allocation.height <= 0:
            return

        # Calculate which visible row the Y coordinate corresponds to
        # Account for header (approximately 30px) and scroll offset
        header_height = 30
        # Get scroll position
        scrolled = self.tree_view.get_parent()
        if isinstance(scrolled, Gtk.ScrolledWindow):
            vadjustment = scrolled.get_vadjustment()
            scroll_offset = vadjustment.get_value() if vadjustment else 0
        else:
            scroll_offset = 0

        # Calculate relative Y position within visible area
        adjusted_y = current_y - header_height + scroll_offset
        row_offset = int(adjusted_y / row_height) if row_height > 0 else 0

        # Calculate target index
        target_index = start_idx + row_offset
        target_index = max(0, min(target_index, len(playlist) - 1))

        if target_index != self._drag_target_index:
            self._drag_target_index = target_index
            # Update selection to match calculated target
            target_path = Gtk.TreePath.new_from_indices([target_index])
            selection = self.tree_view.get_selection()
            selection.select_path(target_path)
            self.tree_view.set_cursor(target_path, None, False)
            # Update visual feedback - highlight target row with dark background
            self._highlight_drop_target(target_index)

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle drag end - play track (tap), show menu (long-press), or reorder (drag)."""
        current_time = GLib.get_monotonic_time()
        time_held = current_time - self._drag_start_time
        movement = abs(offset_x) + abs(offset_y)

        source_idx = self._drag_source_index
        target_idx = self._drag_target_index
        was_drag_mode = self._drag_mode

        # Remove visual feedback
        if was_drag_mode:
            try:
                self.tree_view.remove_css_class("dragging")
            except (AttributeError, RuntimeError):
                # Widget might be destroyed or removed from parent
                pass
            self._clear_drop_highlight()

        # Reset drag state first
        self._drag_mode = False
        self._drag_source_index = -1
        self._drag_target_index = -1
        self._drag_start_time = 0
        self._click_selected_index = -1  # Reset click selection
        # Clear drop target highlight (will be cleared by _clear_drop_highlight, but ensure it's reset)
        self._drop_target_index = -1

        # Determine what action to take based on time held and movement
        tap_threshold = 200000  # 200ms in microseconds - quick tap
        long_press_time = self._long_press_threshold  # 500ms
        movement_threshold = 15  # pixels

        if time_held < tap_threshold and movement < movement_threshold:
            # Quick tap with minimal movement
            # Always use selection model to get the correct row (most reliable)
            selection = self.tree_view.get_selection()
            model, tree_iter = selection.get_selected()
            tap_index = source_idx  # Default to source_idx
            
            if tree_iter:
                path = model.get_path(tree_iter)
                indices = path.get_indices()
                if indices:
                    tap_index = indices[0]
            
            if tap_index >= 0 and not self._playback_lock:
                playlist = self._state.playlist
                if 0 <= tap_index < len(playlist):
                    if self._single_tap_plays:
                        if self._tap_pending and self._pending_tap_index == tap_index:
                            # Second tap on same row - double-tap detected, play immediately
                            self._cancel_tap_timeout()
                            self.play_track_at_index(tap_index)
                        else:
                            # First tap - wait for potential second tap
                            self._cancel_tap_timeout()  # Cancel any previous pending tap
                            self._tap_pending = True
                            self._pending_tap_index = tap_index
                            self._tap_timeout_id = GLib.timeout_add(
                                self._double_tap_window, self._on_single_tap_timeout
                            )
                    # else: single tap only selects (already selected by GTK)
        elif was_drag_mode and movement >= movement_threshold:
            # Was in drag mode and moved - reorder
            # Always use selection model to get the final target (most reliable)
            selection = self.tree_view.get_selection()
            model, tree_iter = selection.get_selected()
            final_target_idx = target_idx  # Default to calculated target

            if tree_iter:
                path = model.get_path(tree_iter)
                indices = path.get_indices()
                if indices:
                    final_target_idx = indices[0]

            # Validate indices before moving
            playlist_len = len(self._state.playlist)
            if (
                source_idx >= 0
                and final_target_idx >= 0
                and source_idx < playlist_len
                and final_target_idx < playlist_len
                and source_idx != final_target_idx
            ):
                self.move_track(source_idx, final_target_idx)
                # After moving, update selection to the new position
                # The track that was at source_idx is now at final_target_idx
                new_path = Gtk.TreePath.new_from_indices([final_target_idx])
                selection.select_path(new_path)
                self.tree_view.set_cursor(new_path, None, False)
        elif time_held >= long_press_time and movement < movement_threshold:
            # Long press without significant movement - show context menu
            # Always use selection model to get the correct row (most reliable)
            selection = self.tree_view.get_selection()
            model, tree_iter = selection.get_selected()
            menu_index = source_idx  # Default to source_idx
            
            if tree_iter:
                path = model.get_path(tree_iter)
                indices = path.get_indices()
                if indices:
                    menu_index = indices[0]
            
            if menu_index >= 0 and not self._menu_showing:
                self.selected_index = menu_index
                # Get coordinates for menu positioning (use start point from gesture)
                success, start_x, start_y = gesture.get_start_point()
                if success:
                    self._show_context_menu(start_x, start_y)
                else:
                    # Fallback: use center of selected row
                    self._show_context_menu(0, 0)

    def _highlight_drop_target(self, target_index: int):
        """Highlight the row where the dragged item will be dropped with dark background."""
        if 0 <= target_index < len(self._state.playlist):
            # Update drop target index
            old_target = self._drop_target_index
            self._drop_target_index = target_index
            
            # Force redraw of both old and new target rows
            if old_target >= 0 and old_target != target_index:
                try:
                    old_path = Gtk.TreePath.new_from_indices([old_target])
                    old_iter = self.store.get_iter(old_path)
                    if old_iter:
                        self.store.row_changed(old_path, old_iter)
                except (ValueError, AttributeError, RuntimeError):
                    pass
            
            # Force redraw of new target row
            try:
                path = Gtk.TreePath.new_from_indices([target_index])
                tree_iter = self.store.get_iter(path)
                if tree_iter:
                    self.store.row_changed(path, tree_iter)
            except (ValueError, AttributeError, RuntimeError):
                pass

    def _clear_drop_highlight(self):
        """Clear the drop target highlight."""
        if self._drop_target_index >= 0:
            old_target = self._drop_target_index
            self._drop_target_index = -1
            
            # Force redraw to clear highlight
            try:
                path = Gtk.TreePath.new_from_indices([old_target])
                tree_iter = self.store.get_iter(path)
                if tree_iter:
                    self.store.row_changed(path, tree_iter)
            except (ValueError, AttributeError, RuntimeError):
                pass
        
        # Restore selection to current playing track
        self._update_selection()

    def _show_context_menu_at_position(self, x, y):
        """Show context menu at the given position.

        Note: This method works correctly with GestureClick coordinates.
        For GestureDrag (long-press), use selection-based lookup instead.
        """
        # GestureClick coordinates work correctly with TreeView's get_path_at_pos
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if path_info:
            path = path_info[0]
            indices = path.get_indices()
            if indices:
                self.selected_index = indices[0]
                # Also select the row visually
                self.tree_view.set_cursor(path, None, False)
            else:
                self.selected_index = -1
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
            play_item.connect("clicked", self._on_menu_play)
            menu_box.append(play_item)

            remove_item = Gtk.Button(label="Remove")
            remove_item.add_css_class("flat")
            remove_item.set_size_request(150, 40)  # Larger for touch
            remove_item.connect("clicked", self._on_menu_remove)
            menu_box.append(remove_item)

            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            move_up_item = Gtk.Button(label="Move Up")
            move_up_item.add_css_class("flat")
            move_up_item.set_size_request(150, 40)  # Larger for touch
            move_up_item.connect("clicked", self._on_menu_move_up)
            move_up_item.set_sensitive(self.selected_index > 0)
            menu_box.append(move_up_item)

            move_down_item = Gtk.Button(label="Move Down")
            move_down_item.add_css_class("flat")
            move_down_item.set_size_request(150, 40)  # Larger for touch
            move_down_item.connect("clicked", self._on_menu_move_down)
            move_down_item.set_sensitive(
                self.selected_index < len(self._state.playlist) - 1
            )
            menu_box.append(move_down_item)

            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # General menu items
        clear_item = Gtk.Button(label="Clear Playlist")
        clear_item.add_css_class("flat")
        clear_item.set_size_request(150, 40)  # Larger for touch
        clear_item.connect("clicked", self._on_menu_clear)
        clear_item.set_sensitive(len(self._state.playlist) > 0)
        menu_box.append(clear_item)

        save_item = Gtk.Button(label="Save Playlist...")
        save_item.add_css_class("flat")
        save_item.set_size_request(150, 40)  # Larger for touch
        save_item.connect("clicked", self._on_menu_save)
        save_item.set_sensitive(len(self._state.playlist) > 0)
        menu_box.append(save_item)

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

        # Ensure the popover can receive events
        self.context_menu.set_can_focus(True)

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

    def _on_menu_play(self, button):
        """Handle 'Play' from context menu."""
        if self.selected_index >= 0:
            self.play_track_at_index(self.selected_index)
        self._close_menu()

    def _on_menu_remove(self, button):
        """Handle 'Remove' from context menu."""
        if self.selected_index >= 0:
            self.remove_track(self.selected_index)
        self._close_menu()

    def _on_menu_move_up(self, button):
        """Handle 'Move Up' from context menu."""
        if self.selected_index > 0:
            self.move_track(self.selected_index, self.selected_index - 1)
            # Update selected_index after move (track moved up, so index decreased)
            self.selected_index -= 1
        self._close_menu()

    def _on_menu_move_down(self, button):
        """Handle 'Move Down' from context menu."""
        if self.selected_index < len(self._state.playlist) - 1:
            self.move_track(self.selected_index, self.selected_index + 1)
            # Update selected_index after move (track moved down, so index increased)
            self.selected_index += 1
        self._close_menu()

    def _on_menu_clear(self, button):
        """Handle 'Clear Playlist' from context menu."""
        self._handle_clear()
        self._close_menu()

    def _on_menu_save(self, button):
        """Handle 'Save Playlist' from context menu."""
        self._show_save_dialog()
        self._close_menu()

    def _show_save_dialog(self):
        """Show save playlist dialog."""
        if not self.window:
            return

        dialog = Gtk.Dialog(
            title="Save Playlist", transient_for=self.window, modal=True
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(10)
        content.set_margin_end(10)

        label = Gtk.Label(label="Playlist name:")
        content.append(label)

        entry = Gtk.Entry()
        entry.set_placeholder_text("My Playlist")
        content.append(entry)

        def on_response(d, response_id):
            if response_id == Gtk.ResponseType.OK:
                name = entry.get_text().strip()
                if name:
                    self.save_playlist(name)
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

    def _show_load_dialog(self):
        """Show load playlist dialog."""
        if not self.window:
            return

        playlists = self.list_playlists()

        if not playlists:
            # Show a message dialog if no playlists exist
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="No Saved Playlists",
            )
            dialog.set_detail_text("There are no saved playlists to load.")
            dialog.connect("response", lambda d, r: d.close())
            dialog.present()
            return

        # Create dialog with playlist selection
        dialog = Gtk.Dialog(
            title="Load Playlist", transient_for=self.window, modal=True
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Load", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(10)
        content.set_margin_end(10)

        label = Gtk.Label(label="Select a playlist to load:")
        content.append(label)

        # Create list store and tree view for playlist selection
        store = Gtk.ListStore(str)
        for playlist_name in playlists:
            store.append([playlist_name])

        tree_view = Gtk.TreeView(model=store)
        tree_view.set_headers_visible(False)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Playlist", renderer, text=0)
        tree_view.append_column(column)

        # Select first item by default
        selection = tree_view.get_selection()
        if playlists:
            path = Gtk.TreePath.new_from_string("0")
            selection.select_path(path)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_min_content_width(300)
        scrolled.set_child(tree_view)
        content.append(scrolled)

        def on_response(d, response_id):
            if response_id == Gtk.ResponseType.OK:
                selection = tree_view.get_selection()
                model, tree_iter = selection.get_selected()
                if tree_iter:
                    playlist_name = model[tree_iter][0]
                    self.load_playlist(playlist_name)
            dialog.close()

        dialog.connect("response", on_response)
        dialog.present()

    def _handle_refresh(self):
        """Handle refresh from MOC - publish action to reload playlist."""
        self._events.publish(EventBus.ACTION_REFRESH_MOC, {})

    def _close_menu(self):
        """Close the context menu safely."""
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
        self._menu_showing = False
