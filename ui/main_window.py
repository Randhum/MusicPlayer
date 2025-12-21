"""Main application window."""

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

from core.music_library import MusicLibrary
from core.audio_player import AudioPlayer
from core.playlist_manager import PlaylistManager
from core.bluetooth_manager import BluetoothManager
from core.metadata import TrackMetadata


class MainWindow(Gtk.ApplicationWindow):
    """Main application window."""
    
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Music Player")
        self.set_default_size(1200, 800)
        
        # Initialize core components
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        self.bt_manager = BluetoothManager()
        
        # Setup player callbacks
        self.player.on_state_changed = self._on_player_state_changed
        self.player.on_position_changed = self._on_player_position_changed
        self.player.on_track_finished = self._on_track_finished
        
        # Setup playlist manager
        self.playlist_manager.current_playlist = []
        self.playlist_manager.current_index = -1
        
        # Create UI
        self._create_ui()
        
        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)
        
        # Start position update timer
        GLib.timeout_add(500, self._update_position)
    
    def _create_ui(self):
        """Create the user interface."""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Top bar with search and Bluetooth
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
        
        top_bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        # Bluetooth panel (compact)
        self.bt_panel = BluetoothPanel(self.bt_manager)
        self.bt_panel.connect('device-selected', self._on_bt_device_selected)
        # Make it more compact for top bar
        bt_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        bt_box.append(self.bt_panel.status_icon)
        bt_box.append(self.bt_panel.status_label)
        top_bar.append(bt_box)
        
        main_box.append(top_bar)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Main content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        main_box.append(content_box)
        
        # Left sidebar - Library browser
        self.library_browser = LibraryBrowser()
        self.library_browser.connect('track-selected', self._on_track_selected)
        self.library_browser.connect('album-selected', self._on_album_selected)
        content_box.append(self.library_browser)
        
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        # Center - Playlist view
        self.playlist_view = PlaylistView()
        self.playlist_view.connect('track-activated', self._on_playlist_track_activated)
        content_box.append(self.playlist_view)
        
        content_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        
        # Right sidebar - Metadata panel
        self.metadata_panel = MetadataPanel()
        content_box.append(self.metadata_panel)
        
        # Bottom - Player controls
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.player_controls = PlayerControls()
        self.player_controls.connect('play-clicked', lambda w: self._on_play())
        self.player_controls.connect('pause-clicked', lambda w: self._on_pause())
        self.player_controls.connect('stop-clicked', lambda w: self._on_stop())
        self.player_controls.connect('next-clicked', lambda w: self._on_next())
        self.player_controls.connect('prev-clicked', lambda w: self._on_prev())
        self.player_controls.connect('seek-changed', self._on_seek)
        self.player_controls.connect('volume-changed', self._on_volume_changed)
        main_box.append(self.player_controls)
    
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
            # Add search results to playlist
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(results)
            self._update_playlist_view()
        else:
            # Clear playlist when search is cleared
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
            # Try to play current track from playlist
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
        # Position is already in seconds from the controls
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
        # Auto-play next track
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
        # Device selection is handled by the panel's connect button
        pass

