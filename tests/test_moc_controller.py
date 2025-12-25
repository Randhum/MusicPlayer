"""Tests for MOC controller."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path


class TestMocController:
    """Test MocController class."""
    
    @pytest.fixture
    def moc_controller(self, mock_config):
        """Create MocController instance."""
        with patch('core.moc_controller.shutil.which', return_value='/usr/bin/mocp'):
            with patch('core.moc_controller.subprocess.run'):
                from core.moc_controller import MocController
                return MocController()
    
    def test_is_available(self, moc_controller):
        """Test MOC availability check."""
        # Should be available if mocp path is set
        assert moc_controller.is_available() is True
    
    def test_is_available_not_found(self, mock_config):
        """Test MOC availability when not found."""
        with patch('core.moc_controller.shutil.which', return_value=None):
            from core.moc_controller import MocController
            controller = MocController()
            assert controller.is_available() is False
    
    def test_get_status(self, moc_controller):
        """Test getting MOC status."""
        with patch('core.moc_controller.subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="State: PLAY\nFile: /path/to/file.mp3\nCurrentSec: 30.0\nTotalSec: 180.0\nVolume: 75%"
            )
            
            status = moc_controller.get_status()
            assert status is not None
            assert status.get('state') == 'PLAY'
            assert status.get('position') == 30.0
            assert status.get('duration') == 180.0

