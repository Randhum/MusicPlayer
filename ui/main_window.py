"""Main application window with dockable panels."""

from pathlib import Path
from typing import Optional, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib

from core.audio_player import AudioPlayer, VIDEO_EXTENSIONS
from core.bluetooth_manager import BluetoothManager
from core.bluetooth_sink import BluetoothSink
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.mpris2 import MPRIS2Manager
from core.music_library import MusicLibrary
from core.playlist_manager import PlaylistManager
from core.playback_controller import PlaybackController
from core.system_volume import SystemVolume
from ui.components.bluetooth_panel import BluetoothPanel
from ui.components.library_browser import LibraryBrowser
from ui.components.metadata_panel import MetadataPanel
from ui.components.player_controls import PlayerControls
from ui.components.playlist_view import PlaylistView
from ui.dock_manager import DockManager
from ui.moc_sync import MocSyncHelper
from core.logging import get_logger

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
        # Create player instance (only for PlaybackController's internal use - do not access directly)
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        # Initialize BT manager with this window for pairing dialogs
        self.bt_manager = BluetoothManager(parent_window=self)
        self.bt_sink = BluetoothSink(self.bt_manager)
        # System volume control
        self.system_volume = SystemVolume(on_volume_changed=self._on_system_volume_changed)
        # MOC integration (Music On Console)
        self.moc_controller = MocController()
        self.use_moc = self.moc_controller.is_available()
        
        # MPRIS2 integration for desktop/media key support
        self.mpris2 = MPRIS2Manager()
        
        # Initialize dock manager
        self.dock_manager = DockManager(self)
        
        # Create UI with dockable panels (needed before MOC sync helper)
        self._create_ui()
        
        # Initialize MOC sync helper (after UI is created)
        # This is the SINGLE interface for all MOC operations
        self.moc_sync = MocSyncHelper(
            self.moc_controller,
            self.playlist_manager,
            self.player_controls,
            self.metadata_panel,
            self.playlist_view,
            self._is_video_track,
            self.mpris2
        )
        self.moc_sync.on_track_finished = self._on_moc_track_finished
        self.moc_sync.on_shuffle_changed = self._on_moc_shuffle_changed
        
        # Initialize playback controller (handles all playback logic)
        self.playback_controller = PlaybackController(
            self.playlist_manager,
            self.moc_sync,
            self.player,
            self.moc_controller,
            self.player_controls,
            self._is_video_track,
            self._normalize_path,
            on_track_changed=self._on_playback_track_changed,
            on_playback_state_changed=self._on_playback_state_changed
        )
        
        # Setup playback controller callbacks (delegates to internal player for video tracks)
        self.playback_controller.on_state_changed = self._on_player_state_changed
        self.playback_controller.on_position_changed = self._on_player_position_changed
        self.playback_controller.on_track_finished = self._on_track_finished
        self.playback_controller.on_track_loaded = self._on_track_loaded
        
        # Setup MPRIS2 callbacks (after playback controller callbacks are set)
        self._setup_mpris2()
        
        # Load saved layout
        GLib.idle_add(self.dock_manager.load_layout)
        
        # Populate UI immediately with cached data (non-blocking)
        GLib.idle_add(self._populate_library_browser)
        
        # Start library scan in background (will update UI incrementally)
        self.library.scan_library(
            callback=self._on_library_scan_complete,
            progress_callback=self._on_library_scan_progress
        )
        
        # Start position update timer
        GLib.timeout_add(POSITION_UPDATE_INTERVAL, self._update_position)
        # If MOC is available, initialize and start status updates
        if self.use_moc:
            # Delay MOC initialization to avoid conflicts during library scan
            GLib.timeout_add(1000, self._initialize_moc)  # Delay 1 second
            GLib.timeout_add(MOC_STATUS_UPDATE_INTERVAL, self._update_moc_status)
        
        # Initialize volume slider with current system volume
        initial_volume = self.system_volume.get_volume()
        self.player_controls.set_volume(initial_volume)
        
        # Connect close signal to save layout
        self.connect('close-request', self._on_close)
    
    def _is_video_track(self, track: Optional[TrackMetadata]) -> bool:
        """Return True if the given track is a video container we should play via GStreamer."""
        if not track or not track.file_path:
            return False
        suffix = Path(track.file_path).suffix.lower()
        return suffix in VIDEO_EXTENSIONS
    
    def _normalize_path(self, file_path: Optional[str]) -> Optional[str]:
        """Normalize a file path to absolute resolved path for comparison."""
        if not file_path:
            return None
        try:
            return str(Path(file_path).resolve())
        except (OSError, ValueError):
            return file_path
    
    
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
        css_provider = Gtk.CssProvider()
        css_provider.load_from_string("""
            .dock-header {
                background: alpha(@theme_bg_color, 0.8);
                border-bottom: 1px solid @borders;
            }
            .dock-header button {
                min-width: 32px;
                min-height: 32px;
                padding: 4px;
            }
            .library-tree row,
            .playlist-tree row {
                min-height: 48px;
                padding: 8px;
            }
            button {
                min-height: 36px;
                padding: 8px 12px;
            }
            entry {
                min-height: 36px;
                padding: 8px;
            }
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
            .album-art-placeholder {
                background: #667eea;
                border-radius: 12px;
                opacity: 0.85;
            }
            .placeholder-icon {
                opacity: 0.7;
                color: white;
            }
            .placeholder-text {
                color: white;
                font-size: 12px;
                font-weight: 500;
                opacity: 0.95;
            }
            .album-art {
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }
        """)
        Gtk.StyleContext.add_provider_for_display(self.get_display(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    
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
        self.search_entry.connect('search-changed', self._on_search_changed)
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
        self.library_browser = LibraryBrowser()
        self.library_browser.connect('track-selected', self._on_track_selected)
        self.library_browser.connect('album-selected', self._on_album_selected)
        self.library_browser.connect('add-track', self._on_add_track)
        self.library_browser.connect('add-album', self._on_add_album)
    
    def _create_playlist_view(self):
        """Create and configure the playlist view."""
        self.playlist_view = PlaylistView()
        self.playlist_view.connect('track-activated', self._on_playlist_track_activated)
        self.playlist_view.connect('remove-track', self._on_playlist_remove_track)
        self.playlist_view.connect('move-track-up', self._on_playlist_move_up)
        self.playlist_view.connect('move-track-down', self._on_playlist_move_down)
        self.playlist_view.connect('clear-playlist', self._on_playlist_clear)
        self.playlist_view.connect('save-playlist', self._on_playlist_save)
        self.playlist_view.connect('load-playlist', self._on_playlist_load)
        self.playlist_view.connect('refresh-playlist', self._on_playlist_refresh)
        # Show refresh button only when MOC is available
        self.playlist_view.set_moc_mode(self.use_moc)
    
    def _create_metadata_panel(self):
        """Create the metadata panel."""
        self.metadata_panel = MetadataPanel()
    
    def _create_bluetooth_panel(self):
        """Create the Bluetooth panel with speaker mode support."""
        self.bt_panel = BluetoothPanel(self.bt_manager, self.bt_sink)
        self.bt_panel.connect('device-selected', self._on_bt_device_selected)
    
    def _create_player_controls(self):
        """Create player controls."""
        self.player_controls = PlayerControls()
        self.player_controls.connect('play-clicked', lambda w: self._on_play())
        self.player_controls.connect('pause-clicked', lambda w: self._on_pause())
        self.player_controls.connect('stop-clicked', lambda w: self._on_stop())
        self.player_controls.connect('next-clicked', lambda w: self._on_next())
        self.player_controls.connect('prev-clicked', lambda w: self._on_prev())
        self.player_controls.connect('seek-changed', self._on_seek)
        self.player_controls.connect('volume-changed', self._on_volume_changed)
        self.player_controls.connect('shuffle-toggled', self._on_shuffle_toggled)
        self.player_controls.connect('autonext-toggled', self._on_autonext_toggled)
    
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
            if panel.parent_position == 'start':
                parent.set_start_child(panel)
            elif panel.parent_position == 'end':
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
        self.playback_controller.cleanup()
        # Cleanup MPRIS2
        if hasattr(self, 'mpris2') and self.mpris2:
            self.mpris2.cleanup()
        # Cleanup system volume monitoring
        if hasattr(self, 'system_volume'):
            self.system_volume.cleanup()
        # Cleanly stop MOC server if we started it
        if self.use_moc and hasattr(self, "moc_controller"):
            try:
                self.moc_controller.shutdown()
            except OSError:
                # Ignore errors shutting down MOC server (may already be stopped)
                pass
        # Cleanup Bluetooth resources
        if hasattr(self, 'bt_manager'):
            self.bt_manager.cleanup()
        return False  # Allow close to proceed
    
    def _on_library_scan_progress(self, current: int, total: int):
        """Called periodically during library scan to update UI incrementally."""
        # Update library browser every 50 tracks or when complete
        if current % 50 == 0 or current == total:
            GLib.idle_add(self._populate_library_browser)
    
    def _on_library_scan_complete(self):
        """Called when library scan is complete."""
        # Final update of library browser
        GLib.idle_add(self._populate_library_browser)
        GLib.idle_add(self._update_playlist_view)
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
            # Sync autonext and shuffle button states after initialization
            self._sync_autonext_button_state()
            self._sync_shuffle_button_state()
        return False  # Don't repeat
    
    def _on_moc_track_finished(self):
        """Handle track finished from MOC - delegate to moc_sync."""
        # All track advancement logic is now in moc_sync
        if self.use_moc:
            self.moc_sync.handle_track_finished()
    
    def _on_moc_shuffle_changed(self, shuffle_enabled: bool):
        """Handle shuffle state change from MOC."""
        # Only update if state is different to avoid interfering with user interaction
        if self.player_controls.shuffle_button.get_active() != shuffle_enabled:
            self.player_controls.shuffle_button.set_active(shuffle_enabled)
    
    def _sync_autonext_button_state(self):
        """Sync autonext button state with MOC state."""
        if self.use_moc:
            autonext_enabled = self.moc_sync.get_autonext_enabled()
            self.player_controls.autonext_button.set_active(autonext_enabled)
    
    def _sync_shuffle_button_state(self):
        """Sync shuffle button state with MOC state."""
        if self.use_moc:
            # Query shuffle state directly from moc_controller
            shuffle_enabled = self.moc_controller.get_shuffle_state()
            if shuffle_enabled is not None:
                self.player_controls.shuffle_button.set_active(shuffle_enabled)
    
    def _update_mpris2_navigation_capabilities(self):
        """Update MPRIS2 CanGoNext and CanGoPrevious based on playlist state."""
        if not self.mpris2:
            return
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        # Can go next if there's a next track or shuffle is enabled with tracks available
        can_go_next = False
        if tracks:
            if self.use_moc and self.moc_sync.get_shuffle_enabled():
                # In shuffle mode, can go next if there are unplayed tracks or all tracks played
                can_go_next = len(tracks) > 0
            else:
                # Sequential mode - can go next if not at end
                can_go_next = current_index < len(tracks) - 1
        
        # Can go previous if there's a previous track
        can_go_previous = current_index > 0
        
        self.mpris2.update_can_go_next(can_go_next)
        self.mpris2.update_can_go_previous(can_go_previous)
    
    def _update_playlist_view(self):
        """Update the playlist view."""
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
        # Update MPRIS2 navigation capabilities when playlist changes
        self._update_mpris2_navigation_capabilities()
        return False
    
    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(self.library.search(query))
        else:
            self.playlist_manager.clear()
        self._update_playlist_view()
        self._sync_moc_playlist()
    
    def _sync_moc_playlist(self):
        """Helper: sync MOC playlist after changes."""
        if self.use_moc:
            self.moc_sync.sync_enabled = True
            self.moc_sync.sync_playlist_to_moc(start_playback=False)
    
    def _on_track_selected(self, browser, track: TrackMetadata):
        self.playlist_manager.clear()
        self.playlist_manager.add_track(track)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        self._sync_moc_playlist()
        self.playback_controller.play_current_track()
        self._update_playlist_view()
    
    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        self.playlist_manager.clear()
        self.playlist_manager.add_tracks(tracks)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        self._sync_moc_playlist()
        self.playback_controller.play_current_track()
        self._update_playlist_view()
    
    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.playlist_manager.set_current_index(index)
        self._update_playlist_view()
        self.playback_controller.play_current_track()
    
    def _on_playback_track_changed(self, track: TrackMetadata):
        """Handle track change from playback controller."""
        # Update playlist view to ensure current track is highlighted and visible
        self._update_playlist_view()
        
        # Update metadata panel
        self.metadata_panel.set_track(track)
        
        # Update MPRIS2 metadata and navigation capabilities
        if self.mpris2:
            self.mpris2.update_metadata(track)
            self._update_mpris2_navigation_capabilities()
    
    def _on_playback_state_changed(self, is_playing: bool):
        """Handle playback state change from playback controller."""
        # UI state is already updated by playback_controller via player_controls.set_playing()
        # This callback is available for any additional state-dependent logic if needed
        pass
    
    def _setup_mpris2(self):
        """Set up MPRIS2 callbacks for media key support."""
        if not self.mpris2 or not self.mpris2.player:
            return
        
        # Set playback control callbacks
        def on_seek(offset_microseconds: int):
            """Handle seek from MPRIS2 (offset in microseconds)."""
            # Get current position and add offset
            track = self.playlist_manager.get_current_track()
            if not self._is_video_track(track):
                # For MOC, get position from moc_sync
                current_pos = self.moc_sync.get_cached_position()
            else:
                # For internal player, get from playback_controller
                current_pos = self.playback_controller.get_current_position()
            
            offset_seconds = offset_microseconds / 1_000_000.0
            new_position = max(0.0, current_pos + offset_seconds)
            # playback_controller.seek() now handles updating player_controls
            self.playback_controller.seek(new_position)
        
        self.mpris2.set_playback_callbacks(
            on_play=self._on_play,
            on_pause=self._on_pause,
            on_stop=self._on_stop,
            on_next=self._on_next,
            on_previous=self._on_prev,
            on_seek=on_seek,
            on_set_volume=lambda volume: self._on_volume_changed(self.player_controls, volume)
        )
        
        # Set window control callbacks
        self.mpris2.set_window_callbacks(
            on_quit=lambda: self.close(),
            on_raise=lambda: self.present()
        )
    
    def _get_selected_track_index(self) -> int:
        """
        Get the index of the selected track in the playlist view.
        
        Returns:
            The 0-based index of the selected track, or -1 if no track is selected
        """
        selection = self.playlist_view.tree_view.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter:
            # Get the index from the first column (which contains the 1-based index)
            index = model[tree_iter][0] - 1  # Convert to 0-based
            playlist = self.playlist_manager.get_playlist()
            if 0 <= index < len(playlist):
                return index
        return -1
    
    def _on_play(self):
        """Handle play button click - delegate to playback controller."""
        selected_index = self._get_selected_track_index()
        self.playback_controller.play(selected_index if selected_index >= 0 else None)
    
    def _on_pause(self):
        """Handle pause button click - delegate to playback controller."""
        # Reset user interaction state to ensure duration labels update properly
        self.player_controls._user_interacting = False
        self.playback_controller.pause()
    
    def _on_stop(self):
        """Handle stop button click - delegate to playback controller."""
        self.playback_controller.stop()
        
        # Update MPRIS2 playback status
        if self.mpris2:
            self.mpris2.update_playback_status(False, is_paused=False)
        self._update_playlist_view()
        self._update_mpris2_navigation_capabilities()
    
    def _on_next(self):
        self.playback_controller.next()
        self._update_playlist_view()
        self._update_mpris2_navigation_capabilities()
    
    def _on_prev(self):
        """Handle previous button click - delegate to playback controller."""
        self.playback_controller.previous()
        # Update MPRIS2 navigation capabilities after track change
        self._update_mpris2_navigation_capabilities()
    
    def _on_seek(self, controls, position: float):
        """Handle seek operation - delegate to playback controller."""
        self.playback_controller.seek(position)
    
    def _on_volume_changed(self, controls, volume: float):
        """Handle volume change from UI slider - control system volume directly."""
        self.system_volume.set_volume(volume)
    
    def _on_system_volume_changed(self, volume: float):
        """Handle system volume change from external source (e.g., volume keys) - update UI."""
        self.player_controls.set_volume(volume)
    
    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_manager.get_current_track()
        if track and self._is_video_track(track):
            self.player_controls.set_playing(is_playing)
            # Update MPRIS2
            if self.mpris2:
                self.mpris2.update_playback_status(is_playing, is_paused=False)
                # Update CanGoNext/CanGoPrevious based on playlist state
                self._update_mpris2_navigation_capabilities()
    
    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_manager.get_current_track()
        if track and self._is_video_track(track):
            self.player_controls.update_progress(position, duration)
    
    def _on_track_loaded(self):
        """Handle track loaded - update duration and sync MOC."""
        # Wait a bit for GStreamer to determine duration, then update
        def update_after_load():
            duration = self.playback_controller.get_current_duration()
            position = self.playback_controller.get_current_position()
            # Update progress even if duration is 0 (will be updated when available)
            self.player_controls.update_progress(position, duration)
            # If duration is still 0, try again after a short delay
            if duration == 0:
                GLib.timeout_add(200, update_after_load)
            return False
        
        # Initial update
        GLib.timeout_add(100, update_after_load)
        
        # Sync MOC after track is loaded (only if using MOC for this track)
        track = self.playlist_manager.get_current_track()
        if self.use_moc and track and not self._is_video_track(track):
            self.moc_sync.sync_enabled = True
            self.moc_sync.sync_playlist_for_playback()
            # Ensure autonext and shuffle are set correctly
            self.moc_sync.set_shuffle(self.moc_sync.get_shuffle_enabled())
    
    def _on_track_finished(self):
        """Handle track finished - auto-advance to next track (internal player only)."""
        # This callback is only for internal player (video files)
        # MOC handles auto-advancement internally for audio files
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        # Check if there's a next track available
        if current_index < len(tracks) - 1:
            # There's a next track - advance to it
            if self.moc_sync.get_shuffle_enabled() if self.use_moc else False:
                self.playback_controller.play_random_track()
            else:
                # Auto-advance to next track in playlist
                next_track = self.playlist_manager.get_next_track()
                if next_track:
                    self._update_playlist_view()
                    self.playback_controller.play_current_track()
                else:
                    # Shouldn't happen, but handle gracefully
                    self.playback_controller.stop()
                    self.playlist_manager.set_current_index(-1)
                    self._update_playlist_view()
        else:
            # End of playlist reached
            self.playback_controller.stop()
            self.playlist_manager.set_current_index(-1)
            self._update_playlist_view()
    
    def _get_current_duration(self) -> float:
        """Get current track duration - delegate to playback_controller."""
        return self.playback_controller.get_current_duration()
    
    def _update_position(self):
        """Periodically update position display - from active player."""
        track = self.playlist_manager.get_current_track()
        if not track:
            # Update MPRIS2 position even when no track (set to 0)
            if self.mpris2:
                self.mpris2.update_position(0.0)
            return True
        
        if not self._is_video_track(track):
            # For MOC, position updates are handled by _update_moc_status() via update_status()
            # Don't call update_progress() here to avoid conflicts and stale position data
            # Only update MPRIS2 position
            if self.mpris2:
                position = self.moc_sync.get_cached_position()
                self.mpris2.update_position(position)
        else:
            # Update from internal player for video files
            if self.playback_controller.is_playing():
                position = self.playback_controller.get_current_position()
                duration = self.playback_controller.get_current_duration()
                # Always update progress to keep slider in sync
                if duration > 0:
                    self.player_controls.update_progress(position, duration)
                elif position > 0:
                    # If we have position but no duration yet, still update position
                    self.player_controls.update_progress(position, 0.0)
                # Update MPRIS2 position
                if self.mpris2:
                    self.mpris2.update_position(position)
            else:
                # Player not playing - update MPRIS2 with current position
                if self.mpris2:
                    position = self.playback_controller.get_current_position()
                    self.mpris2.update_position(position)
        return True

    def _update_moc_status(self):
        """Periodically pull status from MOC - sync UI and detect track changes."""
        if not self.use_moc:
            return False
        return self.moc_sync.update_status()

    def _on_shuffle_toggled(self, controls, active: bool):
        """Handle shuffle toggle state changes - delegate to moc_sync."""
        if self.use_moc:
            self.moc_sync.set_shuffle(active)
    
    def _on_autonext_toggled(self, controls, active: bool):
        """Handle autonext toggle state changes - delegate to moc_sync."""
        if self.use_moc:
            self.moc_sync.set_autonext_enabled(active)

    
    def _on_bt_device_selected(self, panel, device_path: str):
        """Handle Bluetooth device selection.
        
        When a device is selected from the Bluetooth panel:
        - If speaker mode is enabled and device is not paired, attempt to pair
        - If device is paired but not connected, attempt to connect
        - If device is already connected, show connection status
        """
        device = None
        for d in self.bt_manager.get_devices():
            if d.path == device_path:
                device = d
                break
        
        if not device:
            logger.warning("Device not found: %s", device_path)
            return
        
        # If speaker mode is enabled, handle connection automatically
        if self.bt_sink and self.bt_sink.is_sink_enabled:
            if not device.paired:
                # Attempt to pair with the device
                logger.info("Pairing with device: %s", device.name)
                self.bt_manager.pair_device(device_path)
            elif not device.connected:
                # Attempt to connect to the paired device
                logger.info("Connecting to device: %s", device.name)
                self.bt_manager.connect_device(device_path)
            else:
                # Device is already connected
                logger.info("Device %s is already connected", device.name)
        else:
            # Speaker mode not enabled - just show device info
            logger.debug("Selected device: %s (%s)", device.name, device.address)
            logger.debug("  Paired: %s, Connected: %s", device.paired, device.connected)
            logger.info("Note: Enable speaker mode to connect to devices")
    
    def _sync_playlist_file_op(self, op):
        """Helper: execute playlist file operation and refresh UI."""
        op()
        self.playlist_manager.load_playlist_from_file()
        self._update_playlist_view()
    
    def _on_add_track(self, browser, track: TrackMetadata):
        index = self.playlist_manager.get_playlist_length_file()
        self._sync_playlist_file_op(lambda: self.moc_sync.sync_add_track_file(index, track))
    
    def _on_add_album(self, browser, tracks):
        start_index = self.playlist_manager.get_playlist_length_file()
        for i, track in enumerate(tracks):
            self.moc_sync.sync_add_track_file(start_index + i, track)
        self.playlist_manager.load_playlist_from_file()
        self._update_playlist_view()
    
    def _on_playlist_remove_track(self, view, index: int):
        self._sync_playlist_file_op(lambda: self.moc_sync.sync_remove_track_file(index))
    
    def _on_playlist_move_up(self, view, index: int):
        if index > 0:
            self._sync_playlist_file_op(lambda: self.moc_sync.sync_move_track_file(index, index - 1))
    
    def _on_playlist_move_down(self, view, index: int):
        if index < self.playlist_manager.get_playlist_length_file() - 1:
            self._sync_playlist_file_op(lambda: self.moc_sync.sync_move_track_file(index, index + 1))
    
    def _on_playlist_refresh(self, view):
        """Handle refresh from MOC - reload the playlist from MOC's playlist file."""
        if self.use_moc:
            self.moc_sync.load_playlist_from_moc()
    
    def _on_playlist_clear(self, view):
        """Handle clearing playlist."""
        self.playback_controller.stop()
        if self.use_moc:
            self.moc_sync.stop()
            self.moc_sync.sync_playlist_to_moc(start_playback=False)
        
        # Update player controls state to show play button
        self.player_controls.set_playing(False)
        
        self.playlist_manager.clear()
        self._update_playlist_view()

    def _create_dialog_content(self, content):
        """Helper: set dialog content margins."""
        for attr in ['top', 'bottom', 'start', 'end']:
            getattr(content, f'set_margin_{attr}')(10)
    
    def _on_playlist_save(self, view):
        dialog = Gtk.Dialog(title="Save Playlist", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        self._create_dialog_content(content)
        content.append(Gtk.Label(label="Playlist name:"))
        entry = Gtk.Entry()
        entry.set_placeholder_text("My Playlist")
        content.append(entry)
        dialog.connect('response', lambda d, r: (self.playlist_manager.save_playlist(entry.get_text().strip()) if r == Gtk.ResponseType.OK and entry.get_text().strip() else None, d.close())[1])
        dialog.present()
    
    def _on_playlist_load(self, view):
        playlists = self.playlist_manager.list_playlists()
        if not playlists:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK, text="No Saved Playlists")
            dialog.set_detail_text("There are no saved playlists to load.")
            dialog.connect('response', lambda d, r: d.close())
            dialog.present()
            return
        dialog = Gtk.Dialog(title="Load Playlist", transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Load", Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        self._create_dialog_content(content)
        content.append(Gtk.Label(label="Select a playlist to load:"))
        store = Gtk.ListStore(str)
        for name in playlists:
            store.append([name])
        tree_view = Gtk.TreeView(model=store)
        tree_view.set_headers_visible(False)
        tree_view.append_column(Gtk.TreeViewColumn("Playlist", Gtk.CellRendererText(), text=0))
        if playlists:
            tree_view.get_selection().select_path(Gtk.TreePath.new_from_string("0"))
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_min_content_width(300)
        scrolled.set_child(tree_view)
        content.append(scrolled)
        def on_response(d, r):
            if r == Gtk.ResponseType.OK:
                sel = tree_view.get_selection()
                m, it = sel.get_selected()
                if it and self.playlist_manager.load_playlist(m[it][0]):
                    self._update_playlist_view()
                    if self.use_moc:
                        self.moc_sync.sync_playlist_to_moc(start_playback=False)
            d.close()
        dialog.connect('response', on_response)
        dialog.present()
