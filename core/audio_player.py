"""GStreamer-based media player with automatic audio/video handling."""

import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from typing import Optional, Callable
from core.metadata import TrackMetadata


# Video container extensions - these get video+audio playback
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.wmv', '.m4v'}


class AudioPlayer:
    """GStreamer-based media player using playbin for automatic format handling."""
    
    def __init__(self):
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
        self.on_track_loaded: Optional[Callable] = None
        
        self._setup_pipeline()
    
    def _setup_pipeline(self):
        """Set up the GStreamer playbin pipeline."""
        self.playbin = Gst.ElementFactory.make("playbin", "playbin")
        if not self.playbin:
            raise RuntimeError("Failed to create GStreamer playbin")
        
        # Use autoaudiosink - handles all audio formats automatically
        audio_sink = Gst.ElementFactory.make("autoaudiosink", "audiosink")
        if audio_sink:
            self.playbin.set_property("audio-sink", audio_sink)
        
        # Use autovideosink for video output
        video_sink = Gst.ElementFactory.make("autovideosink", "videosink")
        if video_sink:
            self.playbin.set_property("video-sink", video_sink)
        
        # Set initial volume
        self.playbin.set_property("volume", self.volume)
        
        # Set up message bus
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
    
    def _is_video_file(self, file_path: str) -> bool:
        """Check if file is a video container based on extension."""
        return os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS
    
    def _on_message(self, bus, message):
        """Handle GStreamer bus messages."""
        msg_type = message.type
        
        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Playback error: {err.message}")
            if debug:
                print(f"Debug: {debug}")
            self._print_codec_help(err.message, debug or "")
            self._stop()
            
        elif msg_type == Gst.MessageType.EOS:
            self.is_playing = False
            if self.on_state_changed:
                self.on_state_changed(False)
            if self.on_track_finished:
                self.on_track_finished()
                
        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.playbin:
                _, new_state, _ = message.parse_state_changed()
                
                if new_state == Gst.State.PLAYING:
                    self.is_playing = True
                    GLib.timeout_add(100, self._update_duration)
                elif new_state in (Gst.State.PAUSED, Gst.State.NULL):
                    self.is_playing = False
                
                if self.on_state_changed:
                    self.on_state_changed(self.is_playing)
                    
        elif msg_type == Gst.MessageType.DURATION_CHANGED:
            self._update_duration()
        
        return True
    
    def _print_codec_help(self, error: str, debug: str):
        """Print helpful messages for missing codecs."""
        combined = (error + debug).lower()
        
        if 'flac' in combined:
            print("Missing FLAC support: emerge -av media-plugins/gst-plugins-flac")
        elif 'h264' in combined or 'avc' in combined:
            print("Missing H.264 support: emerge -av media-plugins/gst-plugins-openh264")
        elif 'missing' in combined or 'decoder' in combined:
            print("Missing codec: emerge -av media-libs/gst-plugins-good media-libs/gst-plugins-bad")
    
    def _update_duration(self) -> bool:
        """Update track duration."""
        if self.playbin:
            success, duration = self.playbin.query_duration(Gst.Format.TIME)
            if success and duration > 0:
                self.duration = duration / Gst.SECOND
        return False
    
    def _update_position(self) -> bool:
        """Update playback position (called periodically)."""
        if self.playbin and self.is_playing:
            success, position = self.playbin.query_position(Gst.Format.TIME)
            if success:
                self.position = position / Gst.SECOND
                if self.on_position_changed:
                    self.on_position_changed(self.position, self.duration)
            return True
        return False
    
    def load_track(self, track: TrackMetadata) -> bool:
        """Load a track for playback."""
        if not track or not track.file_path:
            return False
        
        if not os.path.exists(track.file_path):
            print(f"File not found: {track.file_path}")
            return False
        
        # Stop current playback
        self._stop()
        
        # Configure video flag based on file type
        # GStreamer playbin flags: VIDEO=0x01, AUDIO=0x02, TEXT=0x04, SOFT_VOLUME=0x10
        is_video = self._is_video_file(track.file_path)
        try:
            if is_video:
                # Video + Audio + Soft Volume
                self.playbin.set_property("flags", 0x01 | 0x02 | 0x10)
            else:
                # Audio + Soft Volume (no video)
                self.playbin.set_property("flags", 0x02 | 0x10)
        except Exception:
            pass
        
        self.current_track = track
        
        # Set URI
        file_uri = "file://" + os.path.abspath(track.file_path)
        self.playbin.set_property("uri", file_uri)
        
        # Use track duration if available
        if track.duration:
            self.duration = track.duration
        
        # Prepare playback
        ret = self.playbin.set_state(Gst.State.PAUSED)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Failed to load track")
            return False
        
        if self.on_track_loaded:
            self.on_track_loaded()
        
        return True
    
    def play(self) -> bool:
        """Start or resume playback."""
        if not self.playbin or not self.current_track:
            return False
        
        ret = self.playbin.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("Failed to start playback")
            return False
        
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
        """Internal stop."""
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
        self.position = 0.0
        self.is_playing = False
    
    def seek(self, position: float):
        """Seek to position in seconds."""
        if self.playbin and self.duration > 0:
            self.playbin.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                int(position * Gst.SECOND)
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
        """Get current position in seconds."""
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
