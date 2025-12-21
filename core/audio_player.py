"""GStreamer-based audio player."""

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from typing import Optional, Callable
from core.metadata import TrackMetadata


class AudioPlayer:
    """GStreamer-based audio player."""
    
    def __init__(self):
        # GStreamer should be initialized in main() before creating the app
        # Only initialize if not already done
        if not Gst.is_initialized():
            Gst.init(None)
        self.pipeline: Optional[Gst.Pipeline] = None
        self.current_track: Optional[TrackMetadata] = None
        self.volume: float = 1.0
        self.position: float = 0.0
        self.duration: float = 0.0
        self.is_playing: bool = False
        
        # Callbacks
        self.on_state_changed: Optional[Callable] = None
        self.on_position_changed: Optional[Callable] = None
        self.on_track_finished: Optional[Callable] = None
        
        self._setup_pipeline()
        self._setup_bus()
    
    def _setup_pipeline(self):
        """Set up the GStreamer pipeline."""
        self.pipeline = Gst.Pipeline.new("player")
        
        # Create elements
        filesrc = Gst.ElementFactory.make("filesrc", "filesrc")
        decodebin = Gst.ElementFactory.make("decodebin", "decodebin")
        audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert")
        audioresample = Gst.ElementFactory.make("audioresample", "audioresample")
        volume_elem = Gst.ElementFactory.make("volume", "volume")
        autoaudiosink = Gst.ElementFactory.make("autoaudiosink", "autoaudiosink")
        
        if not all([filesrc, decodebin, audioconvert, audioresample, volume_elem, autoaudiosink]):
            raise RuntimeError("Failed to create GStreamer elements")
        
        # Add elements to pipeline
        self.pipeline.add(filesrc)
        self.pipeline.add(decodebin)
        self.pipeline.add(audioconvert)
        self.pipeline.add(audioresample)
        self.pipeline.add(volume_elem)
        self.pipeline.add(autoaudiosink)
        
        # Link static elements
        filesrc.link(decodebin)
        audioconvert.link(audioresample)
        audioresample.link(volume_elem)
        volume_elem.link(autoaudiosink)
        
        # Handle decodebin pad-added signal
        decodebin.connect("pad-added", self._on_pad_added, audioconvert)
        
        # Set initial volume
        volume_elem.set_property("volume", self.volume)
    
    def _on_pad_added(self, decodebin, pad, audioconvert):
        """Handle pad-added signal from decodebin."""
        sink_pad = audioconvert.get_static_pad("sink")
        if pad.is_linked():
            return
        
        pad.link(sink_pad)
    
    def _setup_bus(self):
        """Set up message bus for pipeline events."""
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
    
    def _on_message(self, bus, message):
        """Handle messages from the pipeline."""
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer error: {err.message}")
            if debug:
                print(f"Debug info: {debug}")
            self._stop()
        elif message.type == Gst.MessageType.EOS:
            # End of stream
            if self.on_track_finished:
                self.on_track_finished()
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old_state, new_state, pending_state = message.parse_state_changed()
                if new_state == Gst.State.PLAYING:
                    self.is_playing = True
                elif new_state == Gst.State.PAUSED:
                    self.is_playing = False
                elif new_state == Gst.State.NULL:
                    self.is_playing = False
                
                if self.on_state_changed:
                    self.on_state_changed(self.is_playing)
        
        # Update position periodically
        if message.type == Gst.MessageType.STREAM_START:
            self._update_duration()
        
        return True
    
    def _update_duration(self):
        """Update the duration of the current track."""
        if self.pipeline:
            success, duration = self.pipeline.query_duration(Gst.Format.TIME)
            if success:
                self.duration = duration / Gst.SECOND
    
    def _update_position(self):
        """Update the current playback position."""
        if self.pipeline and self.is_playing:
            success, position = self.pipeline.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
                if self.on_position_changed:
                    self.on_position_changed(self.position, self.duration)
        
        # Schedule next update
        if self.is_playing:
            GLib.timeout_add(500, self._update_position)
        
        return False
    
    def load_track(self, track: TrackMetadata):
        """Load a track for playback."""
        if not track or not track.file_path:
            return False
        
        self._stop()
        self.current_track = track
        
        # Set file source location
        filesrc = self.pipeline.get_by_name("filesrc")
        if filesrc:
            filesrc.set_property("location", track.file_path)
            return True
        
        return False
    
    def play(self):
        """Start or resume playback."""
        if not self.pipeline:
            return False
        
        if not self.current_track:
            return False
        
        # If pipeline is in NULL state, set it to READY first
        ret, state, pending = self.pipeline.get_state(0)
        if state == Gst.State.NULL:
            self.pipeline.set_state(Gst.State.READY)
        
        self.pipeline.set_state(Gst.State.PLAYING)
        self._update_position()
        return True
    
    def pause(self):
        """Pause playback."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)
    
    def stop(self):
        """Stop playback."""
        self._stop()
    
    def _stop(self):
        """Internal stop method."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        self.position = 0.0
        self.is_playing = False
    
    def seek(self, position: float):
        """Seek to a specific position in seconds."""
        if self.pipeline and self.duration > 0:
            position_ns = int(position * Gst.SECOND)
            self.pipeline.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                position_ns
            )
    
    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, volume))
        volume_elem = self.pipeline.get_by_name("volume")
        if volume_elem:
            volume_elem.set_property("volume", self.volume)
    
    def get_volume(self) -> float:
        """Get current volume."""
        return self.volume
    
    def get_position(self) -> float:
        """Get current playback position in seconds."""
        return self.position
    
    def get_duration(self) -> float:
        """Get track duration in seconds."""
        return self.duration
    
    def cleanup(self):
        """Clean up resources."""
        self._stop()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

