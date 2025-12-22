"""Player controls component - play/pause/next/prev/volume/progress."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GObject
from typing import Optional, Callable


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
            Gtk.Orientation.HORIZONTAL, 0.0, 100.0, 1.0
        )
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        # Touch-friendly height
        self.progress_scale.set_size_request(-1, 30)
        
        # Use GTK4 gesture controllers for button events
        gesture_press = Gtk.GestureClick()
        gesture_press.connect('pressed', self._on_progress_press)
        self.progress_scale.add_controller(gesture_press)
        
        gesture_release = Gtk.GestureClick()
        gesture_release.connect('released', self._on_progress_release)
        self.progress_scale.add_controller(gesture_release)
        
        # Connect value-changed for seeking
        self.progress_scale.connect('value-changed', self._on_progress_changed)
        progress_box.append(self.progress_scale)
        
        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.set_size_request(50, -1)
        progress_box.append(self.duration_label)
        
        self.append(progress_box)
        
        # Control buttons
        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls_box.set_halign(Gtk.Align.CENTER)
        
        # Touch-friendly button sizes
        button_size = 48  # Larger buttons for touch
        
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
        self.volume_scale.set_size_request(120, 30)  # Larger for touch
        self.volume_scale.connect('value-changed', self._on_volume_changed)
        volume_box.append(self.volume_scale)
        
        controls_box.append(volume_box)
        
        self.append(controls_box)
        
        self._seeking = False
        self._duration = 0.0
    
    def set_playing(self, playing: bool):
        """Update button states based on playing status."""
        self.play_button.set_visible(not playing)
        self.pause_button.set_visible(playing)
    
    def update_progress(self, position: float, duration: float):
        """Update progress bar and time labels."""
        self._duration = duration
        if not self._seeking and duration > 0:
            progress = (position / duration) * 100.0 if duration > 0 else 0.0
            self.progress_scale.set_value(progress)
        
        self.time_label.set_text(self._format_time(position))
        self.duration_label.set_text(self._format_time(duration))
    
    def set_volume(self, volume: float):
        """Set volume slider value."""
        self.volume_scale.set_value(volume)
    
    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to MM:SS."""
        if seconds < 0:
            seconds = 0
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"
    
    def _on_progress_changed(self, scale):
        """Handle progress bar value change."""
        if self._seeking and self._duration > 0:
            value = scale.get_value()
            position = (value / 100.0) * self._duration
            self.emit('seek-changed', position)
    
    def _on_progress_press(self, gesture, n_press, x, y):
        """Handle progress bar press (GTK4 gesture)."""
        self._seeking = True
    
    def _on_progress_release(self, gesture, n_press, x, y):
        """Handle progress bar release (GTK4 gesture)."""
        self._seeking = False
    
    def _on_volume_changed(self, scale):
        """Handle volume slider change."""
        volume = scale.get_value()
        self.emit('volume-changed', volume)

