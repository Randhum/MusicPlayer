"""Main window with player controls and menu."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from typing import Optional

from ui.components.player_controls import PlayerControls
from ui.components.bluetooth_panel import BluetoothPanel
from core.metadata import TrackMetadata


class MainWindow(Gtk.ApplicationWindow):
    """Main application window with player controls."""
    
    def __init__(self, app, application):
        super().__init__(application=app)
        self.application = application
        self.set_title("Music Player - Controls")
        self.set_default_size(600, 200)
        
        # Create UI
        self._create_ui()
    
    def _create_ui(self):
        """Create the user interface."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Menu bar
        menu_bar = self._create_menu_bar()
        main_box.append(menu_bar)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
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
        self.bt_panel = BluetoothPanel(self.application.bt_manager, self.application.bt_sink)
        bt_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        bt_box.append(self.bt_panel.status_icon)
        bt_box.append(self.bt_panel.status_label)
        top_bar.append(bt_box)
        
        main_box.append(top_bar)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Player controls
        self.player_controls = PlayerControls()
        self.player_controls.connect('play-clicked', lambda w: self._on_play())
        self.player_controls.connect('pause-clicked', lambda w: self._on_pause())
        self.player_controls.connect('stop-clicked', lambda w: self._on_stop())
        self.player_controls.connect('next-clicked', lambda w: self._on_next())
        self.player_controls.connect('prev-clicked', lambda w: self._on_prev())
        self.player_controls.connect('shuffle-clicked', lambda w: self._on_shuffle())
        self.player_controls.connect('seek-changed', self._on_seek)
        self.player_controls.connect('volume-changed', self._on_volume_changed)
        main_box.append(self.player_controls)
    
    def _create_menu_bar(self):
        """Create the menu bar."""
        menu_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        menu_box.set_margin_start(5)
        menu_box.set_margin_end(5)
        menu_box.set_margin_top(5)
        menu_box.set_margin_bottom(5)
        
        # Simple button-based menu
        library_btn = Gtk.Button(label="Library")
        library_btn.connect('clicked', lambda w: self.application.show_library_window())
        menu_box.append(library_btn)
        
        playlist_btn = Gtk.Button(label="Playlist")
        playlist_btn.connect('clicked', lambda w: self.application.show_playlist_window())
        menu_box.append(playlist_btn)
        
        metadata_btn = Gtk.Button(label="Metadata")
        metadata_btn.connect('clicked', lambda w: self.application.show_metadata_window())
        menu_box.append(metadata_btn)
        
        return menu_box
    
    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            results = self.application.library.search(query)
            self.application.playlist_manager.clear()
            self.application.add_tracks_to_playlist(results)
        else:
            self.application.playlist_manager.clear()
            self.application.refresh_playlist_views()
    
    def _on_play(self):
        """Handle play button click."""
        if not self.application.player.current_track:
            self.application.play_current_track()
        else:
            self.application.player.play()
    
    def _on_pause(self):
        """Handle pause button click."""
        self.application.player.pause()
    
    def _on_stop(self):
        """Handle stop button click."""
        self.application.player.stop()
        self.application.playlist_manager.set_current_index(-1)
        self.application.refresh_playlist_views()
    
    def _on_next(self):
        """Handle next button click."""
        track = self.application.playlist_manager.get_next_track()
        if track:
            self.application.play_current_track()
    
    def _on_prev(self):
        """Handle previous button click."""
        track = self.application.playlist_manager.get_previous_track()
        if track:
            self.application.play_current_track()
    
    def _on_shuffle(self):
        """Handle shuffle button click."""
        self.application.playlist_manager.shuffle()
        self.application.refresh_playlist_views()
    
    def _on_seek(self, controls, position: float):
        """Handle seek operation."""
        self.application.player.seek(position)
    
    def _on_volume_changed(self, controls, volume: float):
        """Handle volume change."""
        self.application.player.set_volume(volume)
    
    def update_player_state(self, is_playing: bool):
        """Update player state display."""
        self.player_controls.set_playing(is_playing)
    
    def update_player_position(self, position: float, duration: float):
        """Update player position display."""
        self.player_controls.update_progress(position, duration)
    
    def set_current_track(self, track: TrackMetadata):
        """Set the current track display."""
        # Could show track name in main window if needed
        pass
    
    def update_playlist_view(self, tracks, current_index):
        """Update playlist view (if shown in main window)."""
        pass
    
    def refresh_library(self):
        """Refresh library display."""
        pass

