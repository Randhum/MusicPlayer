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
from core.app_state import AppState
from core.audio_player import AudioPlayer
from core.bluetooth_manager import BluetoothManager
from core.bluetooth_sink import BluetoothSink
from core.events import EventBus
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.mpris2 import MPRIS2Manager
from core.music_library import MusicLibrary
from core.playback_controller import PlaybackController
from core.playlist_manager import PlaylistManager
from core.system_volume import SystemVolume
from ui.components.bluetooth_panel import BluetoothPanel
from ui.components.library_browser import LibraryBrowser
from ui.components.metadata_panel import MetadataPanel
from ui.components.player_controls import PlayerControls
from ui.components.playlist_view import PlaylistView
from ui.dock_manager import DockManager

logger = get_logger(__name__)


# Update intervals (milliseconds) - moved to PlaybackController

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

        # Initialize event bus and state (foundation layer)
        self.event_bus = EventBus()
        self.app_state = AppState(self.event_bus)

        # Initialize core components (backends)
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.playlist_manager = PlaylistManager()
        # Initialize BT manager with event bus
        self.bt_manager = BluetoothManager(parent_window=self, event_bus=self.event_bus)
        # Initialize BT sink with event bus
        self.bt_sink = BluetoothSink(self.bt_manager, event_bus=self.event_bus)
        # System volume control
        self.system_volume = SystemVolume(on_volume_changed=self._on_system_volume_changed)
        # MOC integration (Music On Console)
        self.moc_controller = MocController()
        self.use_moc = self.moc_controller.is_available()

        # MPRIS2 integration for desktop/media key support
        self.mpris2 = MPRIS2Manager()

        # Initialize playback controller (mediator)
        self.playback_controller = PlaybackController(
            app_state=self.app_state,
            event_bus=self.event_bus,
            internal_player=self.player,
            moc_controller=self.moc_controller,
            bt_sink=self.bt_sink,
        )

        # Initialize dock manager (needed before UI creation)
        self.dock_manager = DockManager(self)

        # Create UI with dockable panels
        self._create_ui()

        # Load current playlist from auto-save file on startup
        if self.playlist_manager.load_current_playlist():
            # Restore state from saved playlist
            tracks = self.playlist_manager.get_playlist()
            current_index = self.playlist_manager.get_current_index()
            self.app_state.set_playlist(tracks, current_index)

        # Load saved layout
        GLib.idle_add(self.dock_manager.load_layout)

        # Start library scan
        self.library.scan_library(callback=self._on_library_scan_complete)

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
        # Library browser will be created after playlist_view
        # We'll set references after UI creation
        self.library_browser = LibraryBrowser(
            playlist_view=None,  # Will be set after playlist_view is created
            player_controls=None,  # Will be set after player_controls is created
        )
        self.library_browser.connect("track-selected", self._on_track_selected)
        self.library_browser.connect("album-selected", self._on_album_selected)

    def _create_playlist_view(self):
        """Create and configure the playlist view."""
        self.playlist_view = PlaylistView(
            app_state=self.app_state,
            event_bus=self.event_bus,
            playlist_manager=self.playlist_manager,
            window=self,
        )
        self.playlist_view.connect("track-activated", self._on_playlist_track_activated)
        self.playlist_view.connect("current-index-changed", self._on_playlist_current_index_changed)
        # Show refresh button only when MOC is available
        self.playlist_view.set_moc_mode(self.use_moc)

    def _create_metadata_panel(self):
        """Create the metadata panel."""
        self.metadata_panel = MetadataPanel(event_bus=self.event_bus)

    def _create_bluetooth_panel(self):
        """Create the Bluetooth panel with speaker mode support."""
        self.bt_panel = BluetoothPanel(
            bt_manager=self.bt_manager,
            bt_sink=self.bt_sink,
            event_bus=self.event_bus,
        )
        # Device selection is handled internally by bluetooth_panel

    def _create_player_controls(self):
        """Create player controls."""
        self.player_controls = PlayerControls(
            app_state=self.app_state,
            event_bus=self.event_bus,
            mpris2=self.mpris2,
            system_volume=self.system_volume,
            window=self,
        )

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
        # Cleanup playback controller (includes MOC shutdown)
        if hasattr(self, "playback_controller"):
            self.playback_controller.cleanup()
        # Cleanup Bluetooth resources
        if hasattr(self, "bt_sink"):
            self.bt_sink.cleanup()
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
        # PlaybackController handles MOC playlist loading

    def _populate_library_browser(self):
        """Populate library browser (called via idle_add for non-blocking)."""
        self.library_browser.populate(self.library)
        return False  # Don't repeat

    def _on_search_changed(self, entry):
        """Handle search entry changes."""
        query = entry.get_text()
        if query:
            results = self.library.search(query)
            self.playlist_view.clear()
            self.playlist_view.add_tracks(results)
        else:
            self.playlist_view.clear()

    def _on_track_selected(self, browser, track: TrackMetadata):
        """Handle track selection from library browser."""
        self.playlist_view.replace_and_play_track(track)

    def _on_album_selected(self, browser, tracks: List[TrackMetadata]):
        """Handle album selection from library browser."""
        self.playlist_view.replace_and_play_album(tracks)

    def _on_playlist_track_activated(self, view, index: int):
        """Handle track activation in playlist - delegate to playlist_view."""
        # PlaylistView now handles this internally via play_track_at_index()
        # Keep signal connection for potential external coordination if needed
        pass

    def _on_playlist_current_index_changed(self, view, index: int):
        """Handle current index change - for external coordination only."""
        # MOC sync is now handled internally in playlist_view.play_track_at_index()
        # Keep this handler only if needed for metadata panel or other external coordination
        pass

    def _on_track_changed(self, controls, track: TrackMetadata):
        """Handle track change from player_controls (legacy signal)."""
        # Metadata panel now subscribes to events directly
        # MPRIS2 navigation is updated via events
        pass

    def _on_system_volume_changed(self, volume: float):
        """Handle system volume change from external source (e.g., volume keys) - update UI."""
        self.app_state.set_volume(volume)

    def _on_shuffle_toggled(self, controls, active: bool):
        """Handle shuffle toggle state changes (legacy signal)."""
        # Shuffle state is now managed by AppState and events
        pass

