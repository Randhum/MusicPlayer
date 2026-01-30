"""Main application window with dockable panels."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
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
from core.app_state import AppState, PlaybackState
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
        self.set_resizable(True)

        # ---------------------------------------------------------------------
        # Layer 1: Foundation (event bus, playlist, app state)
        # ---------------------------------------------------------------------
        self.event_bus = EventBus()
        self.playlist_manager = PlaylistManager(event_bus=self.event_bus)
        self.app_state = AppState(
            self.event_bus, playlist_manager=self.playlist_manager
        )

        # ---------------------------------------------------------------------
        # Layer 2: Backends (library, players, MOC, BT, volume, MPRIS2)
        # ---------------------------------------------------------------------
        self.library = MusicLibrary()
        self.player = AudioPlayer()
        self.bt_manager = BluetoothManager(
            parent_window=self, event_bus=self.event_bus
        )
        self.bt_sink = BluetoothSink(
            self.bt_manager, event_bus=self.event_bus
        )
        self.system_volume = SystemVolume(
            on_volume_changed=self._on_system_volume_changed
        )
        self.moc_controller = MocController()
        self.use_moc = self.moc_controller.is_available()
        self.mpris2 = MPRIS2Manager()

        # ---------------------------------------------------------------------
        # Layer 3: Playback controller (mediator; uses app_state and backends)
        # ---------------------------------------------------------------------
        self.playback_controller = PlaybackController(
            app_state=self.app_state,
            event_bus=self.event_bus,
            internal_player=self.player,
            moc_controller=self.moc_controller,
            bt_sink=self.bt_sink,
            system_volume=self.system_volume,
        )

        # ---------------------------------------------------------------------
        # Layer 4: Dock manager (needed before UI)
        # ---------------------------------------------------------------------
        self.dock_manager = DockManager(self)

        # ---------------------------------------------------------------------
        # Layer 5: UI (playlist_view and player_controls first for cross-refs)
        # ---------------------------------------------------------------------
        self._create_ui()

        # ---------------------------------------------------------------------
        # Layer 6: Post-UI init (playlist load, metadata sync, layout, library)
        # ---------------------------------------------------------------------
        self._init_playlist_and_state()
        # Sync player controls (time labels, play state, volume) from state we just loaded
        self.player_controls._initialize_from_state()
        current_track = self.app_state.current_track
        if current_track:
            self.metadata_panel.sync_with_state(current_track)
        GLib.idle_add(self.dock_manager.load_layout)
        self.library.scan_library(callback=self._on_library_scan_complete)
        self.connect("close-request", self._on_close)

    def _init_playlist_and_state(self):
        """Load playlist (from MOC or auto-save) and sync playback state. Called after UI is created."""
        if self.use_moc:
            status = self.moc_controller.get_status(force_refresh=True)
            if status:
                self.app_state.set_active_backend("moc")
                if status.get("shuffle") is not None:
                    self.app_state.set_shuffle_enabled(bool(status["shuffle"]))
                if status.get("autonext") is not None:
                    self.app_state.set_autonext_enabled(bool(status["autonext"]))
                # Sync repeat state from MOC to loop mode
                # MOC only has repeat on/off, so map to LOOP_PLAYLIST (2) if on, LOOP_FORWARD (0) if off
                if status.get("repeat") is not None:
                    loop_mode = 2 if status["repeat"] else 0
                    self.app_state.set_loop_mode(loop_mode)
                tracks, current_index = self.moc_controller.get_playlist()
                if tracks:
                    logger.info(
                        "Syncing playlist from MOC on startup: %d tracks",
                        len(tracks),
                    )
                    self.app_state.set_playlist(tracks, current_index)
                else:
                    self.playlist_view.load_current_playlist()
                moc_state = (status.get("state") or "STOP").upper()
                if moc_state == "PLAY":
                    self.app_state.set_playback_state(PlaybackState.PLAYING)
                elif moc_state == "PAUSE":
                    self.app_state.set_playback_state(PlaybackState.PAUSED)
                else:
                    self.app_state.set_playback_state(PlaybackState.STOPPED)
                self.app_state.set_position(
                    float(status.get("position", 0) or 0)
                )
                self.app_state.set_duration(
                    float(status.get("duration", 0) or 0)
                )
                vol = status.get("volume")
                if vol is not None:
                    self.app_state.set_volume(float(vol))
            else:
                self.playlist_view.load_current_playlist()
        else:
            self.playlist_view.load_current_playlist()

    def _create_ui(self):
        """Create the user interface with dockable panels."""
        self._apply_css()

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        self._create_top_bar(main_box)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Create playlist_view and player_controls first (library_browser needs them)
        self._create_playlist_view()
        self._create_player_controls()
        self._create_library_browser()
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
            
            /* Playlist drag-to-reorder visual feedback */
            .playlist-tree.dragging {
                background: alpha(@theme_selected_bg_color, 0.1);
            }
            
            .playlist-tree.dragging row:selected {
                background: @theme_selected_bg_color;
                color: @theme_selected_fg_color;
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
        self.library_browser = LibraryBrowser(
            playlist_view=self.playlist_view,
            player_controls=self.player_controls,
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
        # PlaylistView handles track activation and index changes internally
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
        # Cleanup playlist view (includes timeout cleanup)
        if hasattr(self, "playlist_view"):
            self.playlist_view.cleanup()
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

    def _on_system_volume_changed(self, volume: float):
        """Handle system volume change from external source (e.g., volume keys) - update UI."""
        self.app_state.set_volume(volume)
