"""Main application window with dockable panels."""

import random
from pathlib import Path
from typing import Optional, List

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib

from core.audio_player import AudioPlayer, VIDEO_EXTENSIONS
from core.bluetooth_manager import BluetoothManager
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
        
        # Setup player callbacks
        self.player.on_state_changed = self._on_player_state_changed
        self.player.on_position_changed = self._on_player_position_changed
        self.player.on_track_finished = self._on_track_finished
        self.player.on_track_loaded = self._on_track_loaded
        
        # Playlist manager is initialized with empty state by default
        
        # Create UI with dockable panels (needed before MOC sync helper)
        self._create_ui()
        
        # Set up MPRIS2 callbacks after UI is created
        self._setup_mpris2()
    
    def _setup_mpris2(self):
        """Set up MPRIS2 callbacks for desktop integration."""
        if not self.mpris2:
            return
        
        # Set callbacks even if service isn't ready yet - they'll be used when service is initialized
        # Set playback control callbacks
        self.mpris2.set_playback_callbacks(
            on_play=self._on_play,
            on_pause=self._on_pause,
            on_stop=self._on_stop,
            on_next=self._on_next,
            on_previous=self._on_prev,
        )
        
        # Set window control callbacks
        self.mpris2.set_window_callbacks(
            on_quit=self.close,
            on_raise=self.present,
        )
        
        # Initialize MOC sync helper (after UI is created)
        self.moc_sync = MocSyncHelper(
            self.moc_controller,
            self.playlist_manager,
            self.player_controls,
            self.metadata_panel,
            self.playlist_view,
            self._is_video_track
        )
        self.moc_sync.on_track_finished = self._on_moc_track_finished
        self.moc_sync.on_shuffle_changed = self._on_moc_shuffle_changed
        
        # Load saved layout
        GLib.idle_add(self.dock_manager.load_layout)
        
        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)
        
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
    
    def _should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """
        Return True if playback should use MOC instead of internal player.
        
        Architecture Note: This application uses a dual playback engine approach:
        - MOC (Music On Console): Handles audio file playback (MP3, FLAC, OGG, etc.)
          - Provides robust audio handling, gapless playback, and format support
          - Used when MOC is available and track is not a video container
        - GStreamer (internal player): Handles video container playback (MP4, MKV, WebM, etc.)
          - Required for video files as MOC doesn't support video containers
          - Also serves as fallback if MOC is unavailable
        
        This separation allows leveraging the best tool for each use case.
        """
        return self.use_moc and not self._is_video_track(track)
    
    def _stop_internal_player_if_needed(self):
        """Stop internal GStreamer player if it's active (e.g., when switching to MOC)."""
        if self.player.is_playing or self.player.current_track:
            self.player.stop()
    
    def _stop_all_players(self):
        """Stop all players (MOC and internal) before starting a new track."""
        # Stop internal player if playing
        if self.player.is_playing or self.player.current_track:
            self.player.stop()
        
        # Stop MOC if playing
        if self.use_moc:
            status = self.moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self.moc_controller.stop()
    
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
        """)
        
        display = self.get_display()
        Gtk.StyleContext.add_provider_for_display(
            display,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
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
        self.playlist_view = PlaylistView(self.playlist_manager)
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
        self.bt_panel = BluetoothPanel(self.bt_manager)
        self.bt_panel.connect('device-selected', self._on_bt_device_selected)
    
    def _create_player_controls(self):
        """Create player controls."""
        self.player_controls = PlayerControls()
        # Connect playback callback so player_controls can trigger playback
        self.player_controls.set_play_current_track_callback(self._play_current_track)
        self.player_controls.connect('play-clicked', lambda w: self._on_play())
        self.player_controls.connect('pause-clicked', lambda w: self._on_pause())
        self.player_controls.connect('stop-clicked', lambda w: self._on_stop())
        self.player_controls.connect('next-clicked', lambda w: self._on_next())
        self.player_controls.connect('prev-clicked', lambda w: self._on_prev())
        self.player_controls.connect('seek-changed', self._on_seek)
        self.player_controls.connect('volume-changed', self._on_volume_changed)
        self.player_controls.connect('shuffle-toggled', self._on_shuffle_toggled)
    
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
        self.player.cleanup()
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
        
        # Cleanup library watcher
        if hasattr(self, 'library') and hasattr(self.library, 'stop_watching'):
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
        # We need to ensure our playlist index matches and playback continues
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()
        
        # Check if there's a next track available
        if current_index < len(tracks) - 1:
            # There's a next track - advance to it
            if self.shuffle_enabled:
                self._play_random_track()
            else:
                # Advance to next track in playlist
                next_track = self.playlist_view.get_next_track()
                if next_track:
                    # MOC should already be playing the next track (autonext),
                    # but verify and sync playlist to ensure consistency
                    self.moc_sync.update_moc_playlist(start_playback=True)
                    self.moc_controller.enable_autonext()
                else:
                    # Shouldn't happen, but handle gracefully
                    self.moc_controller.stop()
                    self.playlist_view.set_current_index(-1)
        else:
            # End of playlist - stop playback
            self.moc_controller.stop()
            self.playlist_view.set_current_index(-1)
    
    def _on_moc_shuffle_changed(self, shuffle_enabled: bool):
        """Handle shuffle state change from MOC."""
        self.shuffle_enabled = shuffle_enabled
        self.player_controls.shuffle_button.set_active(shuffle_enabled)
    
    
    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            results = self.library.search(query)
            self.playlist_view.clear()
            self.playlist_view.add_tracks(results)
        else:
            self.playlist_view.clear()
        if self.use_moc:
            self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection from library browser."""
        self.playlist_view.clear()
        self.playlist_view.add_track(track)
        self.playlist_view.set_current_index(0)
        # Always use internal player
        self._play_current_track()
    
    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        """Handle album selection from library browser."""
        self.playlist_view.clear()
        self.playlist_view.add_tracks(tracks)
        self.playlist_view.set_current_index(0)
        # Always use internal player
        self._play_current_track()
    
    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.playlist_view.set_current_index(index)
        # Trigger playback through player_controls
        self.player_controls.play_current_track()
    
    def _play_current_track(self):
        """Play the current track from playlist - use MOC for audio, internal player for video."""
        track = self.playlist_view.get_current_track()
        if not track:
            return
        
        # Validate track file exists
        if not track.file_path:
            logger.error("Track has no file path")
            return
        
        from pathlib import Path
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            logger.error("Track file does not exist: %s", track.file_path)
            return
        
        # Stop all currently playing tracks before starting a new one
        self._stop_all_players()
        
        # Reset position display when starting a new track
        self.player_controls.update_progress(0.0, 0.0)
        
        # Reset end-detection flag for new track
        if self.use_moc:
            self.moc_sync.reset_end_detection()
        
        # Decide which player to use based on file type
        if self._should_use_moc(track):
            # Use MOC for audio files - app is master, MOC does playback
            self._stop_internal_player_if_needed()
            # Sync playlist to MOC and start playback
            if self.use_moc:
                self.moc_sync.sync_enabled = True
                self.moc_sync.update_moc_playlist(start_playback=True)
                # Sync shuffle state
                if self.shuffle_enabled:
                    self.moc_controller.enable_shuffle()
                else:
                    self.moc_controller.disable_shuffle()
                self.moc_controller.enable_autonext()
        else:
            # Use internal player for video files
            self.player.load_track(track)
            self.player.play()
            
            # Sync MOC playlist (but don't play in MOC for video files)
            if self.use_moc:
                self.moc_sync.sync_enabled = True
                self.moc_sync.update_moc_playlist(start_playback=False)
        
        self.metadata_panel.set_track(track)
        
        # Update MPRIS2 metadata
        if self.mpris2:
            self.mpris2.update_metadata(track)
    
    def _on_play(self):
        """Handle play button - route to active player (MOC/internal/BT)."""
        # Check if BT playback is active
        if self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control('play')
            return
        
        track = self.playlist_view.get_current_track()
        if not track:
            return
        
        if self._should_use_moc(track):
            # Use MOC for audio files
            self._stop_internal_player_if_needed()
            # Get fresh status to check current state
            moc_status = self.moc_controller.get_status(force_refresh=True)
            if not moc_status:
                # No status available, start playback from current track
                self._play_current_track()
            else:
                moc_state = moc_status.get("state", "STOP")
                moc_file = moc_status.get("file_path")
                
                # Normalize paths for comparison
                from pathlib import Path
                track_file_abs = str(Path(track.file_path).resolve()) if track.file_path else None
                moc_file_abs = str(Path(moc_file).resolve()) if moc_file else None
                
                if moc_state == "PAUSE":
                    # MOC is paused - check if it's paused on the current track
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        # MOC is paused on the current track - just resume
                        self.moc_controller.play()
                        self.player_controls.set_playing(True)
                    else:
                        # MOC is paused on a different track - start current track
                        self._play_current_track()
                elif moc_state == "PLAY":
                    # Already playing - check if it's playing the current track
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        # Already playing the current track - do nothing
                        pass
                    else:
                        # Playing a different track - start current track
                        self._play_current_track()
                else:
                    # STOP or other state
                    # If MOC has a file_path, it means it was playing something
                    # Check if it matches our current track
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        # MOC was playing our current track but stopped - try to resume
                        # Use jump to current index and play
                        current_index = self.playlist_view.get_current_index()
                        if current_index >= 0:
                            # Jump to current track and play
                            if self.moc_controller.jump_to_index(current_index, start_playback=True):
                                self.player_controls.set_playing(True)
                                return
                        # Fallback: just call play
                        self.moc_controller.play()
                        self.player_controls.set_playing(True)
                    else:
                        # MOC is stopped and not on our current track - start current track
                        # This will sync playlist and start from current_index
                        self._play_current_track()
        else:
            # Use internal player for video files
            if not self.player.current_track:
                self._play_current_track()
            else:
                self.player.play()
    
    def _on_pause(self):
        """Handle pause button - route to active player."""
        # Check if BT playback is active
        if self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control('pause')
            return
        
        track = self.playlist_view.get_current_track()
        if not track:
            return
        
        if self._should_use_moc(track):
            # Use MOC for audio files
            self.moc_controller.pause()
            # Update UI immediately (update_status will also update, but this is immediate feedback)
            self.player_controls.set_playing(False)
        else:
            # Use internal player for video files
            self.player.pause()
            # UI is updated via _on_player_state_changed callback
    
    def _on_stop(self):
        """Handle stop button - route to active player."""
        # Check if BT playback is active
        if self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control('stop')
            return
        
        track = self.playlist_view.get_current_track()
        if self._should_use_moc(track):
            # Use MOC for audio files
            self.moc_controller.stop()
        else:
            # Use internal player for video files
            self.player.stop()
        
        self.playlist_view.set_current_index(-1)
    
    def _on_next(self):
        """Handle next button - route to active player."""
        # Check if BT playback is active
        if self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control('next')
            return
        
        if self.shuffle_enabled:
            self._play_random_track()
        else:
            track = self.playlist_view.get_next_track()
            if track:
                self._play_current_track()
    
    def _on_prev(self):
        """Handle prev button - route to active player."""
        # Check if BT playback is active
        if self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control('prev')
            return
        
        track = self.playlist_view.get_previous_track()
        if track:
            self._play_current_track()
        
        # Update MPRIS2
        if self.mpris2:
            tracks = self.playlist_view.get_playlist()
            current_index = self.playlist_view.get_current_index()
            self.mpris2.update_can_go_next(current_index < len(tracks) - 1)
            self.mpris2.update_can_go_previous(current_index > 0)
    
    def _on_seek(self, controls, position: float):
        """Handle seek operation - route to appropriate player."""
        track = self.playlist_view.get_current_track()
        if not track:
            return
        
        if self._should_use_moc(track):
            # Use MOC for audio files
            # Set seeking flag first to prevent update_status from interfering
            self.moc_sync._seeking = True
            
            # Get current position (use cached if available to avoid too many status calls)
            current_pos = self.moc_sync.get_cached_position()
            if current_pos == 0.0:
                # No cached position, get fresh status
                status = self.moc_controller.get_status(force_refresh=True)
                if status:
                    current_pos = float(status.get("position", 0.0))
                else:
                    self.moc_sync._seeking = False
                    return
            
            delta = position - current_pos
            
            # Only seek if delta is significant (avoid tiny seeks that might cause issues)
            if abs(delta) > 0.5:
                # Perform the seek
                self.moc_controller.seek_relative(delta)
                
                # Reset end-detection flag if we seek away from the end
                duration = self.moc_sync.get_cached_duration()
                if duration > 0 and position < duration - 1.0:
                    self.moc_sync.reset_end_detection()
                
                # Update cached position immediately to reflect the seek
                self.moc_sync.last_position = position
                
                # Clear seeking flag after a delay to allow position to update
                # This prevents update_status from immediately overwriting the seeked position
                GLib.timeout_add(500, lambda: setattr(self.moc_sync, '_seeking', False))
            else:
                # Delta is too small, just update the display
                duration = self._get_current_duration()
                self.player_controls.update_progress(position, duration)
                self.moc_sync._seeking = False
                return
        else:
            # Use internal player for video files
            self.player.seek(position)
        
        # Update position display and reset seeking state so slider resumes updating
        duration = self._get_current_duration()
        self.player_controls.update_progress(position, duration)
        self.player_controls.reset_seeking()
    
    def _on_volume_changed(self, controls, volume: float):
        """Handle volume change from UI slider - control system volume directly."""
        self.system_volume.set_volume(volume)
    
    def _on_system_volume_changed(self, volume: float):
        """Handle system volume change from external source (e.g., volume keys) - update UI."""
        self.player_controls.set_volume(volume)
    
    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_view.get_current_track()
        if track and not self._should_use_moc(track):
            self.player_controls.set_playing(is_playing)
            # Update MPRIS2
            if self.mpris2:
                self.mpris2.update_playback_status(is_playing, is_paused=False)
    
    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change - only for internal player (video files)."""
        # Only update if we're using internal player (video files)
        track = self.playlist_view.get_current_track()
        if track and not self._should_use_moc(track):
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
        if self.use_moc and track and self._should_use_moc(track):
            self.moc_sync.sync_enabled = True
            self.moc_sync.update_moc_playlist(start_playback=True)
            self.moc_controller.enable_autonext()
            # Sync shuffle state
            if self.shuffle_enabled:
                self.moc_controller.enable_shuffle()
            else:
                self.moc_controller.disable_shuffle()
            self.moc_controller.enable_autonext()
    
    def _on_track_finished(self):
        """Handle track finished - auto-advance to next track (internal player only)."""
        # This callback is only for internal player (video files)
        # MOC handles auto-advancement internally for audio files
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()
        
        # Check if there's a next track available
        if current_index < len(tracks) - 1:
            # There's a next track - advance to it
            if self.shuffle_enabled:
                self._play_random_track()
            else:
                # Auto-advance to next track in playlist
                next_track = self.playlist_view.get_next_track()
                if next_track:
                    self._play_current_track()
                else:
                    # Shouldn't happen, but handle gracefully
                    self.player.stop()
                    self.playlist_view.set_current_index(-1)
        else:
            # End of playlist reached
            self.player.stop()
            self.playlist_view.set_current_index(-1)
    
    def _get_current_duration(self) -> float:
        """Get current track duration from the active player."""
        track = self.playlist_view.get_current_track()
        if self._should_use_moc(track):
            # Use cached duration if available, otherwise get from MOC
            return self.moc_sync.get_cached_duration()
        else:
            # Get duration from internal player
            return self.player.get_duration()
    
    def _update_position(self):
        """Periodically update position display - from active player."""
        track = self.playlist_view.get_current_track()
        if not track:
            return True
        
        if self._should_use_moc(track):
            # For MOC, position updates are handled by _update_moc_status()
            # to avoid duplicate status calls. Only update slider if we have cached position.
            position = self.moc_sync.get_cached_position()
            duration = self.moc_sync.get_cached_duration()
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
        else:
            # Update from internal player for video files
            if self.player.is_playing:
                position = self.player.get_position()
                duration = self.player.get_duration()
                # Always update progress to keep slider in sync
                if duration > 0:
                    self.player_controls.update_progress(position, duration)
                elif position > 0:
                    # If we have position but no duration yet, still update position
                    self.player_controls.update_progress(position, 0.0)
        return True

    def _update_moc_status(self):
        """Periodically pull status from MOC - sync UI and detect track changes."""
        if not self.use_moc:
            return False
        return self.moc_sync.update_status()

    def _on_shuffle_toggled(self, controls, active: bool):
        """Handle shuffle toggle state changes."""
        self.shuffle_enabled = active
        # Sync shuffle state with MOC
        if self.use_moc:
            if active:
                self.moc_controller.enable_shuffle()
            else:
                self.moc_controller.disable_shuffle()

    def _sync_shuffle_from_moc(self):
        """Sync shuffle state from MOC to UI."""
        if not self.use_moc:
            return False
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None:
            self.shuffle_enabled = moc_shuffle
            self.player_controls.shuffle_button.set_active(moc_shuffle)
        return False

    def _play_random_track(self):
        """Play a random track from the current playlist."""
        tracks = self.playlist_view.get_playlist()
        if not tracks:
            return
        current_index = self.playlist_view.get_current_index()
        if len(tracks) == 1:
            new_index = 0
        else:
            indices = [i for i in range(len(tracks)) if i != current_index]
            if not indices:
                return
            new_index = random.choice(indices)
        self.playlist_view.set_current_index(new_index)
        self._play_current_track()
        # _play_current_track() already syncs MOC, so we're good
    
    def _on_bt_device_selected(self, panel, device_path: str):
        """Handle Bluetooth device selection.
        
        Device selection is now handled internally by the Bluetooth panel.
        This handler is kept for compatibility but device pairing/connection
        is managed by the panel itself.
        """
        # Device selection is handled internally by bluetooth_panel
        # This signal handler is kept for potential future use
        pass
    
    def _on_add_track(self, browser, track: TrackMetadata):
        """Handle 'Add to Playlist' from library browser context menu."""
        self.playlist_view.add_track(track)
        if self.use_moc:
            self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_add_album(self, browser, tracks):
        """Handle 'Add Album to Playlist' from library browser context menu."""
        self.playlist_view.add_tracks(tracks)
        if self.use_moc:
            self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_playlist_remove_track(self, view, index: int):
        """Handle track removal from playlist."""
        self.playlist_view.remove_track(index)
        if self.use_moc:
            self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_playlist_move_up(self, view, index: int):
        """Handle moving track up in playlist."""
        if index > 0:
            self.playlist_view.move_track(index, index - 1)
            if self.use_moc:
                self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_playlist_move_down(self, view, index: int):
        """Handle moving track down in playlist."""
        tracks = self.playlist_view.get_playlist()
        if index < len(tracks) - 1:
            self.playlist_view.move_track(index, index + 1)
            if self.use_moc:
                self.moc_sync.update_moc_playlist(start_playback=False)
    
    def _on_playlist_refresh(self, view):
        """Handle refresh from MOC - reload the playlist from MOC's playlist file."""
        if self.use_moc:
            # Force reload by checking if MOC has a playlist in memory
            # If MOC is playing, it definitely has a playlist, so we should try to load it
            status = self.moc_controller.get_status()
            if status and status.get("file_path"):
                # MOC is playing something, so it has a playlist in memory
                # Try to load it - if the file doesn't exist, we'll preserve current playlist
                self.moc_sync.load_playlist_from_moc()
            else:
                # MOC is not playing, so try to load from file
                # If file doesn't exist or is empty, we won't clear the current playlist
                self.moc_sync.load_playlist_from_moc()
    
    def _on_playlist_clear(self, view):
        """Handle clearing playlist."""
        self.player.stop()
        self.playlist_view.clear()
        if self.use_moc:
            self.moc_controller.stop()
            self.moc_sync.update_moc_playlist(start_playback=False)

    def _on_playlist_save(self, view):
        """Handle saving playlist."""
        dialog = Gtk.Dialog(title="Save Playlist", transient_for=self, modal=True)
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
        
        dialog.connect('response', lambda d, r: self._on_save_dialog_response(d, r, entry))
        dialog.present()

    
    def _on_save_dialog_response(self, dialog, response, entry):
        """Handle save dialog response."""
        if response == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                self.playlist_view.save_playlist(name)
        dialog.close()
    
    def _on_playlist_load(self, view):
        """Handle loading a saved playlist."""
        playlists = self.playlist_view.list_playlists()
        
        if not playlists:
            # Show a message dialog if no playlists exist
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="No Saved Playlists",
            )
            dialog.set_detail_text("There are no saved playlists to load.")
            dialog.connect('response', lambda d, r: d.close())
            dialog.present()
            return
        
        # Create dialog with playlist selection
        dialog = Gtk.Dialog(title="Load Playlist", transient_for=self, modal=True)
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
                    if self.playlist_view.load_playlist(playlist_name):
                        # Sync to MOC if using MOC
                        if self.use_moc:
                            self.moc_sync.update_moc_playlist(start_playback=False)
            dialog.close()
        
        dialog.connect('response', on_response)
        dialog.present()
