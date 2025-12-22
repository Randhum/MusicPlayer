"""Direct ALSA audio player using pyalsaaudio."""

import threading
import time
from typing import Optional, Callable
try:
    import alsaaudio
    ALSA_AVAILABLE = True
except ImportError:
    ALSA_AVAILABLE = False
    print("Warning: pyalsaaudio not available. Install with: pip install pyalsaaudio")


class ALSAPlayer:
    """Direct ALSA PCM device player."""
    
    def __init__(self, device: str = 'default'):
        if not ALSA_AVAILABLE:
            raise RuntimeError("pyalsaaudio is not installed. Install with: pip install pyalsaaudio")
        
        self.device_name = device
        self.pcm: Optional[alsaaudio.PCM] = None
        self.current_track: Optional[object] = None
        self.volume: float = 1.0
        self.position: float = 0.0
        self.duration: float = 0.0
        self.is_playing: bool = False
        self.is_paused: bool = False
        
        # Playback thread
        self.playback_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Start unpaused
        
        # Audio data
        self.audio_data: Optional[bytes] = None
        self.sample_rate: int = 44100
        self.channels: int = 2
        self.format: int = alsaaudio.PCM_FORMAT_S16_LE
        
        # Callbacks
        self.on_state_changed: Optional[Callable] = None
        self.on_position_changed: Optional[Callable] = None
        self.on_track_finished: Optional[Callable] = None
    
    def _setup_pcm(self):
        """Set up ALSA PCM device."""
        try:
            self.pcm = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK, alsaaudio.PCM_NORMAL, self.device_name)
            self.pcm.setchannels(self.channels)
            self.pcm.setrate(self.sample_rate)
            self.pcm.setformat(self.format)
            self.pcm.setperiodsize(1024)  # Buffer size
        except Exception as e:
            print(f"Error setting up ALSA PCM: {e}")
            raise
    
    def load_audio_data(self, audio_data: bytes, sample_rate: int = 44100, channels: int = 2):
        """Load PCM audio data for playback."""
        self.audio_data = audio_data
        self.sample_rate = sample_rate
        self.channels = channels
        
        # Calculate duration
        if audio_data:
            bytes_per_sample = 2  # 16-bit = 2 bytes
            total_samples = len(audio_data) // (bytes_per_sample * channels)
            self.duration = total_samples / sample_rate
        else:
            self.duration = 0.0
        
        self.position = 0.0
    
    def _playback_worker(self):
        """Worker thread for audio playback."""
        if not self.audio_data or not self.pcm:
            return
        
        try:
            self._setup_pcm()
            
            bytes_per_sample = 2  # 16-bit
            bytes_per_frame = bytes_per_sample * self.channels
            frame_size = 1024 * bytes_per_frame  # Process 1024 frames at a time
            
            offset = 0
            total_length = len(self.audio_data)
            
            while offset < total_length and not self.stop_event.is_set():
                # Check for pause
                self.pause_event.wait()
                
                if self.stop_event.is_set():
                    break
                
                # Get chunk of audio data
                chunk_size = min(frame_size, total_length - offset)
                chunk = self.audio_data[offset:offset + chunk_size]
                
                if not chunk:
                    break
                
                # Write to ALSA
                try:
                    self.pcm.write(chunk)
                except Exception as e:
                    print(f"Error writing to ALSA: {e}")
                    break
                
                # Update position
                offset += chunk_size
                frames_written = chunk_size // bytes_per_frame
                self.position += frames_written / self.sample_rate
                
                # Call position callback
                if self.on_position_changed:
                    self.on_position_changed(self.position, self.duration)
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.01)
            
            # Playback finished
            if not self.stop_event.is_set() and offset >= total_length:
                self.is_playing = False
                if self.on_track_finished:
                    self.on_track_finished()
                if self.on_state_changed:
                    self.on_state_changed(False)
        except Exception as e:
            print(f"Error in playback worker: {e}")
            self.is_playing = False
            if self.on_state_changed:
                self.on_state_changed(False)
        finally:
            if self.pcm:
                self.pcm.close()
                self.pcm = None
    
    def play(self):
        """Start playback."""
        if not self.audio_data:
            return False
        
        if self.is_playing:
            # Already playing, just unpause
            self.pause_event.set()
            self.is_paused = False
            return True
        
        # Start new playback
        self.stop_event.clear()
        self.pause_event.set()
        self.is_playing = True
        self.is_paused = False
        
        if self.on_state_changed:
            self.on_state_changed(True)
        
        # Start playback thread
        self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_thread.start()
        
        return True
    
    def pause(self):
        """Pause playback."""
        if self.is_playing and not self.is_paused:
            self.pause_event.clear()
            self.is_paused = True
            if self.on_state_changed:
                self.on_state_changed(False)
    
    def stop(self):
        """Stop playback."""
        self.stop_event.set()
        self.pause_event.set()  # Unpause to allow thread to exit
        
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=1.0)
        
        self.is_playing = False
        self.is_paused = False
        self.position = 0.0
        
        if self.pcm:
            try:
                self.pcm.close()
            except:
                pass
            self.pcm = None
        
        if self.on_state_changed:
            self.on_state_changed(False)
    
    def seek(self, position: float):
        """Seek to a specific position (not fully implemented - would need to restart playback)."""
        # For simplicity, we'll just stop and restart at new position
        # A full implementation would need to track offset in audio_data
        self.position = max(0.0, min(position, self.duration))
        # Note: Full seek implementation would require restarting playback from new offset
    
    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, volume))
        # ALSA volume control would require mixer access
        # For now, we'll apply volume in the decoder/audio processing
    
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
        self.stop()
        self.audio_data = None

