"""Pytest configuration and fixtures."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Mock GStreamer and GTK before imports
import sys
from unittest.mock import MagicMock

# Mock gi.repository
sys.modules['gi'] = MagicMock()
sys.modules['gi.repository'] = MagicMock()
sys.modules['gi.repository.Gst'] = MagicMock()
sys.modules['gi.repository.GLib'] = MagicMock()
sys.modules['gi.repository.Gtk'] = MagicMock()

try:
    sys.modules['gi.repository.Adw'] = MagicMock()
except:
    pass


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_config(monkeypatch, temp_dir):
    """Mock configuration with temporary directories."""
    from core.config import Config
    
    # Override config directories
    monkeypatch.setattr(Config, 'config_dir', temp_dir / 'config')
    monkeypatch.setattr(Config, 'cache_dir', temp_dir / 'cache')
    monkeypatch.setattr(Config, 'data_dir', temp_dir / 'data')
    
    # Create directories
    (temp_dir / 'config').mkdir(parents=True)
    (temp_dir / 'cache').mkdir(parents=True)
    (temp_dir / 'data').mkdir(parents=True)
    
    return Config.get_instance()


@pytest.fixture
def mock_logger(monkeypatch):
    """Mock logger to avoid file system operations."""
    import logging
    logger = logging.getLogger('test')
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def sample_audio_file(temp_dir):
    """Create a sample audio file path for testing."""
    audio_file = temp_dir / 'test.mp3'
    audio_file.touch()
    return str(audio_file)

