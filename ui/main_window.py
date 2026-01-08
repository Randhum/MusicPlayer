"""Main application window with dockable panels."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from pathlib import Path
from typing import List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.audio_player import AudioPlayer
from core.bluetooth_manager import BluetoothManager
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.mpris2 import MPRIS2Manager
from core.music_library import MusicLibrary
from core.playlist_manager import PlaylistManager
from core.system_volume import SystemVolume
from ui.components.bluetooth_panel import BluetoothPanel
from ui.components.library_browser import LibraryBrowser
from ui.components.metadata_panel import MetadataPanel
from ui.components.player_controls import PlayerControls
from ui.components.playlist_view import PlaylistView
from ui.dock_manager import DockManager
from ui.moc_sync import MocSyncHelper

logger = get_logger(__name__)


# Update intervals (milliseconds)
POSITION_UPDATE_INTERVAL = 500
MOC_STATUS_UPDATE_INTERVAL = 500

# Window defaults
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800


class MainWindow(Gtk.ApplicationWindow):
    """Main application window with modular dockable panels."""

    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Music Player")
        self.set_default_size(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        # Ensure window can be maximized
        self.set_resizable(True)

        # Initialize core components
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        # Initialize BT manager with this window for pairing dialogs
        self.bt_manager = BluetoothManager(parent_window=self)
        # System volume control
        self.system_volume = SystemVolume(on_volume_changed=self._on_system_volume_changed)
        # MOC integration (Music On Console)
        self.moc_controller = MocController()
        self.use_moc = self.moc_controller.is_available()

        # MPRIS2 integration for desktop/media key support
        self.mpris2 = MPRIS2Manager()

        # Initialize dock manager (needed before UI creation)
        self.dock_manager = DockManager(self)

        # Playback options
        self.shuffle_enabled: bool = False

        # Setup player callbacks (will be connected after player_controls is created)
        # These are set up in _create_player_controls

        # Playlist manager is initialized with empty state by default

        # Create UI with dockable panels (needed before MOC sync helper)
        self._create_ui()

        # MPRIS2 is now set up in player_controls constructor

        # Initialize MOC sync helper (after UI is created)
        self.moc_sync = MocSyncHelper(
            self.moc_controller,
            self.playlist_manager,
            self.player_controls,
            self.metadata_panel,
            self.playlist_view,
        )
        self.moc_sync.on_track_finished = self._on_moc_track_finished
        self.moc_sync.on_shuffle_changed = self._on_moc_shuffle_changed

        # Update player_controls with moc_sync and bt_panel references
        self.player_controls.moc_sync = self.moc_sync
        self.player_controls.bt_panel = self.bt_panel
        
        # Update playlist_view with moc_sync, player_controls, and window references
        self.playlist_view.moc_sync = self.moc_sync
        self.playlist_view.player_controls = self.player_controls
        self.playlist_view.window = self
        
        # Update library_browser with playlist_view and player_controls references
        self.library_browser.playlist_view = self.playlist_view
        self.library_browser.player_controls = self.player_controls

        # Setup player callbacks (after player_controls is created)
        self.player.on_state_changed = lambda is_playing: self._on_player_state_changed(is_playing)
        self.player.on_position_changed = lambda pos, dur: self._on_player_position_changed(
            pos, dur
        )
        self.player.on_track_finished = self._on_track_finished
        self.player.on_track_loaded = self._on_track_loaded

        # Load saved layout
        GLib.idle_add(self.dock_manager.load_layout)

        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)

        # Position updates are handled by:
        # - GStreamer on_position_changed callback (for internal player)
        # - MOC status updates (for MOC player)
        # No separate timer needed
        # If MOC is available, initialize and start status updates
        if self.use_moc:
            # Delay MOC initialization to avoid conflicts during library scan
            GLib.timeout_add(1000, self._initialize_moc)  # Delay 1 second
            GLib.timeout_add(MOC_STATUS_UPDATE_INTERVAL, self._update_moc_status)

        # Initialize volume slider with current system volume
        initial_volume = self.system_volume.get_volume()
        self.player_controls.set_volume(initial_volume)

        # Connect close signal to save layout
        self.connect("close-request", self._on_close)

    def _create_ui(self):
        """Create the user interface with dockable panels."""
        # Apply CSS styling
        self._apply_css()

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)

        # Top bar with search and Bluetooth
        self._create_top_bar(main_box)

        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Create UI components
        self._create_library_browser()
        self._create_playlist_view()
        self._create_metadata_panel()
        self._create_bluetooth_panel()

        # Create dockable panels
        library_panel = self.dock_manager.create_panel(
            "library", "Library", self.library_browser, "folder-music-symbolic"
        )
        library_panel.set_size_request(280, -1)

        playlist_panel = self.dock_manager.create_panel(
            "playlist", "Playlist", self.playlist_view, "view-list-symbolic"
        )
        playlist_panel.set_hexpand(True)

        metadata_panel = self.dock_manager.create_panel(
            "metadata", "Now Playing", self.metadata_panel, "audio-x-generic-symbolic"
        )
        metadata_panel.set_size_request(300, -1)

        bt_panel = self.dock_manager.create_panel(
            "bluetooth", "Bluetooth", self.bt_panel, "bluetooth-symbolic"
        )
        bt_panel.set_size_request(300, -1)

        # Store panel references for reattachment
        self.library_panel = library_panel
        self.playlist_panel = playlist_panel
        self.metadata_dock_panel = metadata_panel
        self.bt_dock_panel = bt_panel

        # Set up reattach callbacks
        library_panel.on_reattach = lambda p: self._reattach_panel("library")
        playlist_panel.on_reattach = lambda p: self._reattach_panel("playlist")
        metadata_panel.on_reattach = lambda p: self._reattach_panel("metadata")
        bt_panel.on_reattach = lambda p: self._reattach_panel("bluetooth")

        # Create main content area with paned layout
        self.content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.content_paned.set_vexpand(True)

        # Left paned (Library | Center)
        left_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        left_paned.set_start_child(library_panel)
        left_paned.set_position(280)
        left_paned.set_shrink_start_child(False)
        left_paned.set_shrink_end_child(False)

        # Center paned (Playlist)
        left_paned.set_end_child(playlist_panel)

        self.content_paned.set_start_child(left_paned)
        self.content_paned.set_shrink_start_child(False)
        self.content_paned.set_shrink_end_child(False)

        # Right paned (Metadata | Bluetooth)
        right_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        right_paned.set_start_child(metadata_panel)
        right_paned.set_end_child(bt_panel)
        right_paned.set_position(400)
        right_paned.set_shrink_start_child(False)
        right_paned.set_shrink_end_child(False)

        right_paned.set_size_request(300, -1)
        self.content_paned.set_end_child(right_paned)
        self.content_paned.set_position(800)

        # Store references for layout management
        self.left_paned = left_paned
        self.right_paned = right_paned

        # Store parent container references in panels for reattachment
        library_panel.parent_container = left_paned
        playlist_panel.parent_container = left_paned
        metadata_panel.parent_container = right_paned
        bt_panel.parent_container = right_paned

        main_box.append(self.content_paned)

        # Bottom - Player controls (not dockable)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self._create_player_controls()
        main_box.append(self.player_controls)

    def _apply_css(self):
        """Apply custom CSS styling."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(
            """
            .dock-header {
                background: alpha(@theme_bg_color, 0.8);
                border-bottom: 1px solid @borders;
            }
            .dock-header button {
                min-width: 32px;
                min-height: 32px;
                padding: 4px;
            }
            
            /* Touch-friendly tree views */
            .library-tree row {
                min-height: 48px;
                padding: 8px;
            }
            
            .playlist-tree row {
                min-height: 48px;
                padding: 8px;
            }
            
            /* Touch-friendly buttons */
            button {
                min-height: 36px;
                padding: 8px 12px;
            }
            
            /* Touch-friendly entry fields */
            entry {
                min-height: 36px;
                padding: 8px;
            }
            
            /* Touch-friendly scales */
            scale {
                min-height: 30px;
            }
            
            scale slider {
                min-width: 20px;
                min-height: 20px;
            }
            
            scale trough {
                min-height: 8px;
            }
            
            /* Time left label - dimmed style */
            .dim-label {
                opacity: 0.6;
                font-size: 0.9em;
            }
        """
        )

        display = self.get_display()
        Gtk.StyleContext.add_provider_for_display(
            display, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _create_top_bar(self, parent: Gtk.Box):
        """Create the top bar with search."""
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        top_bar.set_margin_start(10)
        top_bar.set_margin_end(10)
        top_bar.set_margin_top(10)
        top_bar.set_margin_bottom(10)

        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search music...")
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.set_size_request(300, -1)
        top_bar.append(self.search_entry)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top_bar.append(spacer)

        # App title
        title = Gtk.Label(label="Music Player")
        title.add_css_class("title-2")
        top_bar.append(title)

        parent.append(top_bar)

    def _create_library_browser(self):
        """Create and configure the library browser."""
        # Note: playlist_view and player_controls will be set after they are created
        self.library_browser = LibraryBrowser(
            playlist_view=None,  # Will be set after playlist_view is created
            player_controls=None,  # Will be set after player_controls is created
        )
        self.library_browser.connect("track-selected", self._on_track_selected)
        self.library_browser.connect("album-selected", self._on_album_selected)

    def _create_playlist_view(self):
        """Create and configure the playlist view."""
        # Note: player_controls and window will be set after player_controls is created
        self.playlist_view = PlaylistView(
            self.playlist_manager,
            moc_sync=None,  # Will be set after moc_sync is created
            player_controls=None,  # Will be set after player_controls is created
            window=None,  # Will be set after player_controls is created
        )
        self.playlist_view.connect("track-activated", self._on_playlist_track_activated)
        self.playlist_view.connect("current-index-changed", self._on_playlist_current_index_changed)
        # Show refresh button only when MOC is available
        self.playlist_view.set_moc_mode(self.use_moc)

    def _create_metadata_panel(self):
        """Create the metadata panel."""
        self.metadata_panel = MetadataPanel()

    def _create_bluetooth_panel(self):
        """Create the Bluetooth panel with speaker mode support."""
        self.bt_panel = BluetoothPanel(self.bt_manager)
        # Device selection is handled internally by bluetooth_panel

    def _create_player_controls(self):
        """Create player controls."""
        # Note: moc_sync and bt_panel will be set up after UI creation
        self.player_controls = PlayerControls(
            player=self.player,
            playlist_view=self.playlist_view,
            moc_sync=None,  # Will be set after moc_sync is created
            bt_panel=None,  # Will be set after bt_panel is created
            mpris2=self.mpris2,
            system_volume=self.system_volume,
            window=self,
        )
        # Connect signals for metadata updates
        self.player_controls.connect("track-changed", self._on_track_changed)
        self.player_controls.connect("shuffle-toggled", self._on_shuffle_toggled)

    def _reattach_panel(self, panel_id: str):
        """Reattach a detached panel to its original position."""
        panel = self.dock_manager.panels.get(panel_id)
        if not panel or not panel.parent_container:
            return

        # Make sure panel is not already a child of something
        current_parent = panel.get_parent()
        if current_parent:
            if isinstance(current_parent, Gtk.Paned):
                if current_parent.get_start_child() is panel:
                    current_parent.set_start_child(None)
                elif current_parent.get_end_child() is panel:
                    current_parent.set_end_child(None)
            elif isinstance(current_parent, Gtk.Box):
                current_parent.remove(panel)
            elif isinstance(current_parent, Gtk.Window):
                current_parent.set_child(None)

        # Reattach to original parent container
        parent = panel.parent_container
        if isinstance(parent, Gtk.Paned):
            # Use stored position or determine from panel_id
            if panel.parent_position == "start":
                parent.set_start_child(panel)
            elif panel.parent_position == "end":
                parent.set_end_child(panel)
            else:
                # Fallback: determine from panel_id
                if panel_id == "library":
                    parent.set_start_child(panel)
                elif panel_id == "playlist":
                    parent.set_end_child(panel)
                elif panel_id == "metadata":
                    parent.set_start_child(panel)
                elif panel_id == "bluetooth":
                    parent.set_end_child(panel)
        elif isinstance(parent, Gtk.Box):
            parent.append(panel)
        elif isinstance(parent, Gtk.Window):
            parent.set_child(panel)

    def _on_close(self, window):
        """Handle window close."""
        self.dock_manager.cleanup()
        self.player.cleanup()
        # Cleanup player controls (includes MPRIS2 and system volume)
        if hasattr(self, "player_controls"):
            self.player_controls.cleanup()
        # Cleanly stop MOC server if we started it
        if self.use_moc and hasattr(self, "moc_sync"):
            try:
                self.moc_sync.shutdown()
            except OSError:
                # Ignore errors shutting down MOC server (may already be stopped)
                pass
        # Cleanup Bluetooth resources
        if hasattr(self, "bt_manager"):
            self.bt_manager.cleanup()

        # Cleanup library watcher
        if hasattr(self, "library") and hasattr(self.library, "stop_watching"):
            self.library.stop_watching()

        return False  # Allow close to proceed

    def _on_library_scan_complete(self):
        """Called when library scan is complete."""
        # Use idle_add to populate browser incrementally (non-blocking)
        GLib.idle_add(self._populate_library_browser)
        # Playlist view will be updated when MOC loads playlist
        # Delay MOC operations to ensure server is ready
        if self.use_moc:
            GLib.timeout_add(500, lambda: self.moc_sync.load_playlist_from_moc())  # Delay 500ms

    def _populate_library_browser(self):
        """Populate library browser (called via idle_add for non-blocking)."""
        self.library_browser.populate(self.library)
        return False  # Don't repeat

    def _initialize_moc(self):
        """Initialize MOC server and settings (called after startup delay)."""
        if self.use_moc:
            self.moc_sync.initialize()
        return False  # Don't repeat

    def _on_moc_track_finished(self):
        """Handle track finished from MOC - advance to next track."""
        # This is called when MOC has advanced to the next track
        # MOC sync handles the actual advancement, we just need to sync UI
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()

        # Check if there's a next track available
        if current_index < len(tracks) - 1:
            # There's a next track - MOC should already be playing it (autonext)
            # Just verify and sync playlist to ensure consistency
            if self.moc_sync:
                self.moc_sync.update_moc_playlist(start_playback=True)
                self.moc_sync.set_autonext_enabled(True)
        else:
            # End of playlist - stop playback
            if self.moc_sync:
                self.moc_sync.stop()
            self.playlist_view.set_current_index(-1)

    def _on_moc_shuffle_changed(self, shuffle_enabled: bool):
        """Handle shuffle state change from MOC."""
        self.shuffle_enabled = shuffle_enabled
        # Update player_controls shuffle state
        self.player_controls.set_shuffle_enabled(shuffle_enabled)

    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            results = self.library.search(query)
            self.playlist_view.clear()  # Auto-syncs to MOC
            self.playlist_view.add_tracks(results)  # Auto-syncs to MOC
        else:
            self.playlist_view.clear()  # Auto-syncs to MOC

    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection from library browser."""
        self.playlist_view.clear()
        self.playlist_view.add_track(track)
        self.playlist_view.set_current_index(0)
        # Trigger playback through player_controls
        self.player_controls.play_current_track()

    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        """Handle album selection from library browser."""
        self.playlist_view.clear()
        self.playlist_view.add_tracks(tracks)
        self.playlist_view.set_current_index(0)
        # Trigger playback through player_controls
        self.player_controls.play_current_track()

    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.playlist_view.set_current_index(index)
        # Trigger playback through player_controls
        self.player_controls.play_current_track()

    def _on_playlist_current_index_changed(self, view, index: int):
        """Handle current index change in playlist and sync to MOC."""
        if self.use_moc and self.moc_sync:
            self.moc_sync.sync_set_current_index(index)

    def _on_track_changed(self, controls, track: TrackMetadata):
        """Handle track change from player_controls."""
        # Update metadata panel
        self.metadata_panel.set_track(track)

        # Update MPRIS2 navigation capabilities
        self.player_controls.update_mpris2_navigation_capabilities()

    def _on_system_volume_changed(self, volume: float):
        """Handle system volume change from external source (e.g., volume keys) - update UI."""
        self.player_controls.set_volume(volume)

    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_view.get_current_track()
        if track and not self.player_controls.should_use_moc(track):
            self.player_controls.set_playing(is_playing)
            # Update MPRIS2
            if self.mpris2:
                self.mpris2.update_playback_status(is_playing, is_paused=False)

    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_view.get_current_track()
        if track and not self.player_controls.should_use_moc(track):
            self.player_controls.update_progress(position, duration)

    def _on_track_loaded(self):
        """Handle track loaded - update duration and sync MOC."""

        # Wait a bit for GStreamer to determine duration, then update
        def update_after_load():
            duration = self.player.get_duration()
            position = self.player.get_position()
            # Update progress even if duration is 0 (will be updated when available)
            self.player_controls.update_progress(position, duration)
            # If duration is still 0, try again after a short delay
            if duration == 0:
                GLib.timeout_add(200, update_after_load)
            return False

        # Initial update
        GLib.timeout_add(100, update_after_load)

        # Sync MOC after track is loaded (only if using MOC for this track)
        track = self.playlist_view.get_current_track()
        if self.use_moc and track and self.player_controls.should_use_moc(track):
            if self.moc_sync:
                self.moc_sync.enable_sync()
                self.moc_sync.update_moc_playlist(start_playback=True)
                self.moc_sync.set_autonext_enabled(True)
                # Sync shuffle state
                self.moc_sync.set_shuffle(self.shuffle_enabled)

    def _on_track_finished(self):
        """Handle track finished - auto-advance based on loop mode and autonext (internal player only)."""
        # This callback is only for internal player (video files)
        # MOC handles auto-advancement internally for audio files

        # Only auto-advance if autonext is enabled
        if not self.player_controls.get_autonext_enabled():
            return

        loop_mode = self.player_controls.get_loop_mode()
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()

        if loop_mode == self.player_controls.LOOP_TRACK:
            # Loop current track - restart it
            self.player_controls.play_current_track()
        elif loop_mode == self.player_controls.LOOP_PLAYLIST:
            # Loop playlist - advance to next or wrap to first
            next_track = self.playlist_view.get_next_track()
            if next_track:
                self.player_controls.play_current_track()
            else:
                # End of playlist - wrap to beginning
                if tracks:
                    self.playlist_view.set_current_index(0)
                    self.player_controls.play_current_track()
                else:
                    self.player.stop()
                    self.playlist_view.set_current_index(-1)
        else:  # LOOP_FORWARD
            # Forward mode - advance to next track or stop at end
            next_track = self.playlist_view.get_next_track()
            if next_track:
                self.player_controls.play_current_track()
            else:
                # End of playlist reached - stop
                self.player.stop()
                self.playlist_view.set_current_index(-1)

    def _update_moc_status(self):
        """Periodically pull status from MOC - sync UI and detect track changes."""
        if not self.use_moc:
            return False
        return self.moc_sync.update_status()

    def _on_shuffle_toggled(self, controls, active: bool):
        """Handle shuffle toggle state changes."""
        self.shuffle_enabled = active
        # Sync shuffle state with playlist view (manages shuffle order)
        if self.playlist_view:
            self.playlist_view.set_shuffle_enabled(active)
        # Sync shuffle state with MOC (delegated to moc_sync)
        if self.use_moc and self.moc_sync:
            self.moc_sync.set_shuffle(active)
        # Update player_controls internal state to keep in sync
        self.player_controls.set_shuffle_enabled(active)

    def _sync_shuffle_from_moc(self):
        """Sync shuffle state from MOC to UI."""
        if not self.use_moc or not self.moc_sync:
            return False
        moc_shuffle = self.moc_sync.get_shuffle_enabled()
        if moc_shuffle is not None:
            self.shuffle_enabled = moc_shuffle
            self.player_controls.shuffle_button.set_active(moc_shuffle)
        return False

