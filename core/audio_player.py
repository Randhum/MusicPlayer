"""GStreamer-based audio player with ALSA output."""

import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from typing import Optional, Callable
from core.metadata import TrackMetadata


class AudioPlayer:
    """GStreamer-based audio player using ALSA for output."""
    
    def __init__(self):
        # Initialize GStreamer if not already done
        if not Gst.is_initialized():
            Gst.init(None)
        
        self.playbin: Optional[Gst.Element] = None
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
        """Set up the GStreamer pipeline using playbin with ALSA sink."""
        # Use playbin which handles decoding automatically
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if not self.playbin:
            raise RuntimeError("Failed to create GStreamer playbin. Install gst-plugins-base")
        
        # Check for FLAC decoder support
        # Try different possible FLAC decoder names
        flac_available = False
        for decoder_name in ["flacdec", "flac", "flacparse"]:
            decoder = Gst.ElementFactory.make(decoder_name, decoder_name)
            if decoder:
                flac_available = True
                break
        
        if not flac_available:
            print("Warning: FLAC decoder not found.")
            print("To enable FLAC playback, install:")
            print("  emerge -av media-libs/gst-plugins-good")
            print("  (Make sure the 'flac' USE flag is enabled)")
        else:
            print("FLAC decoder available")
        
        # Create ALSA sink for direct ALSA output
        alsasink = Gst.ElementFactory.make("alsasink", "alsasink")
        if alsasink:
            # Use default ALSA device
            alsasink.set_property("device", "default")
            self.playbin.set_property("audio-sink", alsasink)
        else:
            print("Warning: alsasink not available, using autoaudiosink")
            # Fallback to autoaudiosink
            autoaudiosink = Gst.ElementFactory.make("autoaudiosink", "autoaudiosink")
            if autoaudiosink:
                self.playbin.set_property("audio-sink", autoaudiosink)
        
        # Set initial volume
        self.playbin.set_property("volume", self.volume)
    
    def _setup_bus(self):
        """Set up message bus for pipeline events."""
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
    
    def _on_message(self, bus, message):
        """Handle messages from the pipeline."""
        if message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            error_msg = err.message
            print(f"GStreamer error: {error_msg}")
            if debug:
                print(f"Debug info: {debug}")
            
            # Check for missing codec/plugin errors
            if "flac" in error_msg.lower() or ("no decoder" in error_msg.lower() and self.current_track and self.current_track.file_path.endswith('.flac')):
                print("\nERROR: FLAC decoder not available!")
                print("Install FLAC support with:")
                print("  emerge -av media-libs/gst-plugins-good")
                print("  (Make sure the 'flac' USE flag is enabled)")
                print("  You can check USE flags with: emerge -pv media-libs/gst-plugins-good")
            elif "could not link" in error_msg.lower() or "no element" in error_msg.lower():
                print("\nERROR: Missing GStreamer plugin!")
                print("You may need to install additional GStreamer plugins.")
                print("Try: emerge -av media-libs/gst-plugins-good media-libs/gst-plugins-bad")
            
            self._stop()
        elif message.type == Gst.MessageType.EOS:
            # End of stream
            self.is_playing = False
            if self.on_state_changed:
                self.on_state_changed(False)
            if self.on_track_finished:
                self.on_track_finished()
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.playbin:
                old_state, new_state, pending_state = message.parse_state_changed()
                if new_state == Gst.State.PLAYING:
                    self.is_playing = True
                    # Update duration when playback starts
                    GLib.timeout_add(100, self._update_duration)
                elif new_state == Gst.State.PAUSED:
                    self.is_playing = False
                elif new_state == Gst.State.NULL:
                    self.is_playing = False
                
                if self.on_state_changed:
                    self.on_state_changed(self.is_playing)
        elif message.type == Gst.MessageType.DURATION_CHANGED:
            self._update_duration()
        
        return True
    
    def _update_duration(self):
        """Update the duration of the current track."""
        if self.playbin:
            success, duration = self.playbin.query_duration(Gst.Format.TIME)
            if success and duration > 0:
                self.duration = duration / Gst.SECOND
        return False  # Don't repeat the timeout
    
    def _update_position(self):
        """Update the current playback position."""
        if self.playbin and self.is_playing:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
                if self.on_position_changed:
                    self.on_position_changed(self.position, self.duration)
            return True  # Continue timeout
        return False  # Stop timeout
    
    def load_track(self, track: TrackMetadata):
        """Load a track for playback."""
        if not track or not track.file_path:
            return False
        
        # Check file extension to provide helpful error messages
        file_ext = os.path.splitext(track.file_path)[1].lower()
        if file_ext == '.flac':
            # Verify FLAC decoder is available (playbin will handle it, but check anyway)
            flac_available = False
            for decoder_name in ["flacdec", "flac", "flacparse"]:
                decoder = Gst.ElementFactory.make(decoder_name, decoder_name)
                if decoder:
                    flac_available = True
                    break
            
            if not flac_available:
                print("WARNING: FLAC decoder may not be available.")
                print("If playback fails, install FLAC support:")
                print("  emerge -av media-libs/gst-plugins-good")
                print("  (Ensure 'flac' USE flag is enabled)")
                # Don't return False here - let playbin try anyway
                # It might work with other decoders or plugins
        
        self._stop()
        self.current_track = track
        
        # Convert file path to URI for playbin
        file_uri = "file://" + os.path.abspath(track.file_path)
        self.playbin.set_property("uri", file_uri)
        
        # Update duration from track metadata if available
        if track.duration:
            self.duration = track.duration
        
        return True
    
    def play(self):
        """Start or resume playback."""
        if not self.playbin:
            return False
        
        if not self.current_track:
            return False
        
        self.playbin.set_state(Gst.State.PLAYING)
        
        # Start position updates
        GLib.timeout_add(500, self._update_position)
        
        return True
    
    def pause(self):
        """Pause playback."""
        if self.playbin:
            self.playbin.set_state(Gst.State.PAUSED)
            self.is_playing = False
    
    def stop(self):
        """Stop playback."""
        self._stop()
    
    def _stop(self):
        """Internal stop method."""
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
        self.position = 0.0
        self.is_playing = False
    
    def seek(self, position: float):
        """Seek to a specific position in seconds."""
        if self.playbin and self.duration > 0:
            position_ns = int(position * Gst.SECOND)
            self.playbin.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                position_ns
            )
            self.position = position
    
    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, volume))
        if self.playbin:
            self.playbin.set_property("volume", self.volume)
    
    def get_volume(self) -> float:
        """Get current volume."""
        return self.volume
    
    def get_position(self) -> float:
        """Get current playback position in seconds."""
        if self.playbin and self.is_playing:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
        return self.position
    
    def get_duration(self) -> float:
        """Get track duration in seconds."""
        if self.current_track and self.current_track.duration:
            return self.current_track.duration
        return self.duration
    
    def cleanup(self):
        """Clean up resources."""
        self._stop()
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
            self.playbin = None
