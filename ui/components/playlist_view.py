"""Playlist view component - shows current queue/playlist."""

from pathlib import Path
from typing import Callable, List, Optional


import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk

from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.playlist_manager import PlaylistManager

logger = get_logger(__name__)


class PlaylistView(Gtk.Box):
    """Playlist tree; subscribes to PLAYLIST_CHANGED/CURRENT_INDEX_CHANGED; publishes ACTION_*."""

    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "current-index-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(
        self,
        event_bus: EventBus,
        playlist_manager: PlaylistManager,
        window: Optional[Gtk.Window] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self._events = event_bus
        self.playlist_manager = playlist_manager
        self.window = window
        self._shuffle_enabled: bool = False
        self._use_moc: bool = False
        self._bulk_update_in_progress: bool = (
            False  # Track if bulk update is in progress
        )
        self._chunked_update_id: Optional[int] = None  # Track chunked update timeout ID

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

        def _header_btn(box, icon: str, tooltip: str, cb: Callable[[], None]):
            btn = Gtk.Button.new_from_icon_name(icon)
            btn.set_tooltip_text(tooltip)
            btn.add_css_class("flat")
            btn.set_size_request(36, 36)
            btn.connect("clicked", lambda w: cb())
            box.append(btn)
            return btn

        self.refresh_button = _header_btn(
            header_box,
            "view-refresh-symbolic",
            "Refresh from MOC",
            self._handle_refresh,
        )
        self.clear_button = _header_btn(
            header_box,
            "edit-clear-symbolic",
            "Clear Playlist",
            lambda: self.clear(stop_first=True),
        )
        self.save_button = _header_btn(
            header_box,
            "document-save-symbolic",
            "Save Playlist",
            self._show_save_dialog,
        )
        self.load_button = _header_btn(
            header_box,
            "document-open-symbolic",
            "Load Saved Playlist",
            self._show_load_dialog,
        )

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
        self._playback_in_progress = False
        self._playback_lock = False

        # Drag-to-reorder state
        self._drag_mode = False  # True when long-press activated drag mode
        self._drag_source_index = -1  # Index of row being dragged
        self._drag_target_index = -1  # Index where row will be dropped
        self._drag_start_time = (
            0  # Timestamp when drag started (for long-press detection)
        )
        self._long_press_threshold = (
            250000  # 250ms in microseconds (snappier drag feel)
        )
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

    def set_shuffle_enabled(self, enabled: bool):
        """Enable or disable shuffle mode (publish action)."""
        self._events.publish(EventBus.ACTION_SET_SHUFFLE, {"enabled": enabled})

    def get_shuffle_enabled(self) -> bool:
        """Get current shuffle state (cached from SHUFFLE_CHANGED)."""
        return self._shuffle_enabled

    def add_track(self, track: TrackMetadata, position: Optional[int] = None):
        """Add a track - publish ADD_FOLDER; PlaylistManager subscribes; MOC sync via PLAYLIST_CHANGED."""
        self._events.publish(
            EventBus.ADD_FOLDER,
            {
                "tracks": [track],
                **({"position": position} if position is not None else {}),
            },
        )

    def add_tracks(self, tracks: List[TrackMetadata]):
        """Add tracks - publish ADD_FOLDER; PlaylistManager subscribes; view updates via PLAYLIST_CHANGED."""
        if not tracks:
            return
        self._events.publish(EventBus.ADD_FOLDER, {"tracks": tracks})

    def remove_track(self, index: int):
        """Remove a track - publish action; PlaylistManager subscribes; view updates via PLAYLIST_CHANGED."""
        self._events.publish(EventBus.ACTION_REMOVE, {"index": index})

    def move_track(self, from_index: int, to_index: int):
        """Move a track - publish action; PlaylistManager subscribes; view updates via PLAYLIST_CHANGED."""
        self._events.publish(
            EventBus.ACTION_MOVE,
            {"from_index": from_index, "to_index": to_index},
        )

    def clear(self, stop_first: bool = False):
        """Clear playlist (publish action). If stop_first, publish ACTION_STOP first."""
        if stop_first:
            self._events.publish(EventBus.ACTION_STOP)
        self._events.publish(EventBus.ACTION_CLEAR_PLAYLIST)

    def save_playlist(self, name: str) -> bool:
        """Save the current playlist (PlaylistManager is source of truth)."""
        return self.playlist_manager.save_playlist(name)

    def load_playlist(self, name: str) -> bool:
        """Load a saved playlist. PlaylistManager publishes; view updates via events."""
        return self.playlist_manager.load_playlist(name)

    def load_current_playlist(self) -> bool:
        """Load the current playlist from auto-save file. PlaylistManager publishes; view updates via events."""
        return self.playlist_manager.load_current_playlist()

    def list_playlists(self) -> List[str]:
        """List all saved playlists."""
        return self.playlist_manager.list_playlists()

    def play_track_at_index(self, index: int) -> None:
        """Request playback of track at index - publishes action event only.

        Note: We do NOT call set_current_index here. PlaybackController is the
        single source of state mutation - it will set the index when handling
        ACTION_PLAY_TRACK. View updates via CURRENT_INDEX_CHANGED event.
        """
        if self._playback_lock:
            return
        playlist = self.playlist_manager.get_playlist()
        if not 0 <= index < len(playlist):
            return
        self._playback_lock = True
        # Don't mutate state - let controller handle it
        self._events.publish(EventBus.ACTION_PLAY_TRACK, {"index": index})
        self.emit("track-activated", index)
        GLib.timeout_add(500, self._release_playback_lock)

    def replace_and_play_track(self, track: TrackMetadata) -> None:
        """Replace playlist with single track and play it.

        Publishes ACTION_REPLACE_PLAYLIST with start_playback=True.
        PlaylistManager handles the playlist update, PlaybackController handles playback.
        """
        self._events.publish(
            EventBus.ACTION_REPLACE_PLAYLIST,
            {
                "tracks": [track],
                "current_index": 0,
                "start_playback": True,
            },
        )

    def replace_and_play_album(self, tracks: List[TrackMetadata]) -> None:
        """Replace playlist with album tracks and play first track.

        Publishes ACTION_REPLACE_PLAYLIST with start_playback=True.
        PlaylistManager handles the playlist update, PlaybackController handles playback.
        """
        self._events.publish(
            EventBus.ACTION_REPLACE_PLAYLIST,
            {
                "tracks": tracks,
                "current_index": 0,
                "start_playback": True,
            },
        )

    def add_folder(self, folder_path: str) -> None:
        """
        Add a folder to the playlist.

        If MOC is active, uses MOC's native append command which recursively adds
        all tracks in one operation (much faster, single sync).
        Otherwise, collects tracks and adds them individually.

        Args:
            folder_path: Path to the folder to add.
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return

        # Collect tracks and use ADD_FOLDER - PlaybackController handles MOC sync via PLAYLIST_CHANGED
        tracks = []
        for ext in ["*.mp3", "*.ogg", "*.flac", "*.m4a", "*.wav", "*.opus"]:
            tracks.extend([TrackMetadata(str(p)) for p in folder.rglob(ext)])

        # Sort tracks by file path to match library order (library sorts by file_path)
        tracks.sort(key=lambda t: t.file_path)

        if tracks:
            self._events.publish(EventBus.ADD_FOLDER, {"tracks": tracks})

    def replace_and_play_folder(self, folder_path: str) -> None:
        """Replace playlist with folder contents and play first track.

        Defers track collection to idle to keep UI responsive.
        Uses ACTION_REPLACE_PLAYLIST event - PlaylistManager handles playlist,
        PlaybackController handles MOC sync and playback.
        """
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return
        # Release any stuck lock so controls work after load
        self._playback_lock = False
        GLib.idle_add(self._do_replace_and_play_folder, str(folder.resolve()))

    def _do_replace_and_play_folder(self, folder_path: str) -> bool:
        """Idle callback: collect tracks and publish ACTION_REPLACE_PLAYLIST."""
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return False
        tracks = []
        for ext in ["*.mp3", "*.ogg", "*.flac", "*.m4a", "*.wav", "*.opus"]:
            tracks.extend([TrackMetadata(str(p)) for p in folder.rglob(ext)])
        tracks.sort(key=lambda t: t.file_path)
        if not tracks:
            return False
        # Use unified event - PlaylistManager updates playlist, PlaybackController handles playback
        self._events.publish(
            EventBus.ACTION_REPLACE_PLAYLIST,
            {
                "tracks": tracks,
                "current_index": 0,
                "start_playback": True,
            },
        )
        return False  # one-shot idle

    def set_moc_mode(self, enabled: bool):
        """Show or hide the Refresh button based on whether MOC mode is active."""
        self._use_moc = enabled
        self.refresh_button.set_visible(enabled)

    def _sync_from_state(self) -> None:
        """Refresh tree from PlaylistManager (e.g. on init)."""
        self._update_view()

    def _on_playlist_changed(self, data: Optional[dict]) -> None:
        """Subscriber: playlist content changed → refresh tree."""
        tracks = self.playlist_manager.get_playlist()
        # Defer tree update for large playlists to avoid GTK assertion (gtk_css_node_insert_after:
        # store updates must run after layout/draw). Use LOW priority so they run when truly idle.
        if len(tracks) >= 100:
            GLib.idle_add(self._update_view, priority=GLib.PRIORITY_LOW)
        else:
            self._update_view()

    def _on_current_index_changed(self, data: Optional[dict]) -> None:
        """Subscriber: current index changed → update selection and blinking (deferred to avoid GTK assertion)."""
        GLib.idle_add(self._update_selection)

    def _on_shuffle_changed(self, data: Optional[dict]) -> None:
        """Handle shuffle changed event - cache for get_shuffle_enabled()."""
        if data:
            self._shuffle_enabled = data.get("enabled", False)

    def _update_button_states(self):
        """Update the state of action buttons based on playlist content."""
        has_tracks = len(self.playlist_manager.get_playlist()) > 0
        self.clear_button.set_sensitive(has_tracks)
        self.save_button.set_sensitive(has_tracks)

    def _update_view(self):
        """Update the tree view with current tracks from PlaylistManager."""
        tracks = self.playlist_manager.get_playlist()

        # Always reset bulk update state before starting a new update
        # This ensures consistent behavior regardless of previous state
        if self._chunked_update_id is not None:
            GLib.source_remove(self._chunked_update_id)
            self._chunked_update_id = None
        self._bulk_update_in_progress = False

        try:
            self.tree_view.get_selection().unselect_all()
        except (ValueError, AttributeError, RuntimeError, AssertionError):
            pass
        self._stop_blinking_highlight()

        # For large playlists, use chunked updates to avoid blocking UI
        if len(tracks) >= 100:
            # Start chunked update
            self._bulk_update_in_progress = True
            self.store.clear()
            # Process first chunk immediately to show something right away
            # Then schedule remaining chunks asynchronously
            first_chunk_size = min(100, len(tracks))
            for i in range(first_chunk_size):
                track = tracks[i]
                title = track.title or Path(track.file_path).stem
                artist = track.artist or "Unknown Artist"
                duration = (
                    self._format_duration(track.duration) if track.duration else "--:--"
                )
                self.store.append([i + 1, title, artist, duration])

            # If there are more tracks, schedule remaining chunks
            if len(tracks) > first_chunk_size:
                self._chunked_update_id = GLib.idle_add(
                    self._update_view_chunked, first_chunk_size
                )
            else:
                # All tracks processed in first chunk
                self._bulk_update_in_progress = False
                self._chunked_update_id = None
                self._playback_lock = False
                GLib.idle_add(self._apply_selection_after_view_update)
        else:
            # For small playlists, update synchronously (fast enough)
            self.store.clear()
            for i, track in enumerate(tracks):
                # Use filename as fallback if title is missing
                title = track.title or Path(track.file_path).stem
                artist = track.artist or "Unknown Artist"
                duration = (
                    self._format_duration(track.duration) if track.duration else "--:--"
                )
                self.store.append([i + 1, title, artist, duration])
            # Defer selection/blink so we're not in same stack as store updates (avoids GTK assertion)
            GLib.idle_add(self._apply_selection_after_view_update)

    def _apply_selection_after_view_update(self) -> bool:
        """Idle callback: update selection and blink after store repopulate (avoids GTK assertion)."""
        self._update_selection()
        self._update_button_states()
        return False

    def _update_view_chunked(self, start_index: int, chunk_size: int = 100) -> bool:
        """
        Update tree view in chunks to avoid blocking UI.

        Args:
            start_index: Index to start processing from
            chunk_size: Number of tracks to process per chunk

        Returns:
            False (always) - we schedule next chunks explicitly via GLib.idle_add
        """
        # Always read current playlist state (may have changed since callback was scheduled)
        tracks = self.playlist_manager.get_playlist()
        total_tracks = len(tracks)

        # Verify we're still in bulk update mode (might have been cancelled by another _update_view call)
        if not self._bulk_update_in_progress:
            self._chunked_update_id = None
            self._playback_lock = False
            return False

        # Safety check: if playlist is empty or start_index is out of bounds, finalize
        if total_tracks == 0:
            self._bulk_update_in_progress = False
            self._chunked_update_id = None
            self._playback_lock = False
            self._update_selection()
            self._update_button_states()
            return False

        # If start_index is beyond current playlist, we're done (playlist might have shrunk)
        if start_index >= total_tracks:
            self._bulk_update_in_progress = False
            self._chunked_update_id = None
            self._playback_lock = False
            self._update_selection()
            self._update_button_states()
            return False

        # Process one chunk
        end_index = min(start_index + chunk_size, total_tracks)
        for i in range(start_index, end_index):
            track = tracks[i]
            # Use filename as fallback if title is missing
            title = track.title or Path(track.file_path).stem
            artist = track.artist or "Unknown Artist"
            duration = (
                self._format_duration(track.duration) if track.duration else "--:--"
            )
            self.store.append([i + 1, title, artist, duration])

        # Check if more chunks to process (LOW priority to avoid gtk_css_node_insert_after)
        if end_index < total_tracks:
            self._chunked_update_id = GLib.idle_add(
                self._update_view_chunked, end_index, priority=GLib.PRIORITY_LOW
            )
            return False  # Don't repeat automatically - we scheduled the next chunk explicitly

        # All chunks processed - finalize
        self._bulk_update_in_progress = False
        self._chunked_update_id = None
        self._playback_lock = False  # Ensure controls work after large load
        self._update_selection()
        self._update_button_states()
        return False  # Done

    def _update_selection(self, skip_scroll: bool = False):
        """Update selection and blinking for current track. Event-driven (CURRENT_INDEX_CHANGED).
        Current playing track always blinks; selection shows current track. All tree ops wrapped to avoid GTK assertion.
        """
        if self._bulk_update_in_progress:
            return
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        selection = self.tree_view.get_selection()

        # Get actual store row count - may differ from playlist during chunked updates
        store_row_count = len(self.store)

        def safe_select_path(path: Gtk.TreePath) -> None:
            try:
                selection.select_path(path)
                self.tree_view.set_cursor(path, None, False)
            except (ValueError, AttributeError, RuntimeError, AssertionError):
                pass

        def safe_scroll_to_cell(path: Gtk.TreePath) -> None:
            try:
                self.tree_view.scroll_to_cell(path, None, False, 0.0, 0.0)
            except (ValueError, AttributeError, RuntimeError, AssertionError):
                pass

        # Check both playlist length AND store row count to avoid GTK assertion
        # (store may have fewer rows during chunked updates)
        if (
            current_index >= 0
            and current_index < len(tracks)
            and current_index < store_row_count
        ):
            path = Gtk.TreePath.new_from_indices([current_index])
            self._start_blinking_highlight(path)
            safe_select_path(path)
            if not skip_scroll:
                safe_scroll_to_cell(path)
        else:
            self._stop_blinking_highlight()
            try:
                selection.unselect_all()
            except (ValueError, AttributeError, RuntimeError, AssertionError):
                pass

    def _setup_blinking_highlight(self):
        """Setup blinking highlight for current playing track (event-driven via CURRENT_INDEX_CHANGED)."""
        self._blink_path = None

    def _cell_data_func(self, column, cell, model, tree_iter, data):
        """Cell data function: drop target highlight, then current playing track (blinking), else normal."""
        try:
            path = model.get_path(tree_iter)
            indices = path.get_indices()
            if not indices:
                return
            row_index = indices[0]
            if row_index < 0 or row_index >= len(self.store):
                return
        except (ValueError, AttributeError, RuntimeError, AssertionError):
            return

        current_index = self.playlist_manager.get_current_index()

        # Priority: drop target > current playing (blinking) > normal
        try:
            if (
                self._drag_mode
                and row_index == self._drop_target_index
                and self._drop_target_index >= 0
            ):
                cell.set_property("cell-background-set", True)
                cell.set_property("cell-background-rgba", Gdk.RGBA(0.2, 0.2, 0.2, 0.7))
            elif row_index == current_index and current_index >= 0:
                cell.set_property("cell-background-set", True)
                if self._blink_state:
                    cell.set_property(
                        "cell-background-rgba", Gdk.RGBA(0.2, 0.6, 0.9, 0.6)
                    )
                else:
                    cell.set_property(
                        "cell-background-rgba", Gdk.RGBA(0.2, 0.6, 0.9, 0.3)
                    )
            else:
                cell.set_property("cell-background-set", False)
                cell.set_property("cell-background-rgba", Gdk.RGBA(0, 0, 0, 0))
        except (ValueError, AttributeError, RuntimeError, AssertionError):
            pass

    def _start_blinking_highlight(self, path: Gtk.TreePath):
        """Start blinking highlight on the given path."""
        # Stop any existing blinking
        self._stop_blinking_highlight()

        # Store the path (will be updated in _blink_toggle if index changes)
        self._blink_path = path
        self._blink_state = True

        try:
            self.tree_view.queue_draw()
        except (ValueError, AttributeError, RuntimeError, AssertionError):
            pass
        self._blink_timeout_id = GLib.timeout_add(1000, self._blink_toggle)

    def _stop_blinking_highlight(self):
        """Stop blinking highlight."""
        if self._blink_timeout_id:
            GLib.source_remove(self._blink_timeout_id)
            self._blink_timeout_id = None

        if self._blink_path:
            self._blink_path = None

        self._blink_state = False
        try:
            self.tree_view.queue_draw()
        except (ValueError, AttributeError, RuntimeError, AssertionError):
            pass

    def _blink_toggle(self):
        """Toggle blink state for current playing track (called by timeout)."""
        current_index = self.playlist_manager.get_current_index()
        playlist = self.playlist_manager.get_playlist()
        if current_index >= 0 and 0 <= current_index < len(playlist):
            self._blink_path = Gtk.TreePath.new_from_indices([current_index])
            self._blink_state = not self._blink_state
            try:
                self.tree_view.queue_draw()
            except (ValueError, AttributeError, RuntimeError, AssertionError):
                pass
            return True
        self._stop_blinking_highlight()
        return False

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

    def _on_row_activated(self, tree_view, path, column):
        """Handle row activation (double-click or Enter key) - start playback."""
        # Use selection model to get the correct row
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
                selection = self.tree_view.get_selection()
                try:
                    selection.select_path(path)
                    self.tree_view.set_cursor(path, None, False)
                except (ValueError, AttributeError, RuntimeError, AssertionError):
                    pass
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
        try:
            path_info = self.tree_view.get_path_at_pos(int(start_x), int(start_y))
            if path_info:
                path = path_info[0]
                indices = path.get_indices()
                if indices:
                    self._drag_source_index = indices[0]
                    self._drag_target_index = self._drag_source_index
                    # Update selection to match (safe during drag-begin, before drag starts)
                    try:
                        selection.select_path(path)
                        self.tree_view.set_cursor(path, None, False)
                    except (ValueError, AttributeError, RuntimeError):
                        pass  # Selection update failed, but we have the index
        except (ValueError, AttributeError, RuntimeError):
            pass  # get_path_at_pos failed, but we tried other methods

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

        # Calculate target row using GTK's built-in path detection
        try:
            success, start_x, start_y = gesture.get_start_point()
            if not success:
                return

            current_x = start_x + offset_x
            current_y = start_y + offset_y

            playlist = self.playlist_manager.get_playlist()
            if not playlist:
                return

            # Convert widget coordinates to bin window coordinates
            # The tree view header offsets the content, so we need to adjust
            # get_path_at_pos expects bin window coords (content area, not header)
            bin_x, bin_y = self.tree_view.convert_widget_to_bin_window_coords(
                int(current_x), int(current_y)
            )

            # Use get_path_at_pos for accurate row detection
            path_info = self.tree_view.get_path_at_pos(bin_x, bin_y)

            if path_info:
                path = path_info[0]
                indices = path.get_indices()
                if indices:
                    target_index = indices[0]
                else:
                    # Fallback: if at bottom of list, use last index
                    target_index = len(playlist) - 1
            else:
                # Mouse is outside row bounds - determine if above or below
                # If y is negative or small, use first row; if large, use last row
                if bin_y < 0:  # Above first row
                    target_index = 0
                else:
                    target_index = len(playlist) - 1

            # Bounds check
            target_index = max(0, min(target_index, len(playlist) - 1))

            # Only update visual highlight, NOT selection model
            if target_index != self._drag_target_index:
                self._drag_target_index = target_index
                # Update visual feedback - highlight target row with dark background
                # DO NOT update selection or cursor during drag
                self._highlight_drop_target(target_index)
        except Exception as e:
            # Catch any unexpected errors to prevent fatal crashes
            logger.debug("Error in drag update: %s", e, exc_info=True)
            return

    def _on_drag_end(self, gesture, offset_x, offset_y):
        """Handle drag end - play track (tap), show menu (long-press), or reorder (drag)."""
        current_time = GLib.get_monotonic_time()
        time_held = current_time - self._drag_start_time
        movement = abs(offset_x) + abs(offset_y)

        # Validate indices before using them
        playlist_len = len(self.playlist_manager.get_playlist())
        source_idx = (
            self._drag_source_index
            if 0 <= self._drag_source_index < playlist_len
            else -1
        )
        target_idx = (
            self._drag_target_index
            if 0 <= self._drag_target_index < playlist_len
            else -1
        )
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

        # Determine what action to take: drag (reorder) or long-press (menu). Single-tap only selects (handled in _on_left_click_pressed).
        long_press_time = self._long_press_threshold
        movement_threshold = 15

        if was_drag_mode and movement >= movement_threshold:
            # User dragged a track to reorder it
            # source_idx = where the track started
            # target_idx = where the user dropped it (calculated during drag)

            playlist_len = len(self.playlist_manager.get_playlist())
            if (
                source_idx >= 0
                and target_idx >= 0
                and source_idx < playlist_len
                and target_idx < playlist_len
                and source_idx != target_idx
            ):
                # Move the track - UI will refresh automatically via event
                self.move_track(source_idx, target_idx)
        elif time_held >= long_press_time and movement < movement_threshold:
            # Long press without significant movement - show context menu
            # Use row at gesture start position (same as right-click: row under pointer)
            success, start_x, start_y = gesture.get_start_point()
            if success:
                self.selected_index = self._get_playlist_index_at_position(
                    start_x, start_y
                )
            else:
                self.selected_index = -1
            if self.selected_index >= 0 and not self._menu_showing:
                if success:
                    self._show_context_menu(start_x, start_y)
                else:
                    self._show_context_menu(0, 0)

    def _highlight_drop_target(self, target_index: int):
        """Highlight the row where the dragged item will be dropped with dark background."""
        if not (0 <= target_index < len(self.playlist_manager.get_playlist())):
            return

        try:
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
        except Exception as e:
            logger.debug("Error highlighting drop target: %s", e, exc_info=True)

    def _clear_drop_highlight(self):
        """Clear the drop target highlight."""
        if self._drop_target_index >= 0:
            old_target = self._drop_target_index
            self._drop_target_index = -1

            # Force redraw to clear highlight (only if target is valid)
            if 0 <= old_target < len(self.playlist_manager.get_playlist()):
                try:
                    path = Gtk.TreePath.new_from_indices([old_target])
                    tree_iter = self.store.get_iter(path)
                    if tree_iter:
                        self.store.row_changed(path, tree_iter)
                except (ValueError, AttributeError, RuntimeError):
                    pass

        GLib.idle_add(self._update_selection)

    def _get_playlist_index_at_position(self, x: float, y: float) -> int:
        """Return playlist row index at widget coordinates, or -1 if none."""
        path_info = self.tree_view.get_path_at_pos(int(x), int(y))
        if not path_info:
            return -1
        path = path_info[0]
        indices = path.get_indices()
        if not indices:
            return -1
        return indices[0]

    def _show_context_menu_at_position(self, x, y):
        """Show context menu at the given position (right-click or long-press)."""
        self.selected_index = self._get_playlist_index_at_position(x, y)
        if self.selected_index >= 0:
            path = Gtk.TreePath.new_from_indices([self.selected_index])
            self.tree_view.set_cursor(path, None, False)
        self._show_context_menu(x, y)

    def _show_context_menu(self, x: float, y: float):
        """Show context menu. Defer build/show to idle to avoid GTK insert_after assertion."""
        if self._menu_showing:
            return
        # Close and unparent old menu so next idle sees a clean state
        if self.context_menu:
            try:
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                pass
            try:
                if self.context_menu.get_parent():
                    self.context_menu.unparent()
            except (AttributeError, RuntimeError):
                pass
            self.context_menu = None
        self._menu_showing = True
        self._context_menu_x = x
        self._context_menu_y = y
        GLib.idle_add(self._do_show_context_menu)

    def _do_show_context_menu(self):
        """Idle callback: create and show context menu (avoids gtk_css_node_insert_after assertion)."""
        if not self._menu_showing or self.context_menu is not None:
            return False
        x = getattr(self, "_context_menu_x", 0)
        y = getattr(self, "_context_menu_y", 0)
        self.context_menu = Gtk.Popover()
        self.context_menu.set_has_arrow(True)
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
                self.selected_index < len(self.playlist_manager.get_playlist()) - 1
            )
            menu_box.append(move_down_item)

            menu_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # General menu items
        clear_item = Gtk.Button(label="Clear Playlist")
        clear_item.add_css_class("flat")
        clear_item.set_size_request(150, 40)  # Larger for touch
        clear_item.connect("clicked", self._on_menu_clear)
        clear_item.set_sensitive(len(self.playlist_manager.get_playlist()) > 0)
        menu_box.append(clear_item)

        save_item = Gtk.Button(label="Save Playlist...")
        save_item.add_css_class("flat")
        save_item.set_size_request(150, 40)  # Larger for touch
        save_item.connect("clicked", self._on_menu_save)
        save_item.set_sensitive(len(self.playlist_manager.get_playlist()) > 0)
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
        self.context_menu.set_can_focus(True)
        return False  # one-shot idle

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
        if self.selected_index < 0:
            self._close_menu()
            return
        playlist = self.playlist_manager.get_playlist()
        if not (0 <= self.selected_index < len(playlist)):
            self._close_menu()
            return
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
        if self.selected_index < len(self.playlist_manager.get_playlist()) - 1:
            self.move_track(self.selected_index, self.selected_index + 1)
            # Update selected_index after move (track moved down, so index increased)
            self.selected_index += 1
        self._close_menu()

    def _on_menu_clear(self, button):
        """Handle 'Clear Playlist' from context menu."""
        self.clear(stop_first=True)
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
                # Disconnect signal first to prevent double cleanup
                try:
                    self.context_menu.disconnect_by_func(self._on_popover_closed)
                except (TypeError, AttributeError):
                    pass
                # Call popdown to close visually
                self.context_menu.popdown()
            except (AttributeError, RuntimeError):
                # Widget may have been destroyed
                pass
            # Schedule cleanup in idle to let GTK finish state transitions
            GLib.idle_add(self._cleanup_popover)
        self._menu_showing = False

    def cleanup(self) -> None:
        """Clean up resources when component is destroyed."""
        # Stop blinking highlight if active
        if self._blink_timeout_id is not None:
            GLib.source_remove(self._blink_timeout_id)
            self._blink_timeout_id = None

        # Cancel any pending chunked update
        if self._chunked_update_id is not None:
            GLib.source_remove(self._chunked_update_id)
            self._chunked_update_id = None
