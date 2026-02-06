"""Tests for security validators."""

import pytest
from pathlib import Path
from core.security import SecurityValidator


class TestSecurityValidator:
    """Test SecurityValidator class."""
    
    def test_validate_path_valid(self, temp_dir):
        """Test validating a valid path."""
        test_file = temp_dir / 'test.mp3'
        test_file.touch()
        
        result = SecurityValidator.validate_path(str(test_file), base_path=temp_dir)
        assert result == test_file.resolve()
    
    def test_validate_path_traversal(self, temp_dir):
        """Test path traversal detection."""
        malicious_path = str(temp_dir / '../../etc/passwd')
        result = SecurityValidator.validate_path(malicious_path, base_path=temp_dir)
        assert result is None
    
    def test_validate_file_extension(self):
        """Test file extension validation."""
        assert SecurityValidator.validate_file_extension('test.mp3') is True
        assert SecurityValidator.validate_file_extension('test.flac') is True
        assert SecurityValidator.validate_file_extension('test.exe') is False
        assert SecurityValidator.validate_file_extension('test.sh') is False
    
    def test_sanitize_filename(self):
        """Test filename sanitization."""
        assert SecurityValidator.sanitize_filename('test.mp3') == 'test.mp3'
        assert SecurityValidator.sanitize_filename('test/../file.mp3') == 'test..file.mp3'
        assert SecurityValidator.sanitize_filename('test\x00file.mp3') == 'testfile.mp3'
    
    def test_validate_playlist_name(self):
        """Test playlist name validation."""
        assert SecurityValidator.validate_playlist_name('My Playlist') == 'My Playlist'
        assert SecurityValidator.validate_playlist_name('test/../playlist') == 'test..playlist'
        assert SecurityValidator.validate_playlist_name('') is None
        assert SecurityValidator.validate_playlist_name('a' * 200) is not None  # Should be truncated
    
    def test_validate_dbus_path(self):
        """Test D-Bus path validation."""
        assert SecurityValidator.validate_dbus_path('/org/bluez/hci0') is True
        assert SecurityValidator.validate_dbus_path('/org/bluez/hci0/dev_00_11_22_33_44_55') is True
        assert SecurityValidator.validate_dbus_path('invalid') is False
        assert SecurityValidator.validate_dbus_path('/org/bluez/../etc') is False
    
    def test_validate_dbus_interface(self):
        """Test D-Bus interface validation."""
        assert SecurityValidator.validate_dbus_interface('org.bluez.Device1') is True
        assert SecurityValidator.validate_dbus_interface('org.mpris.MediaPlayer2') is True
        assert SecurityValidator.validate_dbus_interface('invalid') is False
        assert SecurityValidator.validate_dbus_interface('org..bluez') is False

