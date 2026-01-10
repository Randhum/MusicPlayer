"""Player controls component - play/pause/next/prev/volume/progress."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ui.components.bluetooth_panel import BluetoothPanel
    from ui.components.playlist_view import PlaylistView
    from ui.moc_sync import MocSyncHelper

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject, Gtk

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.audio_player import AudioPlayer
from core.workflow_utils import is_video_file, normalize_path
from core.metadata import TrackMetadata
from core.mpris2 import MPRIS2Manager
from core.system_volume import SystemVolume


class SeekState(Enum):
    """State machine for seek operations."""

    IDLE = "idle"  # Normal state, no user interaction
    DRAGGING = "dragging"  # User is dragging slider
    SEEKING = "seeking"  # Seek operation in progress


class PlayerControls(Gtk.Box):
    """Player controller - orchestrates playback across multiple engines."""

    LOOP_FORWARD = 0
    LOOP_TRACK = 1
    LOOP_PLAYLIST = 2

    __gsignals__ = {
        "play-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "pause-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "stop-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "next-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "prev-clicked": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "seek-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "volume-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        "shuffle-toggled": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "loop-mode-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "track-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(
        self,
        player: AudioPlayer,
        playlist_view: "PlaylistView",
        moc_sync: Optional["MocSyncHelper"] = None,
        bt_panel: Optional["BluetoothPanel"] = None,
        mpris2: Optional[MPRIS2Manager] = None,
        system_volume: Optional[SystemVolume] = None,
        window: Optional[Gtk.Window] = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)

        self.player = player
        self.playlist_view = playlist_view
        self.moc_sync = moc_sync
        self.bt_panel = bt_panel
        self.mpris2 = mpris2
        self.system_volume = system_volume
        self.window = window

        self._shuffle_enabled = False
        self._autonext_enabled = True
        self._loop_mode = self.LOOP_FORWARD
        self._seek_state = SeekState.IDLE
        self._duration = 0.0
        self._updating_volume = False
        self._updating_toggle = False
        self._updating_progress = (
            False  # Flag to prevent update_progress() from interfering during drag
        )
        self._value_changed_count: int = 0  # Track value-changed events during drag
        self._last_value_changed_time: int = 0  # Track when value-changed last fired
        self._drag_timeout_id: Optional[int] = None  # Timeout to detect drag end

        for margin in ["top", "bottom", "start", "end"]:
            getattr(self, f"set_margin_{margin}")(15)

        self._create_ui()

        if self.system_volume:
            self.set_volume(self.system_volume.get_volume())
        if self.mpris2:
            self._setup_mpris2()

        self.connect("seek-changed", lambda c, p: self.seek(p))
        self.connect(
            "volume-changed",
            lambda c, v: self.system_volume.set_volume(v) if self.system_volume else None,
        )

    def _create_ui(self):
        """Create the UI components."""
        # Progress bar
        pb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.time_label = Gtk.Label(label="00:00")
        self.time_label.set_size_request(50, -1)
        pb.append(self.time_label)

        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        self.progress_scale.set_size_request(-1, 36)

        # Connect to value-changed to update labels during drag
        # Gtk.Scale handles drags internally - we detect drags by tracking rapid value-changed signals
        self.progress_scale.connect("value-changed", self._on_scale_value_changed)
        # Use GestureClick for click-to-seek - set it to NOT interfere with scale's drag handling
        # By only handling clicks (not drags) and returning False, we let the scale handle drags normally
        click_gesture = Gtk.GestureClick.new()
        click_gesture.set_button(1)  # Left mouse button only
        click_gesture.set_exclusive(False)  # Don't grab exclusive access - let scale handle drags
        click_gesture.connect("pressed", self._on_scale_button_pressed)
        click_gesture.connect("released", self._on_scale_button_released)
        self.progress_scale.add_controller(click_gesture)
        pb.append(self.progress_scale)

        # Timer Label Box
        tlb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tlb.set_size_request(50, -1)
        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.set_size_request(50, -1)
        tlb.append(self.duration_label)
        self.time_left_label = Gtk.Label(label="-00:00")
        self.time_left_label.set_size_request(50, -1)
        self.time_left_label.set_css_classes(["dim-label"])
        tlb.append(self.time_left_label)
        pb.append(tlb)
        self.append(pb)

        # Control buttons
        cb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        cb.set_halign(Gtk.Align.CENTER)
        bs = 56

        for name, icon, action in [
            ("prev", "media-skip-backward-symbolic", lambda: self.previous_track()),
            (
                "play",
                "media-playback-start-symbolic",
                lambda: (self.resume(), self.emit("play-clicked")),
            ),
            (
                "pause",
                "media-playback-pause-symbolic",
                lambda: (self.pause(), self.emit("pause-clicked")),
            ),
            (
                "stop",
                "media-playback-stop-symbolic",
                lambda: (self.stop(), self.emit("stop-clicked")),
            ),
            ("next", "media-skip-forward-symbolic", lambda: self.next_track()),
        ]:
            b = Gtk.Button.new_from_icon_name(icon)
            b.set_size_request(bs, bs)
            b.connect("clicked", lambda btn, a=action: a())
            setattr(self, f"{name}_button", b)
            cb.append(b)

        self.pause_button.set_visible(False)

        self.shuffle_button = Gtk.ToggleButton()
        self.shuffle_button.set_child(
            Gtk.Image.new_from_icon_name("media-playlist-shuffle-symbolic")
        )
        self.shuffle_button.set_size_request(bs, bs)
        self.shuffle_button.set_tooltip_text("Shuffle playlist")
        self.shuffle_button.connect("toggled", self._on_shuffle_toggled)
        cb.append(self.shuffle_button)

        self.loop_button = Gtk.ToggleButton()
        '''
        define self.loop_method to default value IF no config loaded 
        -> Need to implement config manager
        '''
        self._update_loop_icon()
        self.loop_button.set_size_request(bs, bs)
        self.loop_button.connect("clicked", self._on_loop_clicked)
        cb.append(self.loop_button)

        vb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        vb.set_halign(Gtk.Align.END)
        vb.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01)
        self.volume_scale.set_value(1.0)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_size_request(140, 36)
        self.volume_scale.connect("value-changed", self._on_volume_changed)
        vb.append(self.volume_scale)
        cb.append(vb)
        self.append(cb)

    def set_playing(self, playing: bool):
        """Update button states."""
        self.play_button.set_visible(not playing)
        self.pause_button.set_visible(playing)

    def update_time_labels(self, position: float, duration: float) -> None:
        """Update time labels only (current time, duration, time left)."""
        # Clamp position to valid range
        position = max(0.0, min(position, duration if duration > 0 else position))
        self.time_label.set_text(self._format_time(position))
        self.duration_label.set_text(self._format_time(duration))
        # Calculate time left, ensuring it's never negative
        if duration > 0:
            time_left = max(0.0, duration - position)
            self.time_left_label.set_text(f"-{self._format_time(time_left)}")
        else:
            self.time_left_label.set_text("-00:00")

    def update_progress(self, position: float, duration: float) -> None:
        """
        Update progress bar and time labels.

        This is a pure UI update method - it never triggers seeks.
        Only updates UI if we're idle (during drag/seeking, handlers control it).
        During drag, labels show drag position, not actual track position.
        """
        # Completely skip updates during drag or seek to prevent any interference
        # This ensures drag position always overrides playback position
        # Check at the very beginning - if we're dragging, don't do anything
        if self._seek_state != SeekState.IDLE:
            return
        
        # Also skip if we're in the middle of updating (prevents recursive calls)
        if self._updating_progress:
            return

        position = max(0.0, min(position, duration if duration > 0 else position))
        self._duration = duration

        # Final check right before set_value() - critical for preventing race conditions
        # Even if we passed the first check, if drag started in the meantime, abort now
        if self._seek_state != SeekState.IDLE:
            return
        
        # Use _updating_progress flag to prevent value-changed signal from interfering
        # This flag tells value-changed handler that this is from playback, not user drag
        self._updating_progress = True
        try:
            progress = (position / duration * 100.0) if duration > 0 else 0.0
            # Only call set_value() if we're still IDLE (triple-check for safety)
            if self._seek_state == SeekState.IDLE:
                self.progress_scale.set_value(max(0.0, min(100.0, progress)))
                self.update_time_labels(position, duration)
        finally:
            self._updating_progress = False

    def set_volume(self, volume: float) -> None:
        """Set volume slider value."""
        self._updating_volume = True
        self.volume_scale.set_value(volume)
        self._updating_volume = False

    def _format_time(self, seconds: float) -> str:
        """Format time to MM:SS."""
        return f"{int(max(0, seconds) // 60):02d}:{int(max(0, seconds) % 60):02d}"

    def _ensure_duration(self):
        """Ensure duration is set."""
        if self._duration <= 0:
            self._duration = self.get_current_duration()

    def _on_scale_button_pressed(self, controller, n_press, x, y):
        """Handle button press on scale - store position for potential click-to-seek."""
        # Store press position and time for click detection
        # If user doesn't drag (no rapid value-changed), we'll seek on release
        self._press_x = x
        self._press_time = GLib.get_monotonic_time()
        self._press_handled = False  # Track if we've already handled this press
    
    def _on_scale_button_released(self, controller, n_press, x, y):
        """Handle button release on scale - seek if it was a click (not a drag)."""
        # Only seek if:
        # 1. We're not currently dragging (drag timeout will handle drag seeks)
        # 2. We haven't already handled this press (e.g., via value-changed drag detection)
        # 3. The press and release happened quickly (click, not drag)
        if self._seek_state == SeekState.IDLE and not self._press_handled:
            time_since_press = GLib.get_monotonic_time() - self._press_time
            # If press and release happened within 200ms and no drag was detected, it's a click
            if time_since_press < 200000:  # 200ms in microseconds
                self._ensure_duration()
                if self._duration > 0:
                    w = self.progress_scale.get_allocation().width
                    if w > 0:
                        pct = max(0.0, min(100.0, (self._press_x / w) * 100.0))
                        pos = (pct / 100.0) * self._duration
                        
                        # Update scale and labels
                        self._updating_progress = True
                        self.progress_scale.set_value(pct)
                        self.update_time_labels(pos, self._duration)
                        self._updating_progress = False
                        
                        # Seek immediately (click, not drag)
                        self._seek_state = SeekState.SEEKING
                        self.emit("seek-changed", pos)
                        self._seek_state = SeekState.IDLE
        self._press_handled = False  # Reset for next press
    
    def _on_scale_value_changed(self, scale):
        """
        Handle scale value changes - detect drags and update labels.
        
        Gtk.Scale handles drags internally. We detect drags by tracking rapid value-changed signals.
        If value-changed fires multiple times rapidly, it's a drag. If it fires slowly, it's playback.
        """
        current_time = GLib.get_monotonic_time()
        time_since_last = current_time - self._last_value_changed_time if self._last_value_changed_time > 0 else 0
        self._last_value_changed_time = current_time
        
        # If value-changed fires rapidly (< 100ms between calls), it's likely a drag
        # If it fires slowly (> 100ms), it's likely a playback update
        is_rapid_change = time_since_last < 100000  # 100ms in microseconds
        
        # Ignore updates from update_progress() (normal playback updates)
        # These are marked with _updating_progress flag and occur when NOT dragging
        if self._updating_progress and self._seek_state != SeekState.DRAGGING:
            return
        
        # If this is a rapid change and we're not already dragging, start drag
        if is_rapid_change and self._seek_state == SeekState.IDLE:
            self._seek_state = SeekState.DRAGGING
            self._value_changed_count = 0
            self._press_handled = True  # Mark that this press is being handled as a drag
            # Cancel any existing timeout
            if self._drag_timeout_id is not None:
                GLib.source_remove(self._drag_timeout_id)
                self._drag_timeout_id = None
            # IMPORTANT: Set _updating_progress to False to ensure value-changed works during drag
            # This ensures that value-changed from user drag is not blocked
            self._updating_progress = False
        
        # During drag: Always update labels from scale value
        if self._seek_state == SeekState.DRAGGING:
            self._value_changed_count += 1
            self._ensure_duration()
            if self._duration > 0:
                scale_value = scale.get_value()
                pos = (scale_value / 100.0) * self._duration
                # Always update labels from scale value during drag
                self.update_time_labels(pos, self._duration)
            
            # Reset timeout - if value-changed doesn't fire for 200ms, drag has ended
            if self._drag_timeout_id is not None:
                GLib.source_remove(self._drag_timeout_id)
            self._drag_timeout_id = GLib.timeout_add(200, self._on_drag_timeout)


    def _on_drag_timeout(self) -> bool:
        """
        Called when value-changed hasn't fired for 200ms - drag has ended.
        Perform seek to final position.
        """
        if self._seek_state == SeekState.DRAGGING:
            self._ensure_duration()
            
            if self._duration > 0:
                # Get current scale value and seek to that position
                scale_value = self.progress_scale.get_value()
                pos = (scale_value / 100.0) * self._duration
                
                # Update labels
                self.update_time_labels(pos, self._duration)
                
                # Seek to that position
                self._seek_state = SeekState.SEEKING
                self._updating_progress = True
                self.emit("seek-changed", pos)
                self._seek_state = SeekState.IDLE
                self._updating_progress = False
                
                # Reset drag tracking
                self._value_changed_count = 0
                self._last_value_changed_time = 0
        
        self._drag_timeout_id = None
        return False  # Don't repeat


    def _on_volume_changed(self, scale):
        """Handle volume change."""
        if not self._updating_volume:
            self.emit("volume-changed", scale.get_value())

    def _on_shuffle_toggled(self, button):
        if not self._updating_toggle:
            self._updating_toggle = True
            self.set_shuffle_enabled(button.get_active())
            self.emit("shuffle-toggled", button.get_active())
            self._updating_toggle = False

    def _on_loop_clicked(self, button):
        if not self._updating_toggle:
            self._updating_toggle = True
            self._loop_mode = (self._loop_mode + 1) % 3
            self._update_loop_icon()
            self.emit("loop-mode-changed", self._loop_mode)
            self._updating_toggle = False

    def _update_loop_icon(self):
        icons = {
            self.LOOP_FORWARD: ("media-playback-start-symbolic", "Loop mode: Forward"),
            self.LOOP_TRACK: ("media-playlist-repeat-song-symbolic", "Loop mode: Loop Track"),
            self.LOOP_PLAYLIST: ("media-playlist-repeat-symbolic", "Loop mode: Loop Playlist"),
        }
        icon, tip = icons.get(self._loop_mode, icons[self.LOOP_FORWARD])
        self.loop_button.set_child(Gtk.Image.new_from_icon_name(icon))
        self.loop_button.set_tooltip_text(tip)
        (
            self.loop_button.add_css_class
            if self._loop_mode != self.LOOP_FORWARD
            else self.loop_button.remove_css_class
        )("suggested-action")

    def set_shuffle_enabled(self, enabled: bool):
        self._shuffle_enabled = enabled
        if self.playlist_view:
            self.playlist_view.set_shuffle_enabled(enabled)
        if not self._updating_toggle and self.shuffle_button.get_active() != enabled:
            self._updating_toggle = True
            self.shuffle_button.set_active(enabled)
            self._updating_toggle = False

    @property
    def autonext_enabled(self) -> bool:
        return self._autonext_enabled

    @autonext_enabled.setter
    def autonext_enabled(self, enabled: bool):
        self._autonext_enabled = enabled
        self._sync_moc_options()

    @property
    def loop_mode(self) -> int:
        return self._loop_mode

    @loop_mode.setter
    def loop_mode(self, mode: int):
        if 0 <= mode <= 2:
            self._loop_mode = mode
            if not self._updating_toggle:
                self._update_loop_icon()

    def should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Check if MOC should be used for this track."""
        if not (self.moc_sync and self.moc_sync.use_moc and track and track.file_path):
            return False
        return not is_video_file(track.file_path)

    def _play_with_moc(self, track: TrackMetadata) -> None:
        """Play track using MOC."""
        self._stop_internal_player()
        if self.moc_sync:
            self.moc_sync.enable_sync()
            self.moc_sync.update_moc_playlist(start_playback=True)
            self._sync_moc_options()

    def _play_with_internal(self, track: TrackMetadata) -> None:
        """Play track using internal player."""
        # For video files, ensure MOC is stopped
        if self.moc_sync and self.moc_sync.use_moc:
            status = self.moc_sync.moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self.moc_sync.moc_controller.stop()
        self.player.load_track(track)
        self.player.play()

    def play_current_track(self):
        track = self.playlist_view.get_current_track()
        if not track or not track.file_path or not Path(track.file_path).exists():
            return

        self._stop_all_players()
        self.update_progress(0.0, 0.0)

        if self.should_use_moc(track):
            self._play_with_moc(track)
        else:
            self._play_with_internal(track)
        
        self.playlist_view._update_view()
        self.set_playing(True)
        self._duration = (
            track.duration if track.duration and track.duration > 0 else self.get_current_duration()
        )
        self.emit("track-changed", track)
        if self.mpris2:
            self.mpris2.update_metadata(track)

    def resume(self):
        if self._handle_bt("play"):
            return
        track = self.playlist_view.get_current_track()
        if not track:
            tracks = self.playlist_view.get_playlist()
            if tracks:
                self.playlist_view.set_current_index(0)
                if self.playlist_view.get_current_track():
                    self.play_current_track()
            return

        # Check if we have a paused track with duration available
        if track.duration and track.duration > 0:
            self._duration = track.duration

        if self.should_use_moc(track):
            self._resume_moc(track)
        else:
            self._resume_internal()

    def play(self):
        self.resume()

    def pause(self):
        if self._handle_bt("pause"):
            return
        track = self.playlist_view.get_current_track()
        if track:
            (
                self.moc_sync.pause
                if self.should_use_moc(track) and self.moc_sync
                else self.player.pause
            )()
        self.set_playing(False)

    def stop(self):
        if self._handle_bt("stop"):
            return
        track = self.playlist_view.get_current_track()
        if track:
            (
                self.moc_sync.stop
                if self.should_use_moc(track) and self.moc_sync
                else self.player.stop
            )()
        self.playlist_view.set_current_index(-1)
        self.set_playing(False)
        if self.mpris2:
            self.mpris2.update_playback_status(False, is_paused=False)

    def next_track(self):
        if not self._handle_bt("next"):
            track = self.playlist_view.get_next_track()
            if track:
                self.play_current_track()

    def previous_track(self):
        if not self._handle_bt("prev"):
            track = self.playlist_view.get_previous_track()
            if track:
                self.play_current_track()
            self._update_mpris2_nav()

    def seek(self, position: float):
        """
        Perform actual seek operation.

        This is called by the seek-changed signal handler.
        It performs the seek operation only - UI updates are handled separately.
        """
        track = self.playlist_view.get_current_track()
        if track:
            if self.should_use_moc(track) and self.moc_sync:
                self.moc_sync.seek(position, force=True)
            else:
                self.player.seek(position)

        # Don't update UI here - let position updates from player handle it
        # This prevents conflicts with drag operations and ensures single source of truth

    def get_current_duration(self) -> float:
        track = self.playlist_view.get_current_track()
        if self.should_use_moc(track) and self.moc_sync:
            # Use cached duration or get from status
            duration = self.moc_sync.last_duration if self.moc_sync.last_duration > 0 else 0.0
            if duration == 0:
                status = self.moc_sync.get_status(force_refresh=False)
                if status:
                    duration = float(status.get("duration", 0.0))
            return duration
        return self.player.get_duration()

    def _stop_internal_player(self):
        if self.player.is_playing or self.player.current_track:
            self.player.stop()

    def _stop_all_players(self):
        self._stop_internal_player()
        if self.moc_sync and self.moc_sync.use_moc:
            status = self.moc_sync.moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self.moc_sync.moc_controller.stop()

    def _normalize_path(self, file_path: Optional[str]) -> Optional[str]:
        """Normalize file path using centralized utility.

        Args:
            file_path: File path to normalize.

        Returns:
            Normalized path as string, or None if invalid.
        """
        normalized = normalize_path(file_path)
        return str(normalized) if normalized else None

    def _handle_bt(self, action: str) -> bool:
        if self.bt_panel and self.bt_panel.is_bt_playback_active():
            self.bt_panel.handle_playback_control(action)
            return True
        return False

    def _resume_moc(self, track: TrackMetadata) -> None:
        """Resume playback using MOC player."""
        # Ensure internal player is stopped first
        self._stop_internal_player()
        if self.moc_sync:
            # Check if track is paused and can be resumed
            status = self.moc_sync.get_status(force_refresh=True)
            if status:
                moc_state = status.get("state", "STOP")
                moc_file = status.get("file_path")
                if moc_file and track.file_path:
                    moc_file_abs = self._normalize_path(moc_file)
                    track_file_abs = self._normalize_path(track.file_path)
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        if moc_state == "PAUSE":
                            self.moc_sync.play()
                            self.set_playing(True)
                            return
                        elif moc_state == "PLAY":
                            self.set_playing(True)
                            return
            # Track not playing or paused - start playback
            self.play_current_track()

    def _resume_internal(self) -> None:
        # Ensure MOC is stopped first
        if self.moc_sync and self.moc_sync.use_moc:
            status = self.moc_sync.moc_controller.get_status(force_refresh=False)
            if status and status.get("state") in ("PLAY", "PAUSE"):
                self.moc_sync.moc_controller.stop()

        if self.player.current_track and not self.player.is_playing:
            self.player.play()
            self.set_playing(True)
        elif not self.player.current_track:
            self.play_current_track()

    def _sync_moc_options(self) -> None:
        """Sync shuffle and autonext options to MOC.
        
        Only sends commands if MOC's state differs from our desired state.
        This reduces unnecessary MOC commands and prevents race conditions.
        """
        if not (self.moc_sync and self.moc_sync.use_moc):
            return
        moc = self.moc_sync.moc_controller
        
        # Get current MOC state to avoid unnecessary commands
        moc_shuffle = moc.get_shuffle_state()
        moc_autonext = moc.get_autonext_state()
        
        # Only sync if state differs
        if moc_shuffle is not None and moc_shuffle != self._shuffle_enabled:
            (moc.enable_shuffle if self._shuffle_enabled else moc.disable_shuffle)()
        if moc_autonext is not None and moc_autonext != self._autonext_enabled:
            (moc.enable_autonext if self._autonext_enabled else moc.disable_autonext)()

    def _update_mpris2_nav(self) -> None:
        """Update MPRIS2 navigation capabilities."""
        if not self.mpris2:
            return
        tracks = self.playlist_view.get_playlist()
        idx = self.playlist_view.get_current_index()
        self.mpris2.update_can_go_next(
            len(tracks) > 0 and (self._shuffle_enabled or idx < len(tracks) - 1)
        )
        self.mpris2.update_can_go_previous(idx > 0)

    def _setup_mpris2(self) -> None:
        """Set up MPRIS2 callbacks."""
        if not self.mpris2:
            return

        def on_seek(offset_us: int) -> None:
            track = self.playlist_view.get_current_track()
            if track:
                pos = (
                    (self.moc_sync.last_position if self.moc_sync else 0.0)
                    if self.should_use_moc(track) and self.moc_sync
                    else self.player.get_position()
                )
                self.seek(max(0.0, pos + (offset_us / 1_000_000.0)))

        self.mpris2.set_playback_callbacks(
            on_play=self.resume,
            on_pause=self.pause,
            on_stop=self.stop,
            on_next=self.next_track,
            on_previous=self.previous_track,
            on_seek=on_seek,
            on_set_volume=lambda v: self.set_volume(v) if 0.0 <= v <= 1.0 else None,
        )
        if self.window:
            self.mpris2.set_window_callbacks(
                on_quit=lambda: self.window.close() if self.window else None,
                on_raise=lambda: self.window.present() if self.window else None,
            )

    def update_mpris2_navigation_capabilities(self) -> None:
        """Update MPRIS2 navigation capabilities."""
        self._update_mpris2_nav()

    def cleanup(self) -> None:
        if self.system_volume:
            self.system_volume.cleanup()
        if self.mpris2:
            self.mpris2.cleanup()
