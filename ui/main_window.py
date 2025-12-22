"""Main application window with dockable panels."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib
from typing import Optional, List

from ui.components.library_browser import LibraryBrowser
from ui.components.playlist_view import PlaylistView
from ui.components.player_controls import PlayerControls
from ui.components.metadata_panel import MetadataPanel
from ui.components.bluetooth_panel import BluetoothPanel
from ui.dock_manager import DockManager, DockablePanel

from core.music_library import MusicLibrary
from core.audio_player import AudioPlayer
from core.playlist_manager import PlaylistManager
from core.bluetooth_manager import BluetoothManager
from core.bluetooth_sink import BluetoothSink
from core.metadata import TrackMetadata


class MainWindow(Gtk.ApplicationWindow):
    """Main application window with modular dockable panels."""
    
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Music Player")
        self.set_default_size(1200, 800)
        
        # Initialize core components
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        self.bt_manager = BluetoothManager()
        self.bt_sink = BluetoothSink(self.bt_manager)
        
        # Initialize dock manager
        self.dock_manager = DockManager(self)
        
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
        GLib.timeout_add(500, self._update_position)
        
        # Connect close signal to save layout
        self.connect('close-request', self._on_close)
    
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
    
    def _reattach_panel(self, panel_id: str):
        """Reattach a detached panel to its original position."""
        panel = self.dock_manager.panels.get(panel_id)
        if not panel:
            return
        
        if panel_id == "library":
            self.left_paned.set_start_child(panel)
        elif panel_id == "playlist":
            self.left_paned.set_end_child(panel)
        elif panel_id == "metadata":
            self.right_paned.set_start_child(panel)
        elif panel_id == "bluetooth":
            self.right_paned.set_end_child(panel)
    
    def _on_close(self, window):
        """Handle window close."""
        self.dock_manager.cleanup()
        self.player.cleanup()
        return False  # Allow close to proceed
    
    def _on_library_scan_complete(self):
        """Called when library scan is complete."""
        self.library_browser.populate(self.library)
        GLib.idle_add(self._update_playlist_view)
    
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
    
    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection from library browser."""
        self.playlist_manager.clear()
        self.playlist_manager.add_track(track)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        self._play_current_track()
    
    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        """Handle album selection from library browser."""
        self.playlist_manager.clear()
        self.playlist_manager.add_tracks(tracks)
        self.playlist_manager.set_current_index(0)
        self._update_playlist_view()
        self._play_current_track()
    
    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist."""
        self.playlist_manager.set_current_index(index)
        self._update_playlist_view()
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
        if not self.player.current_track:
            self._play_current_track()
        else:
            self.player.play()
    
    def _on_pause(self):
        """Handle pause button click."""
        self.player.pause()
    
    def _on_stop(self):
        """Handle stop button click."""
        self.player.stop()
        self.playlist_manager.set_current_index(-1)
        self._update_playlist_view()
    
    def _on_next(self):
        """Handle next button click."""
        track = self.playlist_manager.get_next_track()
        if track:
            self._update_playlist_view()
            self._play_current_track()
    
    def _on_prev(self):
        """Handle previous button click."""
        track = self.playlist_manager.get_previous_track()
        if track:
            self._update_playlist_view()
            self._play_current_track()
    
    def _on_seek(self, controls, position: float):
        """Handle seek operation."""
        self.player.seek(position)
    
    def _on_volume_changed(self, controls, volume: float):
        """Handle volume change."""
        self.player.set_volume(volume)
    
    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change."""
        self.player_controls.set_playing(is_playing)
    
    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change."""
        self.player_controls.update_progress(position, duration)
    
    def _on_track_finished(self):
        """Handle track finished."""
        self._on_next()
    
    def _update_position(self):
        """Periodically update position display."""
        if self.player.is_playing:
            position = self.player.get_position()
            duration = self.player.get_duration()
            self.player_controls.update_progress(position, duration)
        return True
    
    def _on_bt_device_selected(self, panel, device_path: str):
        """Handle Bluetooth device selection."""
        pass
    
    def _on_add_track(self, browser, track: TrackMetadata):
        """Handle 'Add to Playlist' from library browser context menu."""
        self.playlist_manager.add_track(track)
        self._update_playlist_view()
    
    def _on_add_album(self, browser, tracks):
        """Handle 'Add Album to Playlist' from library browser context menu."""
        self.playlist_manager.add_tracks(tracks)
        self._update_playlist_view()
    
    def _on_playlist_remove_track(self, view, index: int):
        """Handle track removal from playlist."""
        self.playlist_manager.remove_track(index)
        self._update_playlist_view()
    
    def _on_playlist_move_up(self, view, index: int):
        """Handle moving track up in playlist."""
        if index > 0:
            self.playlist_manager.move_track(index, index - 1)
            self._update_playlist_view()
    
    def _on_playlist_move_down(self, view, index: int):
        """Handle moving track down in playlist."""
        if index < len(self.playlist_manager.current_playlist) - 1:
            self.playlist_manager.move_track(index, index + 1)
            self._update_playlist_view()
    
    def _on_playlist_clear(self, view):
        """Handle clearing playlist."""
        self.player.stop()
        self.playlist_manager.clear()
        self._update_playlist_view()
    
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
                self.playlist_manager.save_playlist(name)
        dialog.close()
