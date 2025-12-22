"""GStreamer-based audio player with ALSA output and professional audio quality."""

import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from typing import Optional, Callable
from core.metadata import TrackMetadata


class AudioPlayer:
    """GStreamer-based audio player using ALSA for output with high-quality audio processing.
    
    Supports professional audio quality:
    - 24-bit PCM (S24LE format)
    - 44.1 kHz sample rate
    - Stereo (2 channels)
    - FLAC bitstream decoding
    """
    
    # Professional audio quality settings
    SAMPLE_RATE = 44100  # 44.1 kHz - CD quality
    CHANNELS = 2  # Stereo
    BIT_DEPTH = 24  # 24-bit audio
    
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
        self.is_loading: bool = False  # Track loading state
        
        # Callbacks
        self.on_state_changed: Optional[Callable] = None
        self.on_position_changed: Optional[Callable] = None
        self.on_track_finished: Optional[Callable] = None
        self.on_track_loaded: Optional[Callable] = None  # Called when track is ready
        
        self._setup_pipeline()
        self._setup_bus()
    
    def _setup_pipeline(self):
        """Set up the GStreamer pipeline using playbin with high-quality audio processing."""
        # Use playbin which handles decoding automatically
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if not self.playbin:
            raise RuntimeError("Failed to create GStreamer playbin. Install gst-plugins-base")
        
        # Check for FLAC decoder support
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
        
        # Create high-quality audio processing pipeline
        # audioconvert: converts between audio formats
        # audioresample: resamples to target sample rate
        # capsfilter: ensures 24-bit, 44.1 kHz, stereo output
        # alsasink: direct ALSA output
        
        audioconvert = Gst.ElementFactory.make("audioconvert", "audioconvert")
        audioresample = Gst.ElementFactory.make("audioresample", "audioresample")
        capsfilter = Gst.ElementFactory.make("capsfilter", "capsfilter")
        alsasink = Gst.ElementFactory.make("alsasink", "alsasink")
        
        if not all([audioconvert, audioresample, capsfilter]):
            print("Warning: Some audio processing elements not available, using basic sink")
            if alsasink:
                alsasink.set_property("device", "default")
                self.playbin.set_property("audio-sink", alsasink)
            else:
                autoaudiosink = Gst.ElementFactory.make("autoaudiosink", "autoaudiosink")
                if autoaudiosink:
                    self.playbin.set_property("audio-sink", autoaudiosink)
        else:
            # Create audio processing bin
            audio_bin = Gst.Bin.new("audio-bin")
            
            # Configure caps for professional audio quality
            # S24LE = 24-bit signed little-endian PCM
            caps = Gst.Caps.from_string(
                f"audio/x-raw,format=S24LE,rate={self.SAMPLE_RATE},channels={self.CHANNELS},layout=interleaved"
            )
            capsfilter.set_property("caps", caps)
            
            # Configure ALSA sink
            if alsasink:
                alsasink.set_property("device", "default")
                # Enable sync for smooth playback
                alsasink.set_property("sync", True)
            else:
                print("Warning: alsasink not available, using autoaudiosink")
                alsasink = Gst.ElementFactory.make("autoaudiosink", "autoaudiosink")
                if not alsasink:
                    raise RuntimeError("No audio sink available")
            
            # Add elements to bin
            audio_bin.add(audioconvert)
            audio_bin.add(audioresample)
            audio_bin.add(capsfilter)
            audio_bin.add(alsasink)
            
            # Link elements: audioconvert ! audioresample ! capsfilter ! alsasink
            audioconvert.link(audioresample)
            audioresample.link(capsfilter)
            capsfilter.link(alsasink)
            
            # Create ghost pads for the bin
            pad = audioconvert.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("sink", pad)
            audio_bin.add_pad(ghost_pad)
            
            # Set the audio bin as the audio sink for playbin
            self.playbin.set_property("audio-sink", audio_bin)
            
            print(f"Audio pipeline configured for {self.BIT_DEPTH}-bit, {self.SAMPLE_RATE} Hz, {self.CHANNELS}-channel stereo")
        
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
            
            self.is_loading = False
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
                
                # Track is ready when it reaches PAUSED state (loaded but not playing)
                if new_state == Gst.State.PAUSED and self.is_loading:
                    self.is_loading = False
                    if self.on_track_loaded:
                        self.on_track_loaded()
                
                if new_state == Gst.State.PLAYING:
                    self.is_playing = True
                    self.is_loading = False
                    # Update duration when playback starts
                    GLib.timeout_add(100, self._update_duration)
                elif new_state == Gst.State.PAUSED:
                    self.is_playing = False
                elif new_state == Gst.State.NULL:
                    self.is_playing = False
                    self.is_loading = False
                
                if self.on_state_changed:
                    self.on_state_changed(self.is_playing)
        elif message.type == Gst.MessageType.ASYNC_DONE:
            # Pipeline is ready
            if self.is_loading:
                self.is_loading = False
                if self.on_track_loaded:
                    self.on_track_loaded()
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
        """Load a track for playback. Returns True if loading started successfully."""
        if not track or not track.file_path:
            return False
        
        if not os.path.exists(track.file_path):
            print(f"Error: File not found: {track.file_path}")
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
        
        # Stop current playback
        self._stop()
        
        # Set loading state
        self.is_loading = True
        self.current_track = track
        
        # Convert file path to URI for playbin
        file_uri = "file://" + os.path.abspath(track.file_path)
        self.playbin.set_property("uri", file_uri)
        
        # Update duration from track metadata if available
        if track.duration:
            self.duration = track.duration
        
        # Set pipeline to READY state to start loading
        # This will trigger async loading of the track
        ret = self.playbin.set_state(Gst.State.READY)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Error: Failed to load track")
            self.is_loading = False
            return False
        
        # Then set to PAUSED to fully load the track
        ret = self.playbin.set_state(Gst.State.PAUSED)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Error: Failed to prepare track")
            self.is_loading = False
            return False
        
        return True
    
    def play(self):
        """Start or resume playback. Waits for track to be ready if still loading."""
        if not self.playbin:
            return False
        
        if not self.current_track:
            return False
        
        # If track is still loading, wait for it to be ready
        if self.is_loading:
            # Wait for pipeline to reach PAUSED state (track loaded)
            ret = self.playbin.get_state(Gst.CLOCK_TIME_NONE)
            if ret[0] == Gst.StateChangeReturn.ASYNC:
                # Still loading, wait a bit more
                GLib.timeout_add(100, self._wait_and_play)
                return True
            elif ret[0] == Gst.StateChangeReturn.FAILURE:
                print("Error: Track failed to load")
                self.is_loading = False
                return False
        
        # Track is ready, start playback
        ret = self.playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Error: Failed to start playback")
            return False
        
        # Start position updates
        GLib.timeout_add(500, self._update_position)
        
        return True
    
    def _wait_and_play(self):
        """Wait for track to load and then play."""
        if not self.playbin or not self.current_track:
            return False
        
        if self.is_loading:
            ret = self.playbin.get_state(Gst.CLOCK_TIME_NONE)
            if ret[0] == Gst.StateChangeReturn.ASYNC:
                # Still loading, wait more
                GLib.timeout_add(100, self._wait_and_play)
                return True
            elif ret[0] == Gst.StateChangeReturn.FAILURE:
                print("Error: Track failed to load")
                self.is_loading = False
                return False
        
        # Track is ready, start playback
        self.is_loading = False
        ret = self.playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Error: Failed to start playback")
            return False
        
        # Start position updates
        GLib.timeout_add(500, self._update_position)
        return False  # Don't repeat
    
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
