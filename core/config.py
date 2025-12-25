"""Configuration management using XDG Base Directory Specification.

This module provides centralized configuration management following Linux
standards for config, cache, and data directories.
"""

import configparser
import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any


class Config:
    """
    Configuration manager using XDG Base Directory Specification.
    
    Follows Linux standards:
    - Config: ~/.config/musicplayer/ (or XDG_CONFIG_HOME)
    - Cache: ~/.cache/musicplayer/ (or XDG_CACHE_HOME)
    - Data: ~/.local/share/musicplayer/ (or XDG_DATA_HOME)
    """
    
    _instance: Optional['Config'] = None
    
    def __init__(self) -> None:
        """
        Initialize configuration manager.
        
        Sets up XDG Base Directory paths and loads or creates configuration.
        """
        if Config._instance is not None:
            return
        
        # XDG Base Directory paths
        self.config_home = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))
        self.cache_home = Path(os.getenv('XDG_CACHE_HOME', Path.home() / '.cache'))
        self.data_home = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        
        # Application-specific directories
        self.app_name = 'musicplayer'
        self.config_dir = self.config_home / self.app_name
        self.cache_dir = self.cache_home / self.app_name
        self.data_dir = self.data_home / self.app_name
        
        # Create directories
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Config file
        self.config_file = self.config_dir / 'config.ini'
        self.config = configparser.ConfigParser()
        
        # Load or create default config
        self._load_config()
        
        # Migrate old configs if they exist
        self._migrate_old_configs()
        
        Config._instance = self
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """Get the singleton config instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _load_config(self) -> None:
        """Load configuration from file or create defaults."""
        if self.config_file.exists():
            self.config.read(self.config_file)
        else:
            self._create_default_config()
    
    def _create_default_config(self) -> None:
        """Create default configuration with sensible defaults."""
        # Library settings
        self.config['library'] = {
            'music_dirs': str(Path.home() / 'Music') + ':' + str(Path.home() / 'Musik'),
            'scan_on_startup': 'true',
            'index_file': str(self.cache_dir / 'library_index.json'),
        }
        
        # MOC settings
        self.config['moc'] = {
            'enabled': 'auto',  # auto, true, false
            'playlist_path': str(Path.home() / '.moc' / 'playlist.m3u'),
        }
        
        # Bluetooth settings
        self.config['bluetooth'] = {
            'device_name': 'Music Player',
            'auto_connect': 'true',
        }
        
        # Audio settings
        self.config['audio'] = {
            'volume': '1.0',
            'device': 'default',
        }
        
        # UI settings
        self.config['ui'] = {
            'window_width': '1200',
            'window_height': '800',
            'layout_file': str(self.config_dir / 'layout.json'),
        }
        
        # Save defaults
        self.save()
    
    def _migrate_old_configs(self) -> None:
        """
        Migrate old configuration files to new XDG locations.
        
        Handles migration from legacy config locations to XDG-compliant paths.
        """
        old_config_paths = [
            Path.home() / '.config' / 'musicplayer' / 'library_index.json',
            Path.home() / '.cache' / 'musicplayer' / 'art',
        ]
        
        # Migrate library index if it exists in old location
        old_index = Path.home() / '.config' / 'musicplayer' / 'library_index.json'
        new_index = self.cache_dir / 'library_index.json'
        if old_index.exists() and not new_index.exists():
            try:
                shutil.copy2(old_index, new_index)
                # Update config to point to new location
                self.config['library']['index_file'] = str(new_index)
                self.save()
            except Exception:
                pass  # Migration failed, continue with defaults
        
        # Migrate album art cache
        old_art_cache = Path.home() / '.cache' / 'musicplayer' / 'art'
        new_art_cache = self.cache_dir / 'art'
        if old_art_cache.exists() and not new_art_cache.exists():
            try:
                shutil.copytree(old_art_cache, new_art_cache)
            except Exception:
                pass  # Migration failed, continue with defaults
    
    def save(self) -> None:
        """
        Save configuration to file.
        
        Writes current configuration state to the config file.
        """
        try:
            with open(self.config_file, 'w') as f:
                self.config.write(f)
        except Exception as e:
            from core.logging import get_logger
            logger = get_logger(__name__)
            logger.error("Failed to save config: %s", e, exc_info=True)
    
    def get(self, section: str, key: str, fallback: Optional[str] = None) -> Optional[str]:
        """Get a configuration value."""
        return self.config.get(section, key, fallback=fallback)
    
    def set(self, section: str, key: str, value: str) -> None:
        """
        Set a configuration value.
        
        Args:
            section: Configuration section name
            key: Configuration key name
            value: Value to set (will be converted to string)
        """
        if section not in self.config:
            self.config.add_section(section)
        self.config.set(section, key, value)
        self.save()
    
    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        """Get a boolean configuration value."""
        return self.config.getboolean(section, key, fallback=fallback)
    
    def get_int(self, section: str, key: str, fallback: int = 0) -> int:
        """Get an integer configuration value."""
        return self.config.getint(section, key, fallback=fallback)
    
    def get_float(self, section: str, key: str, fallback: float = 0.0) -> float:
        """Get a float configuration value."""
        return self.config.getfloat(section, key, fallback=fallback)
    
    def get_path(self, section: str, key: str, fallback: Optional[Path] = None) -> Optional[Path]:
        """Get a path configuration value."""
        value = self.get(section, key)
        if value:
            return Path(value)
        return fallback
    
    def get_list(self, section: str, key: str, separator: str = ':', fallback: Optional[list[str]] = None) -> list[str]:
        """
        Get a list configuration value (colon or semicolon separated).
        
        Args:
            section: Configuration section name
            key: Configuration key name
            separator: Separator character (default: ':')
            fallback: Default value if not found
            
        Returns:
            List of strings
        """
        value = self.get(section, key)
        if value:
            return [item.strip() for item in value.split(separator) if item.strip()]
        return fallback or []
    
    # Convenience properties
    @property
    def library_index_file(self) -> Path:
        """Get library index file path."""
        return self.get_path('library', 'index_file', self.cache_dir / 'library_index.json')
    
    @property
    def album_art_cache_dir(self) -> Path:
        """Get album art cache directory."""
        art_dir = self.cache_dir / 'art'
        art_dir.mkdir(parents=True, exist_ok=True)
        return art_dir
    
    @property
    def music_directories(self) -> list[Path]:
        """Get list of music directories to scan."""
        dirs = self.get_list('library', 'music_dirs')
        return [Path(d) for d in dirs if Path(d).exists()]
    
    @property
    def moc_playlist_path(self) -> Path:
        """Get MOC playlist path."""
        return self.get_path('moc', 'playlist_path', Path.home() / '.moc' / 'playlist.m3u')
    
    @property
    def layout_file(self) -> Path:
        """Get layout configuration file path."""
        return self.get_path('ui', 'layout_file', self.config_dir / 'layout.json')
    
    @property
    def log_dir(self) -> Path:
        """Get log directory."""
        log_dir = self.data_dir / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir


# Convenience function
def get_config() -> Config:
    """Get the configuration instance."""
    return Config.get_instance()

