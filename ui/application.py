"""Main application managing all windows."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib
from typing import Dict, Optional

from ui.windows.main_window import MainWindow
from ui.windows.library_window import LibraryWindow
from ui.windows.playlist_window import PlaylistWindow
from ui.windows.metadata_window import MetadataWindow

from core.music_library import MusicLibrary
from core.audio_player import AudioPlayer
from core.playlist_manager import PlaylistManager
from core.bluetooth_manager import BluetoothManager
from core.bluetooth_sink import BluetoothSink


class MusicPlayerApplication:
    """Manages the music player application and all its windows."""
    
    def __init__(self, app: Gtk.Application):
        self.app = app
        self.windows: Dict[str, Gtk.Window] = {}
        
        # Initialize core components (shared across windows)
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        
        # Create main window first (needed for BT agent dialogs)
        self._create_main_window()
        
        # Initialize Bluetooth manager with main window for pairing dialogs
        main_window = self.windows.get('main')
        self.bt_manager = BluetoothManager(parent_window=main_window)
        self.bt_sink = BluetoothSink(self.bt_manager)
        
        # Setup player callbacks (if player supports them)
        if hasattr(self.player, 'on_state_changed'):
            self.player.on_state_changed = self._on_player_state_changed
        if hasattr(self.player, 'on_position_changed'):
            self.player.on_position_changed = self._on_player_position_changed
        if hasattr(self.player, 'on_track_finished'):
            self.player.on_track_finished = self._on_track_finished
        
        # Setup playlist manager
        self.playlist_manager.current_playlist = []
        self.playlist_manager.current_index = -1
        
        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)
        
        # Start position update timer
        GLib.timeout_add(500, self._update_position)
    
    def _create_main_window(self):
        """Create the main window with player controls."""
        main_win = MainWindow(self.app, self)
        self.windows['main'] = main_win
        main_win.present()
    
    def show_library_window(self):
        """Show or create the library browser window."""
        if 'library' not in self.windows or self.windows['library'].is_destroyed():
            lib_win = LibraryWindow(self.app, self)
            self.windows['library'] = lib_win
        self.windows['library'].present()
    
    def show_playlist_window(self):
        """Show or create the playlist window."""
        if 'playlist' not in self.windows or self.windows['playlist'].is_destroyed():
            playlist_win = PlaylistWindow(self.app, self)
            self.windows['playlist'] = playlist_win
        self.windows['playlist'].present()
    
    def show_metadata_window(self):
        """Show or create the metadata window."""
        if 'metadata' not in self.windows or self.windows['metadata'].is_destroyed():
            meta_win = MetadataWindow(self.app, self)
            self.windows['metadata'] = meta_win
        self.windows['metadata'].present()
    
    def _on_library_scan_complete(self):
        """Called when library scan is complete."""
        if 'library' in self.windows:
            self.windows['library'].refresh_library()
        if 'main' in self.windows:
            self.windows['main'].refresh_library()
    
    def _on_player_state_changed(self, is_playing: bool):
        """Handle player state change."""
        if 'main' in self.windows:
            self.windows['main'].update_player_state(is_playing)
    
    def _on_player_position_changed(self, position: float, duration: float):
        """Handle player position change."""
        if 'main' in self.windows:
            self.windows['main'].update_player_position(position, duration)
    
    def _on_track_finished(self):
        """Handle track finished."""
        # Auto-play next track
        track = self.playlist_manager.get_next_track()
        if track:
            self.play_current_track()
    
    def _update_position(self):
        """Periodically update position display."""
        if hasattr(self.player, 'is_playing') and self.player.is_playing:
            position = self.player.get_position()
            duration = self.player.get_duration()
            if 'main' in self.windows:
                self.windows['main'].update_player_position(position, duration)
        return True
    
    def play_current_track(self):
        """Play the current track from playlist."""
        track = self.playlist_manager.get_current_track()
        if track:
            self.player.load_track(track)
            self.player.play()
            if 'metadata' in self.windows:
                self.windows['metadata'].set_track(track)
            if 'main' in self.windows:
                self.windows['main'].set_current_track(track)
    
    def add_track_to_playlist(self, track):
        """Add a track to the playlist."""
        self.playlist_manager.add_track(track)
        self.refresh_playlist_views()
    
    def add_tracks_to_playlist(self, tracks):
        """Add multiple tracks to the playlist."""
        self.playlist_manager.add_tracks(tracks)
        self.refresh_playlist_views()
    
    def refresh_playlist_views(self):
        """Refresh all playlist views."""
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if 'playlist' in self.windows:
            self.windows['playlist'].update_playlist(tracks, current_index)
        if 'main' in self.windows:
            self.windows['main'].update_playlist_view(tracks, current_index)

