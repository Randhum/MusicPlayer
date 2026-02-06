"""Tests for configuration management."""

import pytest
from pathlib import Path
from core.config import Config, get_config


class TestConfig:
    """Test Config class."""
    
    def test_get_instance(self, temp_dir):
        """Test singleton pattern."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2
    
    def test_xdg_directories(self, temp_dir, monkeypatch):
        """Test XDG directory resolution."""
        monkeypatch.setenv('XDG_CONFIG_HOME', str(temp_dir / 'config'))
        monkeypatch.setenv('XDG_CACHE_HOME', str(temp_dir / 'cache'))
        monkeypatch.setenv('XDG_DATA_HOME', str(temp_dir / 'data'))
        
        # Reset singleton
        Config._instance = None
        
        config = get_config()
        assert config.config_dir == temp_dir / 'config' / 'musicplayer'
        assert config.cache_dir == temp_dir / 'cache' / 'musicplayer'
        assert config.data_dir == temp_dir / 'data' / 'musicplayer'
    
    def test_config_get_set(self, mock_config):
        """Test getting and setting config values."""
        mock_config.set('library', 'scan_on_startup', 'false')
        assert mock_config.get('library', 'scan_on_startup') == 'false'
        assert mock_config.get_bool('library', 'scan_on_startup') is False
    
    def test_config_get_list(self, mock_config):
        """Test getting list values."""
        mock_config.set('library', 'music_dirs', '/path1:/path2:/path3')
        dirs = mock_config.get_list('library', 'music_dirs')
        assert len(dirs) == 3
        assert '/path1' in dirs
        assert '/path2' in dirs
        assert '/path3' in dirs
    
    def test_config_properties(self, mock_config):
        """Test config convenience properties."""
        assert isinstance(mock_config.library_index_file, Path)
        assert isinstance(mock_config.album_art_cache_dir, Path)
        assert isinstance(mock_config.music_directories, list)

