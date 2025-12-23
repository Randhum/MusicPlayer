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
from core.bluetooth_sink import BluetoothSink
from core.metadata import TrackMetadata
from core.moc_controller import MocController, MOC_PLAYLIST_PATH
from core.music_library import MusicLibrary
from core.playlist_manager import PlaylistManager
from ui.components.bluetooth_panel import BluetoothPanel
from ui.components.library_browser import LibraryBrowser
from ui.components.metadata_panel import MetadataPanel
from ui.components.player_controls import PlayerControls
from ui.components.playlist_view import PlaylistView
from ui.dock_manager import DockManager


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
        self.bt_sink = BluetoothSink(self.bt_manager)
        # MOC integration (Music On Console)
        self.moc_controller = MocController()
        self.use_moc = self.moc_controller.is_available()
        self._moc_last_position: float = 0.0
        self._moc_last_file: Optional[str] = None
        self._moc_playlist_mtime: float = 0.0
        
        # Initialize dock manager
        self.dock_manager = DockManager(self)

        # Playback options
        self.shuffle_enabled: bool = False
        
        # Setup player callbacks
        self.player.on_state_changed = self._on_player_state_changed
        self.player.on_position_changed = self._on_player_position_changed
        self.player.on_track_finished = self._on_track_finished
        
        # Setup playlist manager
        self.playlist_manager.current_playlist = []
        self.playlist_manager.current_index = -1
        
        # Create UI with dockable panels
        self._create_ui()
        
        # Load saved layout
        GLib.idle_add(self.dock_manager.load_layout)
        
        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)
        
        # Start position update timer
        GLib.timeout_add(POSITION_UPDATE_INTERVAL, self._update_position)
        # If MOC is available, periodically sync status from mocp
        if self.use_moc:
            if MOC_PLAYLIST_PATH.exists():
                try:
                    self._moc_playlist_mtime = MOC_PLAYLIST_PATH.stat().st_mtime
                except OSError:
                    self._moc_playlist_mtime = 0.0
            GLib.timeout_add(MOC_STATUS_UPDATE_INTERVAL, self._update_moc_status)
        
        # Connect close signal to save layout
        self.connect('close-request', self._on_close)
    
    def _is_video_track(self, track: Optional[TrackMetadata]) -> bool:
        """Return True if the given track is a video container we should play via GStreamer."""
        if not track or not track.file_path:
            return False
        suffix = Path(track.file_path).suffix.lower()
        return suffix in VIDEO_EXTENSIONS
    
    def _should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Return True if playback should use MOC instead of internal player."""
        return self.use_moc and not self._is_video_track(track)
    
    def _stop_internal_player_if_needed(self):
        """Stop internal GStreamer player if it's active (e.g., when switching to MOC)."""
        if self.player.is_playing or self.player.current_track:
            self.player.stop()
    
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
        self.playlist_view = PlaylistView()
        self.playlist_view.connect('track-activated', self._on_playlist_track_activated)
        self.playlist_view.connect('remove-track', self._on_playlist_remove_track)
        self.playlist_view.connect('move-track-up', self._on_playlist_move_up)
        self.playlist_view.connect('move-track-down', self._on_playlist_move_down)
        self.playlist_view.connect('clear-playlist', self._on_playlist_clear)
        self.playlist_view.connect('save-playlist', self._on_playlist_save)
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
    
    def _on_library_scan_complete(self):
        """Called when library scan is complete."""
        self.library_browser.populate(self.library)
        GLib.idle_add(self._update_playlist_view)
        # If MOC is available, sync playlist view to MOC's playlist
        if self.use_moc:
            GLib.idle_add(self._load_moc_playlist_from_moc)
    
    def _update_playlist_view(self):
        """Update the playlist view."""
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
        return False
    
    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            results = self.library.search(query)
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(results)
            self._update_playlist_view()
        else:
            self.playlist_manager.clear()
            self._update_playlist_view()
        if self.use_moc:
            self._sync_playlist_to_moc(start_playback=False)
    
    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection from library browser."""
        self.playlist_manager.clear()
        self.playlist_manager.add_track(track)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        # Prefer our GStreamer pipeline for video containers (e.g. MP4),
        # even when MOC is available.
        if self._should_use_moc(track):
            self._stop_internal_player_if_needed()
            self._sync_playlist_to_moc(start_playback=True)
        else:
            self._play_current_track()
    
    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        """Handle album selection from library browser."""
        self.playlist_manager.clear()
        self.playlist_manager.add_tracks(tracks)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        # Decide based on the first track; if it's a video container, prefer
        # our internal player over MOC for this album selection.
        first_track = tracks[0] if tracks else None
        if self._should_use_moc(first_track):
            self._stop_internal_player_if_needed()
            self._sync_playlist_to_moc(start_playback=True)
        else:
            self._play_current_track()
    
    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.playlist_manager.set_current_index(index)
        self._update_playlist_view()
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            # Ensure MOC playlist matches our view, then play the selected file
            self._stop_internal_player_if_needed()
            self._sync_playlist_to_moc(start_playback=False)
            if track:
                self.moc_controller.play_file(track.file_path)
        else:
            # For video containers or when MOC is unavailable, always use
            # our internal GStreamer-based player.
            self._play_current_track()
    
    def _play_current_track(self):
        """Play the current track from playlist."""
        track = self.playlist_manager.get_current_track()
        if track:
            self.player.load_track(track)
            self.player.play()
            self.metadata_panel.set_track(track)
    
    def _on_play(self):
        """Handle play button click."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self._stop_internal_player_if_needed()
            self.moc_controller.play()
        else:
            if not self.player.current_track:
                self._play_current_track()
            else:
                self.player.play()
    
    def _on_pause(self):
        """Handle pause button click."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self.moc_controller.pause()
        else:
            self.player.pause()
    
    def _on_stop(self):
        """Handle stop button click."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self.moc_controller.stop()
        else:
            self.player.stop()
            self.playlist_manager.set_current_index(-1)
            self._update_playlist_view()
    
    def _on_next(self):
        """Handle next button click."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self._stop_internal_player_if_needed()
            self.moc_controller.next()
        elif self.shuffle_enabled:
            self._play_random_track()
        else:
            track = self.playlist_manager.get_next_track()
            if track:
                self._update_playlist_view()
                self._play_current_track()
    
    def _on_prev(self):
        """Handle previous button click."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self._stop_internal_player_if_needed()
            self.moc_controller.previous()
        else:
            track = self.playlist_manager.get_previous_track()
            if track:
                self._update_playlist_view()
                self._play_current_track()
    
    def _on_seek(self, controls, position: float):
        """Handle seek operation."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            # Use relative seek based on last known position from MOC
            delta = position - self._moc_last_position
            self.moc_controller.seek_relative(delta)
        else:
            self.player.seek(position)
    
    def _on_volume_changed(self, controls, volume: float):
        """Handle volume change."""
        track = self.playlist_manager.get_current_track()
        if self._should_use_moc(track):
            self.moc_controller.set_volume(volume)
        else:
            self.player.set_volume(volume)
    
    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change."""
        self.player_controls.set_playing(is_playing)
    
    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change."""
        # In MOC mode we drive position from mocp status polling instead
        if not self.use_moc:
            self.player_controls.update_progress(position, duration)
    
    def _on_track_finished(self):
        """Handle track finished."""
        if self.shuffle_enabled:
            self._play_random_track()
        else:
            self._on_next()
    
    def _update_position(self):
        """Periodically update position display."""
        # When using MOC, playback position is updated by _update_moc_status
        if not self.use_moc and self.player.is_playing:
            position = self.player.get_position()
            duration = self.player.get_duration()
            self.player_controls.update_progress(position, duration)
        return True

    def _update_moc_status(self):
        """Periodically pull status from MOC and sync UI/playlist."""
        if not self.use_moc:
            return False

        status = self.moc_controller.get_status()
        if not status:
            return True  # Try again later

        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))
        volume = float(status.get("volume", 1.0))

        # Remember last known position for relative seeks
        self._moc_last_position = position

        # Sync basic playback UI
        self.player_controls.set_playing(state == "PLAY")
        self.player_controls.update_progress(position, duration)
        self.player_controls.set_volume(volume)

        # If track changed, update metadata and reload playlist from MOC
        if file_path and file_path != self._moc_last_file:
            self._moc_last_file = file_path
            track = TrackMetadata(file_path)
            self.metadata_panel.set_track(track)

            # Always reload the playlist from MOC on track change to stay in sync
            self._load_moc_playlist_from_moc()
            # Select the current track
            playlist = self.playlist_manager.get_playlist()
            for idx, t in enumerate(playlist):
                if t.file_path == file_path:
                    self.playlist_manager.set_current_index(idx)
                    self._update_playlist_view()
                    break
        # Detect external playlist changes (e.g. from MOC UI) by watching the M3U file
        try:
            mtime = MOC_PLAYLIST_PATH.stat().st_mtime
        except OSError:
            # If the playlist file temporarily disappears (e.g. while MOC rewrites
            # it), don't treat this as a "real" mtime change; just keep the old
            # value so we only react when a concrete new file timestamp appears.
            mtime = self._moc_playlist_mtime
        if mtime != self._moc_playlist_mtime:
            self._moc_playlist_mtime = mtime
            self._load_moc_playlist_from_moc()

        return True

    def _on_shuffle_toggled(self, controls, active: bool):
        """Handle shuffle toggle state changes."""
        self.shuffle_enabled = active

    def _play_random_track(self):
        """Play a random track from the current playlist."""
        tracks = self.playlist_manager.get_playlist()
        if not tracks:
            return
        current_index = self.playlist_manager.get_current_index()
        if len(tracks) == 1:
            new_index = 0
        else:
            indices = [i for i in range(len(tracks)) if i != current_index]
            if not indices:
                return
            new_index = random.choice(indices)
        self.playlist_manager.set_current_index(new_index)
        self._update_playlist_view()
        self._play_current_track()
    
    def _on_bt_device_selected(self, panel, device_path: str):
        """Handle Bluetooth device selection."""
        pass
    
    def _on_add_track(self, browser, track: TrackMetadata):
        """Handle 'Add to Playlist' from library browser context menu."""
        self.playlist_manager.add_track(track)
        self._update_playlist_view()
        if self.use_moc:
            self._sync_playlist_to_moc(start_playback=False)
    
    def _on_add_album(self, browser, tracks):
        """Handle 'Add Album to Playlist' from library browser context menu."""
        self.playlist_manager.add_tracks(tracks)
        self._update_playlist_view()
        if self.use_moc:
            self._sync_playlist_to_moc(start_playback=False)
    
    def _on_playlist_remove_track(self, view, index: int):
        """Handle track removal from playlist."""
        self.playlist_manager.remove_track(index)
        self._update_playlist_view()
        if self.use_moc:
            self._sync_playlist_to_moc(start_playback=False)
    
    def _on_playlist_move_up(self, view, index: int):
        """Handle moving track up in playlist."""
        if index > 0:
            self.playlist_manager.move_track(index, index - 1)
            self._update_playlist_view()
            if self.use_moc:
                self._sync_playlist_to_moc(start_playback=False)
    
    def _on_playlist_move_down(self, view, index: int):
        """Handle moving track down in playlist."""
        if index < len(self.playlist_manager.current_playlist) - 1:
            self.playlist_manager.move_track(index, index + 1)
            self._update_playlist_view()
            if self.use_moc:
                self._sync_playlist_to_moc(start_playback=False)
    
    def _on_playlist_refresh(self, view):
        """Handle refresh from MOC - reload the playlist from MOC's playlist file."""
        if self.use_moc:
            self._load_moc_playlist_from_moc()
    
    def _on_playlist_clear(self, view):
        """Handle clearing playlist."""
        if self.use_moc:
            self.moc_controller.stop()
        else:
            self.player.stop()
        self.playlist_manager.clear()
        self._update_playlist_view()
        if self.use_moc:
            self._sync_playlist_to_moc(start_playback=False)

    def _sync_playlist_to_moc(self, start_playback: bool = False):
        """Push the current GUI playlist into MOC's internal playlist."""
        if not self.use_moc:
            return
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        if not tracks:
            # Clear MOC playlist
            self.moc_controller.set_playlist([], -1, start_playback=False)
            return
        self.moc_controller.set_playlist(
            tracks,
            current_index=current_index if start_playback else -1,
            start_playback=start_playback,
        )
    
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

    def _load_moc_playlist_from_moc(self):
        """Replace current playlist with tracks from MOC's playlist file."""
        tracks, current_index = self.moc_controller.get_playlist()
        self.playlist_manager.clear()
        if tracks:
            self.playlist_manager.add_tracks(tracks)
            if current_index >= 0:
                self.playlist_manager.set_current_index(current_index)
        self._update_playlist_view()
        return False
    
    def _on_save_dialog_response(self, dialog, response, entry):
        """Handle save dialog response."""
        if response == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                self.playlist_manager.save_playlist(name)
        dialog.close()
