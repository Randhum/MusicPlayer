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
from core.metadata import TrackMetadata
from core.playlist_manager import PlaylistManager


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

        # Add drag gesture for long-press-to-reorder
        drag_gesture = Gtk.GestureDrag()
        drag_gesture.set_button(1)  # Left mouse button
        drag_gesture.connect("drag-begin", self._on_drag_begin)
        drag_gesture.connect("drag-update", self._on_drag_update)
        drag_gesture.connect("drag-end", self._on_drag_end)
        self.tree_view.add_controller(drag_gesture)

        # Playback state
        self._playback_in_progress = False  # Guard to prevent concurrent playback
        self._playback_lock = False  # Prevent concurrent play_track_at_index calls

        # Single-tap behavior configuration
        # True = single tap plays track, False = single tap only selects (double-tap to play)
        self._single_tap_plays = True

        # Tap/double-tap detection state
        self._tap_pending = False  # True when waiting for potential double-tap
        self._tap_timeout_id = None  # GLib timeout source ID
        self._pending_tap_index = -1  # Index of track for pending single-tap
        self._double_tap_window = 300  # ms to wait for second tap

        # Drag-to-reorder state
        self._drag_mode = False  # True when long-press activated drag mode
        self._drag_source_index = -1  # Index of row being dragged
        self._drag_target_index = -1  # Index where row will be dropped
        self._drag_start_time = 0  # Timestamp when drag started (for long-press detection)
        self._long_press_threshold = 500000  # 500ms in microseconds

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

        self._shuffle_enabled: bool = False
        self._shuffle_queue: List[int] = []  # Queue of shuffled indices for shuffle mode

        # Subscribe to playlist changes
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)
        self._events.subscribe(EventBus.CURRENT_INDEX_CHANGED, self._on_current_index_changed)
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
        Get the next track from AppState.

        If shuffle is enabled, returns a random unplayed track.
        If all tracks have been played, resets and starts over.
        """
        if self._shuffle_enabled:
            return self._get_next_random_track()
        else:
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
        self._shuffle_enabled = enabled
        # Regenerate shuffle queue when toggling shuffle
        self._regenerate_shuffle_queue()

    def get_shuffle_enabled(self) -> bool:
        """Get current shuffle state."""
        return self._shuffle_enabled

    def _get_next_random_track(self) -> Optional[TrackMetadata]:
        """
        Get the next random track from the shuffle queue.

        Uses a shuffled queue of indices. When the queue is empty, regenerates it.
        This ensures each track is played exactly once before repeating.
        """
        tracks = self._state.playlist
        if not tracks:
            return None

        # If queue is empty, regenerate it
        if not self._shuffle_queue:
            self._regenerate_shuffle_queue()

        # If still empty (shouldn't happen, but handle edge case)
        if not self._shuffle_queue:
            return None

        # Pop the next index from the queue
        new_index = self._shuffle_queue.pop(0)
        self._state.set_current_index(new_index)
        return tracks[new_index]

    def _regenerate_shuffle_queue(self):
        """
        Regenerate the shuffle queue with all playlist indices in random order.

        This is called when:
        - Shuffle is enabled
        - Playlist is modified (add, remove, clear, load)
        - Queue is exhausted
        """
        import random

        tracks = self._state.playlist
        if not tracks:
            self._shuffle_queue = []
            return

        # Create a list of all indices
        indices = list(range(len(tracks)))

        # Shuffle the list
        random.shuffle(indices)

        # If there's a current track, remove it from the queue to avoid immediate repeat
        current_idx = self._state.current_index
        if 0 <= current_idx < len(tracks) and current_idx in indices:
            indices.remove(current_idx)
            # Add it at the end so it plays eventually, but not next
            indices.append(current_idx)

        self._shuffle_queue = indices

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
        # Regenerate shuffle queue when playlist changes
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()

    def set_current_index(self, index: int):
        """
        Set the currently playing track index.

        Updates AppState and the UI view.
        In shuffle mode, removes the index from the shuffle queue if present.
        """
        old_index = self._state.current_index
        self._state.set_current_index(index)
        # Remove from shuffle queue if present (to avoid playing it again before queue regenerates)
        if self._shuffle_enabled and index in self._shuffle_queue:
            self._shuffle_queue.remove(index)
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
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()

    def add_tracks(self, tracks: List[TrackMetadata]):
        """Add multiple tracks to the playlist (updates AppState and UI)."""
        for track in tracks:
            self._state.add_track(track)
            self.playlist_manager.add_track(track)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()

    def remove_track(self, index: int):
        """Remove a track from the playlist (updates AppState and UI)."""
        self._state.remove_track(index)
        self.playlist_manager.remove_track(index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()

    def move_track(self, from_index: int, to_index: int):
        """Move a track in the playlist (updates AppState and UI)."""
        self._state.move_track(from_index, to_index)
        self.playlist_manager.move_track(from_index, to_index)
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()

    def clear(self):
        """Clear the playlist (updates AppState and UI)."""
        self._shuffle_queue.clear()  # Clear shuffle queue
        self._state.clear_playlist()
        self.playlist_manager.clear()
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
            self._apply_playlist_change(lambda: None)  # Already loaded, just sync
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

    # ============================================================================
    # UI Configuration
    # ============================================================================

    def set_moc_mode(self, enabled: bool):
        """Show or hide the Refresh button based on whether MOC mode is active."""
        self.refresh_button.set_visible(enabled)

    def set_single_tap_plays(self, enabled: bool):
        """
        Configure single-tap behavior.
        
        Args:
            enabled: If True, single tap plays the track (after double-tap detection window).
                     If False, single tap only selects (use double-tap to play).
        """
        self._single_tap_plays = enabled

    def get_single_tap_plays(self) -> bool:
        """Get current single-tap behavior setting."""
        return self._single_tap_plays

    def set_double_tap_window(self, ms: int):
        """
        Configure the double-tap detection window.
        
        Args:
            ms: Time in milliseconds to wait for a second tap (default: 300).
        """
        self._double_tap_window = max(100, min(ms, 1000))  # Clamp to 100-1000ms

    def get_double_tap_window(self) -> int:
        """Get current double-tap detection window in milliseconds."""
        return self._double_tap_window

    # ============================================================================
    # Internal Methods
    # ============================================================================

    def _sync_from_state(self):
        """Sync the view from AppState."""
        if self._shuffle_enabled:
            self._regenerate_shuffle_queue()
        self._update_view()
    
    def _on_playlist_changed(self, data: Optional[dict]) -> None:
        """Handle playlist changed event."""
        if data:
            tracks = data.get("tracks", [])
            index = data.get("index", -1)
            # Regenerate shuffle queue if shuffle is enabled
            if self._shuffle_enabled:
                self._regenerate_shuffle_queue()
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
            duration = self._format_duration(track.duration) if track.duration else "--:--"
            self.store.append([i + 1, title, artist, duration])
        self._update_selection()
        # Update button states
        self._update_button_states()

    def _update_selection(self):
        """Update the selection to highlight current track."""
        selection = self.tree_view.get_selection()
        selection.unselect_all()

        tracks = self._state.playlist
        current_index = self._state.current_index
        if 0 <= current_index < len(tracks):
            path = Gtk.TreePath.new_from_indices([current_index])
            selection.select_path(path)
            self.tree_view.set_cursor(path, None, False)
            self.tree_view.scroll_to_cell(path, None, False, 0.0, 0.0)

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
        
        indices = path.get_indices()
        if indices:
            index = indices[0]
            # Only play if not already locked (prevents double-play from double-tap detection)
            if not self._playback_lock:
                self.play_track_at_index(index)

    def _on_right_click(self, gesture, n_press, x, y):
        """Handle right-click to show context menu."""
        # Only show menu if not already showing
        if not self._menu_showing:
            self._show_context_menu_at_position(x, y)

    def _on_drag_begin(self, gesture, start_x, start_y):
        """Handle drag begin - record start time for long-press detection."""
        self._drag_start_time = GLib.get_monotonic_time()
        self._drag_mode = False
        self._drag_source_index = -1
        self._drag_target_index = -1
        
        # Get the row at the press location and select it
        # Using get_path_at_pos immediately (not in a timeout) with set_cursor is safe
        path_info = self.tree_view.get_path_at_pos(int(start_x), int(start_y))
        if path_info:
            path = path_info[0]
            # Select the row to ensure GTK selection matches the pressed row
            self.tree_view.set_cursor(path, None, False)
            # Get index directly from path (more reliable than querying selection)
            indices = path.get_indices()
            if indices:
                self._drag_source_index = indices[0]
                self._drag_target_index = self._drag_source_index

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
        if not self._drag_mode and time_held >= self._long_press_threshold and movement > 10:
            self._drag_mode = True
            self.tree_view.add_css_class("dragging")

        # If in drag mode, track where the row would be dropped
        if not self._drag_mode:
            return

        # Get current drag position
        success, start_x, start_y = gesture.get_start_point()
        if not success:
            return

        current_y = start_y + offset_y

        # Find the row at the current position using tree view allocation
        playlist = self._state.playlist
        if not playlist:
            return

        # Calculate target row based on y position
        allocation = self.tree_view.get_allocation()
        if allocation.height <= 0:
            return

        row_count = len(playlist)
        if row_count == 0:
            return

        # Account for header height (approximately 30px)
        header_height = 30
        content_height = allocation.height - header_height
        row_height = content_height / max(row_count, 1)

        # Calculate target index from y position
        adjusted_y = current_y - header_height
        target_index = int(adjusted_y / row_height) if row_height > 0 else 0
        target_index = max(0, min(target_index, row_count - 1))

        if target_index != self._drag_target_index:
            self._drag_target_index = target_index
            # Update visual feedback - highlight target row
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
            self.tree_view.remove_css_class("dragging")
            self._clear_drop_highlight()

        # Reset drag state first
        self._drag_mode = False
        self._drag_source_index = -1
        self._drag_target_index = -1
        self._drag_start_time = 0

        # Determine what action to take based on time held and movement
        tap_threshold = 200000  # 200ms in microseconds - quick tap
        long_press_time = self._long_press_threshold  # 500ms
        movement_threshold = 15  # pixels

        if time_held < tap_threshold and movement < movement_threshold:
            # Quick tap with minimal movement
            if source_idx >= 0 and not self._playback_lock:
                playlist = self._state.playlist
                if 0 <= source_idx < len(playlist):
                    if self._single_tap_plays:
                        if self._tap_pending and self._pending_tap_index == source_idx:
                            # Second tap on same row - double-tap detected, play immediately
                            self._cancel_tap_timeout()
                            self.play_track_at_index(source_idx)
                        else:
                            # First tap - wait for potential second tap
                            self._cancel_tap_timeout()  # Cancel any previous pending tap
                            self._tap_pending = True
                            self._pending_tap_index = source_idx
                            self._tap_timeout_id = GLib.timeout_add(
                                self._double_tap_window, self._on_single_tap_timeout
                            )
                    # else: single tap only selects (already selected by GTK)
        elif was_drag_mode and movement >= movement_threshold:
            # Was in drag mode and moved - reorder
            if source_idx != target_idx and 0 <= target_idx < len(self._state.playlist):
                self.move_track(source_idx, target_idx)
        elif time_held >= long_press_time and movement < movement_threshold:
            # Long press without significant movement - show context menu
            success, start_x, start_y = gesture.get_start_point()
            if success and not self._menu_showing:
                self._show_context_menu_at_position(start_x, start_y)

    def _highlight_drop_target(self, target_index: int):
        """Highlight the row where the dragged item will be dropped."""
        # Select the target row to show where it will be dropped
        if 0 <= target_index < len(self._state.playlist):
            path = Gtk.TreePath.new_from_indices([target_index])
            self.tree_view.set_cursor(path, None, False)

    def _clear_drop_highlight(self):
        """Clear the drop target highlight."""
        # Restore selection to current playing track
        self._update_selection()

    def _show_context_menu_at_position(self, x, y):
        """Show context menu at the given position."""
        # Use selection instead of coordinate-based path lookup
        # GTK handles selection correctly (accounting for scroll offset),
        # while get_path_at_pos with gesture coordinates may have offset issues
        selection = self.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter:
            path = model.get_path(tree_iter)
            indices = path.get_indices()
            if indices:
                self.selected_index = indices[0]
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
            play_item.connect("clicked", lambda w: self._on_menu_play())
            menu_box.append(play_item)

            remove_item = Gtk.Button(label="Remove")
            remove_item.add_css_class("flat")
            remove_item.set_size_request(150, 40)  # Larger for touch
            remove_item.connect("clicked", lambda w: self._on_menu_remove())
            menu_box.append(remove_item)

            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

            move_up_item = Gtk.Button(label="Move Up")
            move_up_item.add_css_class("flat")
            move_up_item.set_size_request(150, 40)  # Larger for touch
            move_up_item.connect("clicked", lambda w: self._on_menu_move_up())
            move_up_item.set_sensitive(self.selected_index > 0)
            menu_box.append(move_up_item)

            move_down_item = Gtk.Button(label="Move Down")
            move_down_item.add_css_class("flat")
            move_down_item.set_size_request(150, 40)  # Larger for touch
            move_down_item.connect("clicked", lambda w: self._on_menu_move_down())
            move_down_item.set_sensitive(self.selected_index < len(self._state.playlist) - 1)
            menu_box.append(move_down_item)

            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # General menu items
        clear_item = Gtk.Button(label="Clear Playlist")
        clear_item.add_css_class("flat")
        clear_item.set_size_request(150, 40)  # Larger for touch
        clear_item.connect("clicked", lambda w: self._on_menu_clear())
        clear_item.set_sensitive(len(self._state.playlist) > 0)
        menu_box.append(clear_item)

        save_item = Gtk.Button(label="Save Playlist...")
        save_item.add_css_class("flat")
        save_item.set_size_request(150, 40)  # Larger for touch
        save_item.connect("clicked", lambda w: self._on_menu_save())
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
            self.play_track_at_index(self.selected_index)

    def _on_menu_remove(self):
        """Handle 'Remove' from context menu."""
        self._close_menu()
        if self.selected_index >= 0:
            self.remove_track(self.selected_index)

    def _on_menu_move_up(self):
        """Handle 'Move Up' from context menu."""
        self._close_menu()
        if self.selected_index > 0:
            self.move_track(self.selected_index, self.selected_index - 1)

    def _on_menu_move_down(self):
        """Handle 'Move Down' from context menu."""
        self._close_menu()
        if self.selected_index < len(self._state.playlist) - 1:
            self.move_track(self.selected_index, self.selected_index + 1)

    def _on_menu_clear(self):
        """Handle 'Clear Playlist' from context menu."""
        self._close_menu()
        self._handle_clear()

    def _on_menu_save(self):
        """Handle 'Save Playlist' from context menu."""
        self._close_menu()
        self._show_save_dialog()
    
    def _show_save_dialog(self):
        """Show save playlist dialog."""
        if not self.window:
            return
        
        dialog = Gtk.Dialog(title="Save Playlist", transient_for=self.window, modal=True)
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
        dialog = Gtk.Dialog(title="Load Playlist", transient_for=self.window, modal=True)
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
