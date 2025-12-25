"""MPRIS2 (Media Player Remote Interfacing Specification) D-Bus interface.

This module implements MPRIS2 for desktop integration, allowing:
- Media key support (PlayPause, Next, Previous)
- Desktop environment integration (notifications, system tray)
- Remote control via D-Bus
"""

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from typing import Optional, Dict, Any, List
from pathlib import Path

from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

logger = get_logger(__name__)


# MPRIS2 interfaces
MPRIS2_BUS_NAME = 'org.mpris.MediaPlayer2.musicplayer'
MPRIS2_OBJECT_PATH = '/org/mpris/MediaPlayer2'
MPRIS2_ROOT_INTERFACE = 'org.mpris.MediaPlayer2'
MPRIS2_PLAYER_INTERFACE = 'org.mpris.MediaPlayer2.Player'
MPRIS2_TRACKLIST_INTERFACE = 'org.mpris.MediaPlayer2.TrackList'
MPRIS2_PLAYLISTS_INTERFACE = 'org.mpris.MediaPlayer2.Playlists'


class MPRIS2Root(dbus.service.Object):
    """MPRIS2 root interface (org.mpris.MediaPlayer2)."""
    
    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)
        self._can_quit = True
        self._can_raise = True
        self._has_track_list = True
        self._identity = "Music Player"
        self._supported_uri_schemes = ['file']
        self._supported_mime_types = [
            'audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/mp4',
            'video/mp4', 'video/x-matroska', 'video/webm'
        ]
    
    @dbus.service.method(MPRIS2_ROOT_INTERFACE, in_signature='', out_signature='')
    def Quit(self):
        """Quit the application."""
        logger.info("MPRIS2: Quit requested")
        # Signal to main window to close
        if hasattr(self, 'on_quit'):
            self.on_quit()
    
    @dbus.service.method(MPRIS2_ROOT_INTERFACE, in_signature='', out_signature='')
    def Raise(self):
        """Raise the application window."""
        logger.debug("MPRIS2: Raise requested")
        if hasattr(self, 'on_raise'):
            self.on_raise()
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='b')
    def CanQuit(self):
        """Whether the application can be quit."""
        return self._can_quit
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='b')
    def CanRaise(self):
        """Whether the application window can be raised."""
        return self._can_raise
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='b')
    def HasTrackList(self):
        """Whether the application has a track list."""
        return self._has_track_list
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='s')
    def Identity(self):
        """Application identity."""
        return self._identity
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='as')
    def SupportedUriSchemes(self):
        """Supported URI schemes."""
        return self._supported_uri_schemes
    
    @dbus.service.property(MPRIS2_ROOT_INTERFACE, signature='as')
    def SupportedMimeTypes(self):
        """Supported MIME types."""
        return self._supported_mime_types


class MPRIS2Player(dbus.service.Object):
    """MPRIS2 Player interface (org.mpris.MediaPlayer2.Player)."""
    
    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)
        self._playback_status = 'Stopped'  # Playing, Paused, Stopped
        self._rate = 1.0
        self._metadata: Dict[str, Any] = {}
        self._volume = 1.0
        self._position = 0.0
        self._minimum_rate = 1.0
        self._maximum_rate = 1.0
        self._can_go_next = True
        self._can_go_previous = True
        self._can_play = True
        self._can_pause = True
        self._can_seek = True
        self._can_control = True
        
        # Callbacks to control playback
        self.on_play: Optional[callable] = None
        self.on_pause: Optional[callable] = None
        self.on_stop: Optional[callable] = None
        self.on_next: Optional[callable] = None
        self.on_previous: Optional[callable] = None
        self.on_seek: Optional[callable] = None
        self.on_set_position: Optional[callable] = None
        self.on_set_volume: Optional[callable] = None
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def Next(self):
        """Skip to next track."""
        logger.info("MPRIS2: Next requested")
        if self.on_next:
            self.on_next()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def Previous(self):
        """Skip to previous track."""
        logger.info("MPRIS2: Previous requested")
        if self.on_previous:
            self.on_previous()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def Pause(self):
        """Pause playback."""
        logger.info("MPRIS2: Pause requested")
        if self.on_pause:
            self.on_pause()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def PlayPause(self):
        """Toggle play/pause."""
        logger.info("MPRIS2: PlayPause requested")
        if self._playback_status == 'Playing':
            if self.on_pause:
                self.on_pause()
        else:
            if self.on_play:
                self.on_play()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def Stop(self):
        """Stop playback."""
        logger.info("MPRIS2: Stop requested")
        if self.on_stop:
            self.on_stop()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='', out_signature='')
    def Play(self):
        """Start or resume playback."""
        logger.info("MPRIS2: Play requested")
        if self.on_play:
            self.on_play()
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='x', out_signature='')
    def Seek(self, offset: int):
        """Seek forward or backward by offset microseconds."""
        logger.debug("MPRIS2: Seek requested: %d microseconds", offset)
        if self.on_seek:
            seconds = offset / 1_000_000.0
            self.on_seek(seconds)
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='ox', out_signature='')
    def SetPosition(self, track_id: str, position: int):
        """Set position in microseconds for a specific track."""
        logger.debug("MPRIS2: SetPosition requested: track_id=%s, position=%d", track_id, position)
        if self.on_set_position:
            seconds = position / 1_000_000.0
            self.on_set_position(track_id, seconds)
    
    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature='s', out_signature='')
    def OpenUri(self, uri: str):
        """Open a URI for playback."""
        logger.info("MPRIS2: OpenUri requested: %s", uri)
        # Convert file:// URI to path
        if uri.startswith('file://'):
            file_path = uri[7:]  # Remove 'file://' prefix
            # Security: Validate path
            validated_path = SecurityValidator.validate_path(file_path)
            if validated_path and SecurityValidator.validate_file_extension(str(validated_path)):
                if hasattr(self, 'on_open_uri'):
                    self.on_open_uri(str(validated_path))
            else:
                logger.warning("MPRIS2: Invalid or unsafe URI: %s", uri)
    
    @dbus.service.signal(MPRIS2_PLAYER_INTERFACE, signature='x')
    def Seeked(self, position: int):
        """Signal emitted when position changes via SetPosition."""
        pass
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='s', emits_change_signal=True)
    def PlaybackStatus(self):
        """Current playback status: Playing, Paused, Stopped."""
        return self._playback_status
    
    @PlaybackStatus.setter
    def PlaybackStatus(self, value: str):
        if self._playback_status != value:
            self._playback_status = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'PlaybackStatus': value}, [])
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='d', emits_change_signal=True)
    def Rate(self):
        """Playback rate (1.0 = normal)."""
        return self._rate
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='a{sv}', emits_change_signal=True)
    def Metadata(self):
        """Current track metadata."""
        return self._metadata
    
    @Metadata.setter
    def Metadata(self, value: Dict[str, Any]):
        if self._metadata != value:
            self._metadata = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'Metadata': value}, [])
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='d', emits_change_signal=True)
    def Volume(self):
        """Volume (0.0 to 1.0)."""
        return self._volume
    
    @Volume.setter
    def Volume(self, value: float):
        if abs(self._volume - value) > 0.01:
            self._volume = max(0.0, min(1.0, value))
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'Volume': dbus.Double(self._volume)}, [])
            if self.on_set_volume:
                self.on_set_volume(self._volume)
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='x')
    def Position(self):
        """Current position in microseconds."""
        return int(self._position * 1_000_000)
    
    @Position.setter
    def Position(self, value: float):
        """Set position in seconds (internal use)."""
        self._position = value
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='d')
    def MinimumRate(self):
        """Minimum playback rate."""
        return self._minimum_rate
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='d')
    def MaximumRate(self):
        """Maximum playback rate."""
        return self._maximum_rate
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanGoNext(self):
        """Whether Next() is available."""
        return self._can_go_next
    
    @CanGoNext.setter
    def CanGoNext(self, value: bool):
        if self._can_go_next != value:
            self._can_go_next = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'CanGoNext': value}, [])
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanGoPrevious(self):
        """Whether Previous() is available."""
        return self._can_go_previous
    
    @CanGoPrevious.setter
    def CanGoPrevious(self, value: bool):
        if self._can_go_previous != value:
            self._can_go_previous = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'CanGoPrevious': value}, [])
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanPlay(self):
        """Whether Play() is available."""
        return self._can_play
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanPause(self):
        """Whether Pause() is available."""
        return self._can_pause
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanSeek(self):
        """Whether seeking is available."""
        return self._can_seek
    
    @dbus.service.property(MPRIS2_PLAYER_INTERFACE, signature='b')
    def CanControl(self):
        """Whether playback control is available."""
        return self._can_control
    
    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface: str, changed: Dict[str, Any], invalidated: List[str]):
        """Signal emitted when properties change."""
        pass
    
    def update_metadata(self, track: Optional[TrackMetadata]):
        """Update metadata from track."""
        if not track:
            self.Metadata = {}
            return
        
        # Build MPRIS2 metadata dict
        metadata = {}
        
        # Track ID (required)
        track_id = f"/org/mpris/MediaPlayer2/Track/{hash(track.file_path) & 0xFFFFFFFF}"
        metadata['mpris:trackid'] = dbus.ObjectPath(track_id)
        
        # File path as URI
        if track.file_path:
            file_path = Path(track.file_path).resolve()
            metadata['xesam:url'] = f"file://{file_path}"
            metadata['xesam:title'] = track.title or file_path.name
        else:
            metadata['xesam:title'] = track.title or "Unknown"
        
        # Artist
        if track.artist:
            metadata['xesam:artist'] = [track.artist]
        elif track.album_artist:
            metadata['xesam:artist'] = [track.album_artist]
        
        # Album
        if track.album:
            metadata['xesam:album'] = track.album
        
        # Duration in microseconds
        if track.duration:
            metadata['mpris:length'] = dbus.Int64(int(track.duration * 1_000_000))
        
        # Track number
        if track.track_number:
            metadata['xesam:trackNumber'] = track.track_number
        
        # Art URL
        if track.album_art_path:
            art_path = Path(track.album_art_path).resolve()
            metadata['mpris:artUrl'] = f"file://{art_path}"
        
        self.Metadata = metadata
    
    def update_position(self, position: float):
        """Update playback position in seconds."""
        self._position = position
    
    def update_playback_status(self, is_playing: bool, is_paused: bool = False):
        """Update playback status."""
        if is_playing:
            status = 'Playing'
        elif is_paused:
            status = 'Paused'
        else:
            status = 'Stopped'
        self.PlaybackStatus = status


class MPRIS2Manager:
    """Manager for MPRIS2 D-Bus interfaces."""
    
    def __init__(self):
        """Initialize MPRIS2 manager."""
        DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.root: Optional[MPRIS2Root] = None
        self.player: Optional[MPRIS2Player] = None
        self._name_id: Optional[int] = None
        
        # Request bus name
        try:
            self._name_id = self.bus.request_name(
                MPRIS2_BUS_NAME,
                dbus.bus.NAME_FLAG_REPLACE_EXISTING
            )
            if self._name_id == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER:
                logger.info("MPRIS2: Acquired bus name %s", MPRIS2_BUS_NAME)
                self._setup_interfaces()
            else:
                logger.warning("MPRIS2: Could not acquire bus name (may already be in use)")
        except Exception as e:
            logger.error("MPRIS2: Failed to register: %s", e, exc_info=True)
    
    def _setup_interfaces(self):
        """Set up MPRIS2 interfaces."""
        try:
            # Create root interface
            self.root = MPRIS2Root(self.bus, MPRIS2_OBJECT_PATH)
            
            # Create player interface
            self.player = MPRIS2Player(self.bus, MPRIS2_OBJECT_PATH)
            
            logger.info("MPRIS2: Interfaces registered successfully")
        except Exception as e:
            logger.error("MPRIS2: Failed to set up interfaces: %s", e, exc_info=True)
    
    def set_playback_callbacks(self, on_play=None, on_pause=None, on_stop=None,
                               on_next=None, on_previous=None, on_seek=None,
                               on_set_position=None, on_set_volume=None):
        """Set playback control callbacks."""
        if self.player:
            self.player.on_play = on_play
            self.player.on_pause = on_pause
            self.player.on_stop = on_stop
            self.player.on_next = on_next
            self.player.on_previous = on_previous
            self.player.on_seek = on_seek
            self.player.on_set_position = on_set_position
            self.player.on_set_volume = on_set_volume
    
    def set_window_callbacks(self, on_quit=None, on_raise=None):
        """Set window control callbacks."""
        if self.root:
            self.root.on_quit = on_quit
            self.root.on_raise = on_raise
    
    def update_metadata(self, track: Optional[TrackMetadata]):
        """Update current track metadata."""
        if self.player:
            self.player.update_metadata(track)
    
    def update_position(self, position: float):
        """Update playback position."""
        if self.player:
            self.player.update_position(position)
    
    def update_playback_status(self, is_playing: bool, is_paused: bool = False):
        """Update playback status."""
        if self.player:
            self.player.update_playback_status(is_playing, is_paused)
    
    def update_volume(self, volume: float):
        """Update volume."""
        if self.player:
            self.player.Volume = volume
    
    def update_can_go_next(self, can_go: bool):
        """Update whether Next() is available."""
        if self.player:
            self.player.CanGoNext = can_go
    
    def update_can_go_previous(self, can_go: bool):
        """Update whether Previous() is available."""
        if self.player:
            self.player.CanGoPrevious = can_go
    
    def cleanup(self):
        """Clean up MPRIS2 resources."""
        try:
            if self._name_id:
                self.bus.release_name(MPRIS2_BUS_NAME)
            logger.info("MPRIS2: Cleaned up")
        except Exception as e:
            logger.error("MPRIS2: Error during cleanup: %s", e, exc_info=True)

