"""Player controls component - play/pause/next/prev/volume/progress."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GObject, GLib


class PlayerControls(Gtk.Box):
    """Component for player controls (play/pause, volume, progress)."""
    
    __gsignals__ = {
        'play-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'pause-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'stop-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'next-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'prev-clicked': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'seek-changed': (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        'volume-changed': (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        'shuffle-toggled': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        'autonext-toggled': (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        # Touch-friendly margins
        self.set_margin_top(15)
        self.set_margin_bottom(15)
        self.set_margin_start(15)
        self.set_margin_end(15)
        
        # Progress bar and time labels
        progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        self.time_label = Gtk.Label(label="00:00")
        self.time_label.set_size_request(50, -1)
        progress_box.append(self.time_label)
        
        self.progress_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 0.1
        )
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        # Touch-friendly height (slightly larger)
        self.progress_scale.set_size_request(-1, 36)
        
        # GTK Scale handles user interaction (clicking/dragging) automatically
        # We use gesture controllers to detect when user starts/finishes interacting
        # This allows us to distinguish user interaction from programmatic updates
        gesture_click = Gtk.GestureClick()
        gesture_click.connect('pressed', self._on_progress_pressed)
        gesture_click.connect('released', self._on_progress_released)
        self.progress_scale.add_controller(gesture_click)
        
        # Use value-changed to update labels during user interaction
        self.progress_scale.connect('value-changed', self._on_progress_value_changed)
        progress_box.append(self.progress_scale)
        
        # Duration and time remaining labels in a vertical box
        time_labels_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.set_size_request(50, -1)
        time_labels_box.append(self.duration_label)
        
        self.time_remaining_label = Gtk.Label(label="-00:00")
        self.time_remaining_label.set_size_request(50, -1)
        self.time_remaining_label.add_css_class("dim-label")
        time_labels_box.append(self.time_remaining_label)
        
        progress_box.append(time_labels_box)
        
        self.append(progress_box)
        
        # Control buttons
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls_box.set_halign(Gtk.Align.CENTER)
        
        # Touch-friendly button sizes (slightly larger)
        button_size = 56  # Larger buttons for touch
        
        self.prev_button = Gtk.Button.new_from_icon_name("media-skip-backward-symbolic")
        self.prev_button.set_size_request(button_size, button_size)
        self.prev_button.connect('clicked', lambda btn: self.emit('prev-clicked'))
        controls_box.append(self.prev_button)
        
        self.play_button = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        self.play_button.set_size_request(button_size, button_size)
        self.play_button.connect('clicked', lambda btn: self.emit('play-clicked'))
        controls_box.append(self.play_button)
        
        self.pause_button = Gtk.Button.new_from_icon_name("media-playback-pause-symbolic")
        self.pause_button.set_size_request(button_size, button_size)
        self.pause_button.connect('clicked', lambda btn: self.emit('pause-clicked'))
        self.pause_button.set_visible(False)
        controls_box.append(self.pause_button)
        
        self.stop_button = Gtk.Button.new_from_icon_name("media-playback-stop-symbolic")
        self.stop_button.set_size_request(button_size, button_size)
        self.stop_button.connect('clicked', lambda btn: self.emit('stop-clicked'))
        controls_box.append(self.stop_button)
        
        self.next_button = Gtk.Button.new_from_icon_name("media-skip-forward-symbolic")
        self.next_button.set_size_request(button_size, button_size)
        self.next_button.connect('clicked', lambda btn: self.emit('next-clicked'))
        controls_box.append(self.next_button)
        
        # Shuffle toggle
        self.shuffle_button = Gtk.ToggleButton()
        shuffle_image = Gtk.Image.new_from_icon_name("media-playlist-shuffle-symbolic")
        self.shuffle_button.set_child(shuffle_image)
        self.shuffle_button.set_size_request(button_size, button_size)
        self.shuffle_button.set_tooltip_text("Shuffle playlist")
        self.shuffle_button.connect('toggled', self._on_shuffle_toggled)
        controls_box.append(self.shuffle_button)
        
        
        # Autonext toggle
        self.autonext_button = Gtk.ToggleButton()
        autonext_image = Gtk.Image.new_from_icon_name("media-playlist-repeat-symbolic")
        self.autonext_button.set_child(autonext_image)
        self.autonext_button.set_size_request(button_size, button_size)
        self.autonext_button.set_tooltip_text("Toggle Autonext")
        self.autonext_button.set_active(True)  # Default to enabled
        self.autonext_button.connect('toggled', self._on_autonext_toggled)
        controls_box.append(self.autonext_button)

        # Volume control
        volume_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        volume_box.set_halign(Gtk.Align.END)
        
        volume_icon = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        volume_box.append(volume_icon)
        
        self.volume_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.01
        )
        self.volume_scale.set_value(1.0)
        self.volume_scale.set_draw_value(False)
        # Slightly larger for touch
        self.volume_scale.set_size_request(140, 36)
        self.volume_scale.connect('value-changed', self._on_volume_changed)
        volume_box.append(self.volume_scale)
        
        controls_box.append(volume_box)
        
        self.append(controls_box)
        
        self._user_interacting = False  # Track if user is actively interacting with slider
        self._duration = 0.0
        self._updating_volume = False  # Flag to prevent feedback loop
        self._updating_progress = False  # Flag to prevent feedback loop when programmatically updating
        self._seek_timeout_id = None  # Timeout ID for debounced seek during drag
    
    def set_playing(self, playing: bool):
        """Update button states based on playing status."""
        self.play_button.set_visible(not playing)
        self.pause_button.set_visible(playing)
    
    def update_progress(self, position: float, duration: float):
        """Update progress bar and time labels (programmatic update from playback position)."""
        # Don't update if user is actively interacting with the slider
        if self._user_interacting:
            # Only update duration if it changed
            if duration != self._duration:
                self._duration = duration
                self.duration_label.set_text(self._format_time(duration))
            return
        
        # Validate inputs
        position = max(0.0, position)
        duration = max(0.0, duration)
        
        # Clamp position to duration if known
        if duration > 0:
            position = min(position, duration)
        
        self._duration = duration
        
        # Update slider programmatically (set flag to prevent value-changed from triggering seek)
        if duration > 0:
            # Calculate progress percentage, allowing up to 100% to reach the end
            # Use a small epsilon to handle floating point precision issues
            # If position is very close to duration (within 0.1 seconds), treat as 100%
            if position >= duration - 0.1:
                progress = 100.0
            else:
                progress = (position / duration) * 100.0
            # Clamp to valid range
            progress = max(0.0, min(100.0, progress))
        else:
            progress = 0.0
        
        # Set flag to prevent value-changed handler from treating this as user interaction
        self._updating_progress = True
        self.progress_scale.set_value(progress)
        self._updating_progress = False
        
        # Update time labels
        self.time_label.set_text(self._format_time(position))
        self.duration_label.set_text(self._format_time(duration))
        
        # Update time remaining label
        if duration > 0:
            remaining = max(0.0, duration - position)
            self.time_remaining_label.set_text(f"-{self._format_time(remaining)}")
        else:
            self.time_remaining_label.set_text("-00:00")
    
    def set_volume(self, volume: float):
        """Set volume slider value (programmatically, without triggering signal)."""
        self._updating_volume = True
        self.volume_scale.set_value(volume)
        self._updating_volume = False
    
    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to MM:SS."""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def _on_progress_pressed(self, gesture, n_press, x, y):
        """Handle button press on progress bar - user is starting to interact."""
        # Cancel any pending seek timeout
        if self._seek_timeout_id:
            GLib.source_remove(self._seek_timeout_id)
            self._seek_timeout_id = None
        
        # Mark that user is interacting - this prevents update_progress() from interfering
        self._user_interacting = True
    
    def _on_progress_released(self, gesture, n_press, x, y):
        """Handle button release - update UI immediately, then seek."""
        # Cancel any pending seek timeout
        if self._seek_timeout_id:
            GLib.source_remove(self._seek_timeout_id)
            self._seek_timeout_id = None
        
        # Calculate position from current slider value
        if self._duration > 0:
            value = self.progress_scale.get_value()
            value = max(0.0, min(100.0, value))
            if value >= 99.9999:
                position = self._duration
            else:
                position = (value / 100.0) * self._duration
            position = max(0.0, min(self._duration, position))
            
            # Update UI immediately (scale is already at correct position, just update labels)
            self._user_interacting = False
            self.time_label.set_text(self._format_time(position))
            remaining = max(0.0, self._duration - position)
            self.time_remaining_label.set_text(f"-{self._format_time(remaining)}")
            
            # Emit seek signal to actually perform the seek (UI already updated)
            self.emit('seek-changed', position)
    
    def _on_progress_value_changed(self, scale):
        """Handle progress bar value change - update labels during user interaction."""
        # Only update labels if this is a user interaction (not programmatic update)
        if self._user_interacting and not self._updating_progress and self._duration > 0:
            value = scale.get_value()
            # Calculate position from slider value
            if value >= 99.9999:
                position = self._duration
            else:
                position = (value / 100.0) * self._duration
            
            # Update time labels immediately during user interaction for real-time feedback
            self.time_label.set_text(self._format_time(position))
            remaining = max(0.0, self._duration - position)
            self.time_remaining_label.set_text(f"-{self._format_time(remaining)}")
            
            # Schedule a debounced seek (only applies if user stops dragging)
            # This provides immediate feedback while dragging, and seeks when user pauses
            if self._seek_timeout_id:
                GLib.source_remove(self._seek_timeout_id)
            # Wait 150ms after last value change before seeking (debounce)
            self._seek_timeout_id = GLib.timeout_add(150, self._on_seek_timeout)
        
        # Note: When not user interaction, time labels are updated by update_progress()
    
    def _on_seek_timeout(self):
        """Handle seek timeout - apply seek after user stops dragging."""
        self._seek_timeout_id = None
        # Only seek if user is still interacting (they paused dragging)
        if self._user_interacting and self._duration > 0:
            value = self.progress_scale.get_value()
            value = max(0.0, min(100.0, value))
            if value >= 99.9999:
                position = self._duration
            else:
                position = (value / 100.0) * self._duration
            position = max(0.0, min(self._duration, position))
            # Emit seek signal
            self.emit('seek-changed', position)
        return False  # Don't repeat
    
    def _on_volume_changed(self, scale):
        """Handle volume slider change."""
        # Only emit signal if this is a user interaction, not programmatic update
        if not self._updating_volume:
            volume = scale.get_value()
            self.emit('volume-changed', volume)

    def _on_shuffle_toggled(self, button):
        """Handle shuffle toggle button."""
        active = button.get_active()
        self.emit('shuffle-toggled', active)
    
    def _on_autonext_toggled(self, button):
        """Handle autonext toggle button."""
        active = button.get_active()
        self.emit('autonext-toggled', active)

