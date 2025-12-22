"""Audio decoder for converting audio files to PCM format using ffmpeg."""

import subprocess
import os
from typing import Optional, Tuple
from pathlib import Path


class AudioDecoder:
    """Decodes audio files to PCM format for ALSA playback using ffmpeg."""
    
    def __init__(self):
        # Check for ffmpeg
        self.ffmpeg_path = self._find_ffmpeg()
        if not self.ffmpeg_path:
            raise RuntimeError("ffmpeg is not installed. Install with: emerge -av media-video/ffmpeg")
    
    def _find_ffmpeg(self) -> Optional[str]:
        """Find ffmpeg executable."""
        # Try common locations
        for path in ['ffmpeg', '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg']:
            try:
                result = subprocess.run([path, '-version'], 
                                      capture_output=True, 
                                      timeout=2)
                if result.returncode == 0:
                    return path
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None
    
    def decode_file(self, file_path: str, sample_rate: int = 44100, channels: int = 2) -> Optional[bytes]:
        """
        Decode an audio file to PCM format using ffmpeg.
        
        Args:
            file_path: Path to the audio file
            sample_rate: Target sample rate (default 44100 Hz)
            channels: Number of channels (1=mono, 2=stereo, default 2)
        
        Returns:
            PCM audio data as bytes (16-bit signed little-endian), or None on error
        """
        try:
            # Build ffmpeg command
            # -i: input file
            # -f s16le: 16-bit signed little-endian PCM format
            # -ar: sample rate
            # -ac: number of channels
            # -: output to stdout
            cmd = [
                self.ffmpeg_path,
                '-i', file_path,
                '-f', 's16le',  # 16-bit signed little-endian PCM
                '-ar', str(sample_rate),
                '-ac', str(channels),
                '-'  # Output to stdout
            ]
            
            # Run ffmpeg and capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5 minute timeout
                check=False
            )
            
            if result.returncode != 0:
                # ffmpeg writes errors to stderr, but also outputs data to stdout
                # Check if we got any output
                if not result.stdout:
                    error_msg = result.stderr.decode('utf-8', errors='ignore') if result.stderr else "Unknown error"
                    print(f"ffmpeg error for {file_path}: {error_msg}")
                    return None
            
            return result.stdout
            
        except subprocess.TimeoutExpired:
            print(f"Timeout decoding audio file: {file_path}")
            return None
        except Exception as e:
            print(f"Error decoding audio file {file_path}: {e}")
            return None
    
    def get_audio_info(self, file_path: str) -> Optional[Tuple[int, int, float]]:
        """
        Get audio file information using ffprobe.
        
        Args:
            file_path: Path to the audio file
        
        Returns:
            Tuple of (sample_rate, channels, duration_seconds) or None on error
        """
        try:
            # Try to find ffprobe
            ffprobe_path = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
            if not os.path.exists(ffprobe_path):
                # Fallback: use ffmpeg to get info
                return self._get_info_via_ffmpeg(file_path)
            
            # Use ffprobe to get audio info
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-show_entries', 'stream=sample_rate,channels,duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 3:
                    sample_rate = int(float(lines[0]))
                    channels = int(float(lines[1]))
                    duration = float(lines[2])
                    return (sample_rate, channels, duration)
            
            # Fallback to ffmpeg method
            return self._get_info_via_ffmpeg(file_path)
            
        except Exception as e:
            print(f"Error getting audio info for {file_path}: {e}")
            return self._get_info_via_ffmpeg(file_path)
    
    def _get_info_via_ffmpeg(self, file_path: str) -> Optional[Tuple[int, int, float]]:
        """Get audio info using ffmpeg (fallback method)."""
        try:
            cmd = [
                self.ffmpeg_path,
                '-i', file_path,
                '-f', 'null',
                '-'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            # Parse ffmpeg output for stream info
            # ffmpeg outputs info to stderr
            if result.stderr:
                lines = result.stderr.split('\n')
                for line in lines:
                    if 'Audio:' in line or 'Stream' in line:
                        # Try to extract sample rate and channels
                        # Format: Audio: pcm_s16le, 44100 Hz, stereo, s16, 1411 kb/s
                        parts = line.split(',')
                        sample_rate = 44100  # default
                        channels = 2  # default
                        
                        for part in parts:
                            part = part.strip()
                            if 'Hz' in part:
                                try:
                                    sample_rate = int(part.split()[0])
                                except:
                                    pass
                            if 'mono' in part.lower():
                                channels = 1
                            elif 'stereo' in part.lower():
                                channels = 2
                        
                        # Get duration from metadata if available
                        duration = 0.0
                        for line2 in lines:
                            if 'Duration:' in line2:
                                # Parse duration like "Duration: 00:03:45.67"
                                try:
                                    dur_str = line2.split('Duration:')[1].split(',')[0].strip()
                                    parts = dur_str.split(':')
                                    if len(parts) == 3:
                                        hours, minutes, seconds = map(float, parts)
                                        duration = hours * 3600 + minutes * 60 + seconds
                                except:
                                    pass
                        
                        return (sample_rate, channels, duration)
            
            # Default values if parsing fails
            return (44100, 2, 0.0)
            
        except Exception as e:
            print(f"Error getting audio info via ffmpeg: {e}")
            return None
    
    def decode_to_pcm(self, file_path: str) -> Optional[Tuple[bytes, int, int]]:
        """
        Decode file to PCM with automatic format detection.
        
        Returns:
            Tuple of (pcm_data, sample_rate, channels) or None on error
        """
        try:
            # Get original audio info
            info = self.get_audio_info(file_path)
            if not info:
                # Try with default values
                sample_rate = 44100
                channels = 2
            else:
                sample_rate, channels, _ = info
            
            # Decode to standard format (44100 Hz, stereo)
            pcm_data = self.decode_file(file_path, sample_rate=44100, channels=2)
            
            if pcm_data:
                return (pcm_data, 44100, 2)
            return None
            
        except Exception as e:
            print(f"Error in decode_to_pcm for {file_path}: {e}")
            return None
