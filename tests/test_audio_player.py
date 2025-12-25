"""Tests for audio player."""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestAudioPlayer:
    """Test AudioPlayer class."""
    
    @pytest.fixture
    def audio_player(self, mock_config, mock_logger):
        """Create AudioPlayer instance."""
        with patch('core.audio_player.Gst'):
            from core.audio_player import AudioPlayer
            player = AudioPlayer()
            return player
    
    def test_initialization(self, audio_player):
        """Test AudioPlayer initialization."""
        assert audio_player.current_track is None
        assert audio_player.volume == 1.0
        assert audio_player.position == 0.0
        assert audio_player.is_playing is False
    
    def test_is_video_file(self, audio_player):
        """Test video file detection."""
        assert audio_player._is_video_file('test.mp4') is True
        assert audio_player._is_video_file('test.mkv') is True
        assert audio_player._is_video_file('test.mp3') is False
        assert audio_player._is_video_file('test.flac') is False
    
    def test_volume_range(self, audio_player):
        """Test volume clamping."""
        audio_player.set_volume(2.0)
        assert audio_player.get_volume() == 1.0
        
        audio_player.set_volume(-1.0)
        assert audio_player.get_volume() == 0.0
        
        audio_player.set_volume(0.5)
        assert audio_player.get_volume() == 0.5

