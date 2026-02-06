"""Player controls component - play/pause/next/prev/volume/progress."""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ui.components.bluetooth_panel import BluetoothPanel
    from ui.components.playlist_view import PlaylistView

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk

from core.events import EventBus
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

    def __init__(
        self,
        event_bus: EventBus,
        mpris2: Optional[MPRIS2Manager] = None,
        system_volume: Optional[SystemVolume] = None,
        window: Optional[Gtk.Window] = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)

        self._events = event_bus
        self.mpris2 = mpris2
        self.system_volume = system_volume
        self.window = window

        # Cached state from events (no AppState)
        self._last_position: float = 0.0
        self._last_duration: float = 0.0
        self._shuffle_enabled: bool = False
        self._loop_mode: int = 0
        self._playlist_length: int = 0
        self._current_index: int = -1
        self._playing: bool = False
        self._volume: float = 1.0

        self._seek_state = SeekState.IDLE
        self._updating_volume = False
        self._updating_toggle = False
        self._updating_progress = False
        self._value_changed_count: int = 0
        self._last_value_changed_time: int = 0
        self._drag_timeout_id: Optional[int] = None
        self._press_x: float = 0.0
        self._press_time: int = 0
        self._press_handled: bool = False

        for margin in ["top", "bottom", "start", "end"]:
            getattr(self, f"set_margin_{margin}")(15)

        self._create_ui()

        # Subscribe to state events
        self._events.subscribe(EventBus.PLAYBACK_STARTED, self._on_playback_started)
        self._events.subscribe(EventBus.PLAYBACK_PAUSED, self._on_playback_paused)
        self._events.subscribe(EventBus.PLAYBACK_STOPPED, self._on_playback_stopped)
        self._events.subscribe(EventBus.POSITION_CHANGED, self._on_position_changed)
        self._events.subscribe(EventBus.DURATION_CHANGED, self._on_duration_changed)
        self._events.subscribe(EventBus.TRACK_CHANGED, self._on_track_changed)
        self._events.subscribe(EventBus.SHUFFLE_CHANGED, self._on_shuffle_changed)
        self._events.subscribe(EventBus.LOOP_MODE_CHANGED, self._on_loop_mode_changed)
        self._events.subscribe(EventBus.VOLUME_CHANGED, self._on_volume_changed)
        self._events.subscribe(EventBus.PLAYLIST_CHANGED, self._on_playlist_changed)

        if self.system_volume:
            self.set_volume(self.system_volume.get_volume())
        if self.mpris2:
            self._setup_mpris2()

        # UI will sync from events (main_window calls playback_controller.publish_initial_state() after load)
        self._initialize_from_state()

    def _create_ui(self):
        """Create the UI components."""
        # Progress bar
        pb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.time_label = Gtk.Label(label="00:00")
        self.time_label.set_size_request(50, -1)
        pb.append(self.time_label)

        self.progress_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0
        )
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
        click_gesture.set_exclusive(
            False
        )  # Don't grab exclusive access - let scale handle drags
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
            (
                "prev",
                "media-skip-backward-symbolic",
                lambda: self._events.publish(EventBus.ACTION_PREV),
            ),
            (
                "play",
                "media-playback-start-symbolic",
                lambda: self._events.publish(EventBus.ACTION_PLAY),
            ),
            (
                "pause",
                "media-playback-pause-symbolic",
                lambda: self._events.publish(EventBus.ACTION_PAUSE),
            ),
            (
                "stop",
                "media-playback-stop-symbolic",
                lambda: self._events.publish(EventBus.ACTION_STOP),
            ),
            (
                "next",
                "media-skip-forward-symbolic",
                lambda: self._events.publish(EventBus.ACTION_NEXT),
            ),
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
        self._update_shuffle_style()
        cb.append(self.shuffle_button)

        self.loop_button = Gtk.ToggleButton()
        self._update_loop_icon()
        self.loop_button.set_size_request(bs, bs)
        self.loop_button.connect("clicked", self._on_loop_clicked)
        cb.append(self.loop_button)

        vb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        vb.set_halign(Gtk.Align.END)
        vb.append(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic"))
        self.volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01
        )
        self.volume_scale.set_value(1.0)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_size_request(140, 36)
        self.volume_scale.connect("value-changed", self._on_volume_scale_changed)
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
            if time_since_press < 200000:  # 200ms in microseconds
                duration = self._last_duration
                w = self.progress_scale.get_allocation().width
                if w > 0:
                    pct = max(0.0, min(100.0, (self._press_x / w) * 100.0))
                    if duration > 0:
                        pos = (pct / 100.0) * duration
                    else:
                        # If no duration, can't seek - just update UI to show click position
                        pos = 0.0

                    # Update scale and labels
                    self._updating_progress = True
                    self.progress_scale.set_value(pct)
                    if duration > 0:
                        self.update_time_labels(pos, duration)
                    self._updating_progress = False

                    # Seek immediately (click, not drag) - only if duration > 0
                    if duration > 0:
                        self._seek_state = SeekState.SEEKING
                        self._on_seek_changed(pos)
                        self._seek_state = SeekState.IDLE
        self._press_handled = False  # Reset for next press

    def _on_scale_value_changed(self, scale):
        """
        Handle scale value changes - detect drags and update labels.

        Gtk.Scale handles drags internally. We detect drags by tracking rapid value-changed signals.
        If value-changed fires multiple times rapidly, it's a drag. If it fires slowly, it's playback.
        """
        current_time = GLib.get_monotonic_time()
        time_since_last = (
            current_time - self._last_value_changed_time
            if self._last_value_changed_time > 0
            else 0
        )
        self._last_value_changed_time = current_time

        # If value-changed fires rapidly (< 150ms between calls), it's likely a drag
        is_rapid_change = time_since_last < 150000  # 150ms in microseconds

        # Ignore updates from update_progress() (normal playback updates)
        # These are marked with _updating_progress flag and occur when NOT dragging
        if self._updating_progress and self._seek_state != SeekState.DRAGGING:
            return

        # If this is a rapid change and we're not already dragging, start drag
        if is_rapid_change and self._seek_state == SeekState.IDLE:
            self._seek_state = SeekState.DRAGGING
            self._value_changed_count = 0
            self._press_handled = (
                True  # Mark that this press is being handled as a drag
            )
            # Cancel any existing timeout
            if self._drag_timeout_id is not None:
                GLib.source_remove(self._drag_timeout_id)
                self._drag_timeout_id = None
            # IMPORTANT: Set _updating_progress to False to ensure value-changed works during drag
            # This ensures that value-changed from user drag is not blocked
            self._updating_progress = False

        # During drag: update display (labels) only; do not seek playback until drag ends
        if self._seek_state == SeekState.DRAGGING:
            self._value_changed_count += 1
            duration = self._last_duration
            if duration > 0:
                scale_value = scale.get_value()
                pos = (scale_value / 100.0) * duration
                self.update_time_labels(pos, duration)
            # Reset timeout - when value-changed stops for 200ms, drag has ended and we seek once
            if self._drag_timeout_id is not None:
                GLib.source_remove(self._drag_timeout_id)
            self._drag_timeout_id = GLib.timeout_add(200, self._on_drag_timeout)

    def _on_drag_timeout(self) -> bool:
        """
        Called when value-changed hasn't fired for 200ms - drag has ended.
        Always reflect the drag: update labels and publish seek (controller clamps).
        """
        if self._seek_state == SeekState.DRAGGING:
            duration = self._last_duration
            scale_value = self.progress_scale.get_value()
            # Position from scale; when duration is 0 use 0 so controller can still update state
            pos = (
                (scale_value / 100.0) * duration
                if duration > 0
                else 0.0
            )
            # Always update labels to reflect the drag
            self.update_time_labels(pos, duration if duration > 0 else 0.0)

            # Always publish seek so state and (when backend active) playback reflect the drag
            self._seek_state = SeekState.SEEKING
            self._updating_progress = True
            self._on_seek_changed(pos)
            self._seek_state = SeekState.IDLE
            self._updating_progress = False

            self._value_changed_count = 0
            self._last_value_changed_time = 0

        self._drag_timeout_id = None
        return False  # Don't repeat

    def _on_volume_scale_changed(self, scale: Gtk.Scale) -> None:
        """Handle volume scale value-changed signal - extract value and call slider handler."""
        if not self._updating_volume:
            volume = scale.get_value()
            self._on_volume_slider_changed(volume)

    def _on_volume_slider_changed(self, volume: float) -> None:
        """Handle volume slider change - publish action (controller updates state and system volume)."""
        if not self._updating_volume:
            self._events.publish(EventBus.ACTION_SET_VOLUME, {"volume": volume})

    def _on_shuffle_toggled(self, button):
        """Handle shuffle toggle - publish action event."""
        if not self._updating_toggle:
            self._updating_toggle = True
            enabled = button.get_active()
            self._events.publish(EventBus.ACTION_SET_SHUFFLE, {"enabled": enabled})
            self._update_shuffle_style()
            self._updating_toggle = False

    def _on_loop_clicked(self, button):
        """Handle loop button click - publish action event."""
        if not self._updating_toggle:
            self._updating_toggle = True
            new_mode = (self._loop_mode + 1) % 3
            self._events.publish(EventBus.ACTION_SET_LOOP_MODE, {"mode": new_mode})
            self._updating_toggle = False

    def _update_shuffle_style(self) -> None:
        """Highlight shuffle button when active."""
        if self.shuffle_button.get_active():
            self.shuffle_button.add_css_class("suggested-action")
        else:
            self.shuffle_button.remove_css_class("suggested-action")

    def _update_loop_icon(self) -> None:
        """Update loop button icon from cached loop mode."""
        loop_mode = self._loop_mode
        icons = {
            0: ("media-playback-start-symbolic", "Loop mode: Forward"),
            1: ("media-playlist-repeat-song-symbolic", "Loop mode: Loop Track"),
            2: ("media-playlist-repeat-symbolic", "Loop mode: Loop Playlist"),
        }
        icon, tip = icons.get(loop_mode, icons[0])
        self.loop_button.set_child(Gtk.Image.new_from_icon_name(icon))
        self.loop_button.set_tooltip_text(tip)
        if loop_mode != 0:
            self.loop_button.add_css_class("suggested-action")
        else:
            self.loop_button.remove_css_class("suggested-action")
        # Keep toggle state in sync so button looks pressed when in loop mode
        if self.loop_button.get_active() != (loop_mode != 0):
            self._updating_toggle = True
            self.loop_button.set_active(loop_mode != 0)
            self._updating_toggle = False

    def _on_seek_changed(self, position: float) -> None:
        """Publish seek action (playback sync). Never called during drag - only on click or after drag end."""
        if self._seek_state == SeekState.DRAGGING:
            return
        self._events.publish(EventBus.ACTION_SEEK, {"position": position})

    def _initialize_from_state(self) -> None:
        """Initialize UI from cached state (set by events / publish_initial_state)."""
        self.set_playing(self._playing)
        if self._last_duration > 0:
            self.update_progress(self._last_position, self._last_duration)
        else:
            self.update_progress(0.0, 0.0)
        if not self._updating_toggle:
            self._updating_toggle = True
            self.shuffle_button.set_active(self._shuffle_enabled)
            self._update_shuffle_style()
            self._updating_toggle = False
        self._update_loop_icon()
        self.set_volume(self._volume)

    # ============================================================================
    # Event Handlers (State Updates)
    # ============================================================================

    def _on_playback_started(self, data: Optional[dict]) -> None:
        """Handle playback started event."""
        self._playing = True
        self.set_playing(True)

    def _on_playback_paused(self, data: Optional[dict]) -> None:
        """Handle playback paused event."""
        self._playing = False
        self.set_playing(False)

    def _on_playback_stopped(self, data: Optional[dict]) -> None:
        """Handle playback stopped event."""
        self._playing = False
        self.set_playing(False)
        # Reset timeline to 00:00
        self.update_progress(0.0, 0.0)

    def _on_position_changed(self, data: Optional[dict]) -> None:
        """Handle position changed event - cache and update UI."""
        if not data:
            return
        position = data.get("position", 0.0)
        duration = data.get("duration", self._last_duration)
        self._last_position = position
        if "duration" in data:
            self._last_duration = duration
        self.update_progress(position, duration)

    def _on_duration_changed(self, data: Optional[dict]) -> None:
        """Handle duration changed event."""
        if not data:
            return
        duration = data.get("duration", 0.0)
        self._last_duration = duration
        self.update_progress(self._last_position, duration)

    def _on_track_changed(self, data: Optional[dict]) -> None:
        """Handle track changed event."""
        if not data or "track" not in data:
            return
        track = data["track"]
        if self.mpris2:
            self.mpris2.update_metadata(track)
        self._update_mpris2_nav()

    def _on_playlist_changed(self, data: Optional[dict]) -> None:
        """Handle playlist changed event - cache and update MPRIS2 nav."""
        if data is not None:
            if "playlist_length" in data:
                self._playlist_length = int(data["playlist_length"])
            if "index" in data:
                self._current_index = int(data["index"])
        self._update_mpris2_nav()

    def _on_shuffle_changed(self, data: Optional[dict]) -> None:
        """Handle shuffle changed event."""
        if not data:
            return
        enabled = data.get("enabled", False)
        self._shuffle_enabled = enabled
        if not self._updating_toggle and self.shuffle_button.get_active() != enabled:
            self._updating_toggle = True
            self.shuffle_button.set_active(enabled)
            self._update_shuffle_style()
            self._updating_toggle = False

    def _on_loop_mode_changed(self, data: Optional[dict]) -> None:
        """Handle loop mode changed event."""
        if not data:
            return
        mode = data.get("mode", 0)
        self._loop_mode = mode
        self._update_loop_icon()

    def _on_volume_changed(self, data: Optional[dict]) -> None:
        """Handle volume changed event."""
        if not data:
            return
        volume = data.get("volume", 1.0)
        self._volume = volume
        self.set_volume(volume)

    def _update_mpris2_nav(self) -> None:
        """Update MPRIS2 navigation capabilities from cached state."""
        if not self.mpris2:
            return
        n = self._playlist_length
        idx = self._current_index
        self.mpris2.update_can_go_next(
            n > 0 and (self._shuffle_enabled or idx < n - 1)
        )
        self.mpris2.update_can_go_previous(idx > 0)

    def _setup_mpris2(self) -> None:
        """Set up MPRIS2 callbacks."""
        if not self.mpris2:
            return

        def on_seek(offset_us: int) -> None:
            pos = self._last_position
            new_pos = max(0.0, pos + (offset_us / 1_000_000.0))
            self._events.publish(EventBus.ACTION_SEEK, {"position": new_pos})

        self.mpris2.set_playback_callbacks(
            on_play=lambda: self._events.publish(EventBus.ACTION_PLAY),
            on_pause=lambda: self._events.publish(EventBus.ACTION_PAUSE),
            on_stop=lambda: self._events.publish(EventBus.ACTION_STOP),
            on_next=lambda: self._events.publish(EventBus.ACTION_NEXT),
            on_previous=lambda: self._events.publish(EventBus.ACTION_PREV),
            on_seek=on_seek,
            on_set_volume=lambda v: (
                self._events.publish(EventBus.ACTION_SET_VOLUME, {"volume": v})
                if 0.0 <= v <= 1.0
                else None
            ),
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
        # Clean up drag timeout if active
        if self._drag_timeout_id is not None:
            GLib.source_remove(self._drag_timeout_id)
            self._drag_timeout_id = None
        
        if self.system_volume:
            self.system_volume.cleanup()
        if self.mpris2:
            self.mpris2.cleanup()
