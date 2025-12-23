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
            print("  emerge -av media-plugins/gst-plugins-flac")
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
        
        # Set up video sink for video files with proper synchronization
        # Create a video processing bin with sync enabled
        video_bin = Gst.Bin.new("video-bin")
        
        # Try different video sinks in order of preference
        video_sink = None
        video_sink_name = None
        
        # Try autovideosink first (automatically chooses best available)
        video_sink = Gst.ElementFactory.make("autovideosink", "autovideosink")
        if video_sink:
            video_sink_name = "autovideosink"
        else:
            # Fallback to xvimagesink for X11
            video_sink = Gst.ElementFactory.make("xvimagesink", "xvimagesink")
            if video_sink:
                video_sink_name = "xvimagesink"
            else:
                # Fallback to ximagesink
                video_sink = Gst.ElementFactory.make("ximagesink", "ximagesink")
                if video_sink:
                    video_sink_name = "ximagesink"
        
        if video_sink:
            # Enable synchronization for smooth video playback
            video_sink.set_property("sync", True)
            
            # Add to bin
            video_bin.add(video_sink)
            
            # Create ghost pad
            pad = video_sink.get_static_pad("sink")
            if pad:
                ghost_pad = Gst.GhostPad.new("sink", pad)
                video_bin.add_pad(ghost_pad)
            
            # Set video bin as video sink
            self.playbin.set_property("video-sink", video_bin)
            print(f"Video output enabled using {video_sink_name} (will display video if present)")
        else:
            print("Warning: No video sink available, video will not be displayed")
        
        # Ensure both audio and video are enabled by setting playbin flags
        # Flags: AUDIO=1, VIDEO=2, SOFT_VOLUME=8, TEXT=16
        try:
            # Try using PlayFlags enum if available
            flags = Gst.PlayFlags.AUDIO | Gst.PlayFlags.VIDEO | Gst.PlayFlags.SOFT_VOLUME
            self.playbin.set_property("flags", flags)
        except (AttributeError, TypeError):
            # Fallback: use integer values directly
            self.playbin.set_property("flags", 1 | 2 | 8)  # AUDIO | VIDEO | SOFT_VOLUME
        
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
            error_lower = error_msg.lower()
            debug_lower = debug.lower() if debug else ""
            
            # Check for FLAC decoder errors (multiple patterns)
            is_flac_error = (
                "flac" in error_lower or
                ("missing decoder" in debug_lower and "flac" in debug_lower) or
                ("no suitable plugins found" in debug_lower and "flac" in debug_lower) or
                ("no decoder" in error_lower and self.current_track and self.current_track.file_path.lower().endswith('.flac'))
            )
            
            if is_flac_error:
                print("\n" + "="*60)
                print("ERROR: FLAC decoder not available!")
                print("="*60)
                print("To enable FLAC playback, install GStreamer FLAC support:")
                print("  1. Install the FLAC plugin package:")
                print("     emerge -av media-plugins/gst-plugins-flac")
                print("  2. Verify FLAC decoder is available:")
                print("     gst-inspect-1.0 flacdec")
                print("="*60)
            elif "missing decoder" in debug_lower or "no suitable plugins found" in debug_lower:
                print("\n" + "="*60)
                print("ERROR: Missing GStreamer decoder plugin!")
                print("="*60)
                print("The audio format requires a decoder that is not installed.")
                print("Install additional GStreamer plugins:")
                print("  emerge -av media-libs/gst-plugins-good media-libs/gst-plugins-bad")
                print("="*60)
            elif "h264" in error_lower or "openh264" in error_lower or ("missing decoder" in debug_lower and "h264" in debug_lower):
                print("\n" + "="*60)
                print("ERROR: H.264/OpenH264 decoder not available!")
                print("="*60)
                print("To enable H.264 video playback, install:")
                print("  emerge -av media-plugins/gst-plugins-openh264")
                print("Or for broader codec support:")
                print("  emerge -av media-libs/gst-plugins-bad media-libs/gst-plugins-ugly")
                print("="*60)
            elif "could not link" in error_lower or "no element" in error_lower:
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
        
        # Check file extension to provide helpful error messages for common formats
        file_ext = os.path.splitext(track.file_path)[1].lower()
        
        # Format-specific decoder checks and helpful messages
        # Note: playbin handles most formats automatically, but we check for critical ones
        format_checks = {
            '.flac': (['flacdec', 'flac', 'flacparse'], 'media-plugins/gst-plugins-flac'),
        }
        
        if file_ext in format_checks:
            decoder_names, package = format_checks[file_ext]
            decoder_available = False
            for decoder_name in decoder_names:
                decoder = Gst.ElementFactory.make(decoder_name, decoder_name)
                if decoder:
                    decoder_available = True
                    break
            
            if not decoder_available:
                print(f"WARNING: {file_ext.upper()} decoder may not be available.")
                print(f"If playback fails, install support:")
                print(f"  emerge -av {package}")
        
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
