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

logger = get_logger(__name__)


# MPRIS2 interfaces
MPRIS2_BUS_NAME = 'org.mpris.MediaPlayer2.musicplayer'
MPRIS2_OBJECT_PATH = '/org/mpris/MediaPlayer2'
MPRIS2_ROOT_INTERFACE = 'org.mpris.MediaPlayer2'
MPRIS2_PLAYER_INTERFACE = 'org.mpris.MediaPlayer2.Player'
MPRIS2_TRACKLIST_INTERFACE = 'org.mpris.MediaPlayer2.TrackList'
MPRIS2_PLAYLISTS_INTERFACE = 'org.mpris.MediaPlayer2.Playlists'
PROPERTIES_INTERFACE = 'org.freedesktop.DBus.Properties'


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
    
    # Properties interface implementation (overrides parent to handle both interfaces)
    @dbus.service.method(PROPERTIES_INTERFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name: str, property_name: str):
        """Get a property value."""
        # Handle root interface properties
        if interface_name == MPRIS2_ROOT_INTERFACE:
            if property_name == 'CanQuit':
                return dbus.Boolean(self._can_quit)
            elif property_name == 'CanRaise':
                return dbus.Boolean(self._can_raise)
            elif property_name == 'HasTrackList':
                return dbus.Boolean(self._has_track_list)
            elif property_name == 'Identity':
                return dbus.String(self._identity)
            elif property_name == 'SupportedUriSchemes':
                return dbus.Array([dbus.String(s) for s in self._supported_uri_schemes], signature='s')
            elif property_name == 'SupportedMimeTypes':
                return dbus.Array([dbus.String(s) for s in self._supported_mime_types], signature='s')
            else:
                raise dbus.exceptions.DBusException(
                    PROPERTIES_INTERFACE + '.UnknownProperty',
                    f'Unknown property: {property_name}'
                )
        # Handle player interface properties
        elif interface_name == MPRIS2_PLAYER_INTERFACE:
            return self._get_player_property(property_name)
        else:
            raise dbus.exceptions.DBusException(
                PROPERTIES_INTERFACE + '.UnknownInterface',
                f'Unknown interface: {interface_name}'
            )
    
    def _get_player_property(self, property_name: str):
        """Get a player interface property value."""
        if property_name == 'PlaybackStatus':
            return dbus.String(self._playback_status)
        elif property_name == 'Rate':
            return dbus.Double(self._rate)
        elif property_name == 'Metadata':
            # Convert metadata dict to dbus.Dictionary
            metadata_dict = {}
            for key, value in self._metadata.items():
                if isinstance(value, dbus.ObjectPath):
                    metadata_dict[key] = value
                elif isinstance(value, dbus.Int64):
                    metadata_dict[key] = value
                elif isinstance(value, str):
                    metadata_dict[key] = dbus.String(value)
                elif isinstance(value, list):
                    metadata_dict[key] = dbus.Array([dbus.String(v) for v in value], signature='s')
                else:
                    metadata_dict[key] = dbus.String(str(value))
            return dbus.Dictionary(metadata_dict, signature='sv')
        elif property_name == 'Volume':
            return dbus.Double(self._volume)
        elif property_name == 'Position':
            return dbus.Int64(int(self._position * 1_000_000))
        elif property_name == 'MinimumRate':
            return dbus.Double(self._minimum_rate)
        elif property_name == 'MaximumRate':
            return dbus.Double(self._maximum_rate)
        elif property_name == 'CanGoNext':
            return dbus.Boolean(self._can_go_next)
        elif property_name == 'CanGoPrevious':
            return dbus.Boolean(self._can_go_previous)
        elif property_name == 'CanPlay':
            return dbus.Boolean(self._can_play)
        elif property_name == 'CanPause':
            return dbus.Boolean(self._can_pause)
        elif property_name == 'CanSeek':
            return dbus.Boolean(self._can_seek)
        elif property_name == 'CanControl':
            return dbus.Boolean(self._can_control)
        else:
            raise dbus.exceptions.DBusException(
                PROPERTIES_INTERFACE + '.UnknownProperty',
                f'Unknown property: {property_name}'
            )
    
    @dbus.service.method(PROPERTIES_INTERFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name: str):
        """Get all properties for an interface."""
        if interface_name == MPRIS2_ROOT_INTERFACE:
            return {
                'CanQuit': dbus.Boolean(self._can_quit),
                'CanRaise': dbus.Boolean(self._can_raise),
                'HasTrackList': dbus.Boolean(self._has_track_list),
                'Identity': dbus.String(self._identity),
                'SupportedUriSchemes': dbus.Array([dbus.String(s) for s in self._supported_uri_schemes], signature='s'),
                'SupportedMimeTypes': dbus.Array([dbus.String(s) for s in self._supported_mime_types], signature='s'),
            }
        elif interface_name == MPRIS2_PLAYER_INTERFACE:
            # Convert metadata dict to dbus.Dictionary
            metadata_dict = {}
            for key, value in self._metadata.items():
                if isinstance(value, (dbus.ObjectPath, dbus.Int64)):
                    metadata_dict[key] = value
                elif isinstance(value, str):
                    metadata_dict[key] = dbus.String(value)
                elif isinstance(value, list):
                    metadata_dict[key] = dbus.Array([dbus.String(v) for v in value], signature='s')
                else:
                    metadata_dict[key] = dbus.String(str(value))
            
            return {
                'PlaybackStatus': dbus.String(self._playback_status),
                'Rate': dbus.Double(self._rate),
                'Metadata': dbus.Dictionary(metadata_dict, signature='sv'),
                'Volume': dbus.Double(self._volume),
                'Position': dbus.Int64(int(self._position * 1_000_000)),
                'MinimumRate': dbus.Double(self._minimum_rate),
                'MaximumRate': dbus.Double(self._maximum_rate),
                'CanGoNext': dbus.Boolean(self._can_go_next),
                'CanGoPrevious': dbus.Boolean(self._can_go_previous),
                'CanPlay': dbus.Boolean(self._can_play),
                'CanPause': dbus.Boolean(self._can_pause),
                'CanSeek': dbus.Boolean(self._can_seek),
                'CanControl': dbus.Boolean(self._can_control),
            }
        else:
            raise dbus.exceptions.DBusException(
                PROPERTIES_INTERFACE + '.UnknownInterface',
                f'Unknown interface: {interface_name}'
            )
    
    @dbus.service.method(PROPERTIES_INTERFACE, in_signature='ssv')
    def Set(self, interface_name: str, property_name: str, value):
        """Set a property value."""
        if interface_name == MPRIS2_ROOT_INTERFACE:
            # MPRIS2 root properties are read-only
            raise dbus.exceptions.DBusException(
                PROPERTIES_INTERFACE + '.PropertyReadOnly',
                f'Property {property_name} is read-only'
            )
        elif interface_name == MPRIS2_PLAYER_INTERFACE:
            if property_name == 'Volume':
                # Convert dbus value to float
                if isinstance(value, dbus.Double):
                    new_volume = float(value)
                else:
                    new_volume = float(value)
                
                if abs(self._volume - new_volume) > 0.01:
                    self._volume = max(0.0, min(1.0, new_volume))
                    self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'Volume': dbus.Double(self._volume)}, [])
                    if self.on_set_volume:
                        self.on_set_volume(self._volume)
            else:
                raise dbus.exceptions.DBusException(
                    PROPERTIES_INTERFACE + '.PropertyReadOnly',
                    f'Property {property_name} is read-only'
                )
        else:
            raise dbus.exceptions.DBusException(
                PROPERTIES_INTERFACE + '.UnknownInterface',
                f'Unknown interface: {interface_name}'
            )


class MPRIS2Player(MPRIS2Root):
    """MPRIS2 Player interface (org.mpris.MediaPlayer2.Player).
    
    Inherits from MPRIS2Root so both interfaces are on the same object path.
    """
    
    def __init__(self, bus, object_path):
        # Initialize root interface first
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
            if hasattr(self, 'on_open_uri'):
                self.on_open_uri(file_path)
    
    @dbus.service.signal(MPRIS2_PLAYER_INTERFACE, signature='x')
    def Seeked(self, position: int):
        """Signal emitted when position changes via SetPosition."""
        pass
    
    
    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface: str, changed: Dict[str, Any], invalidated: List[str]):
        """Signal emitted when properties change."""
        pass
    
    # Property setters for internal use
    def _set_playback_status(self, value: str):
        """Set playback status (internal use)."""
        if self._playback_status != value:
            self._playback_status = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'PlaybackStatus': dbus.String(value)}, [])
    
    def _set_metadata(self, value: Dict[str, Any]):
        """Set metadata (internal use)."""
        if self._metadata != value:
            self._metadata = value
            # Convert to dbus types for signal
            metadata_dict = {}
            for key, val in value.items():
                if isinstance(val, (dbus.ObjectPath, dbus.Int64)):
                    metadata_dict[key] = val
                elif isinstance(val, str):
                    metadata_dict[key] = dbus.String(val)
                elif isinstance(val, list):
                    metadata_dict[key] = dbus.Array([dbus.String(v) for v in val], signature='s')
                else:
                    metadata_dict[key] = dbus.String(str(val))
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'Metadata': dbus.Dictionary(metadata_dict, signature='sv')}, [])
    
    def _set_can_go_next(self, value: bool):
        """Set CanGoNext (internal use)."""
        if self._can_go_next != value:
            self._can_go_next = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'CanGoNext': dbus.Boolean(value)}, [])
    
    def _set_can_go_previous(self, value: bool):
        """Set CanGoPrevious (internal use)."""
        if self._can_go_previous != value:
            self._can_go_previous = value
            self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, {'CanGoPrevious': dbus.Boolean(value)}, [])
    
    def update_metadata(self, track: Optional[TrackMetadata]):
        """Update metadata from track."""
        if not track:
            self._set_metadata({})
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
        
        self._set_metadata(metadata)
    
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
        self._set_playback_status(status)


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
            # Create combined object (player inherits from root, so both interfaces are on same path)
            self.player = MPRIS2Player(self.bus, MPRIS2_OBJECT_PATH)
            # Keep reference to root for callbacks (it's the same object)
            self.root = self.player
            
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
            # Use Set method to update volume (triggers callback if needed)
            self.player.Set(MPRIS2_PLAYER_INTERFACE, 'Volume', dbus.Double(volume))
    
    def update_can_go_next(self, can_go: bool):
        """Update whether Next() is available."""
        if self.player:
            self.player._set_can_go_next(can_go)
    
    def update_can_go_previous(self, can_go: bool):
        """Update whether Previous() is available."""
        if self.player:
            self.player._set_can_go_previous(can_go)
    
    def cleanup(self):
        """Clean up MPRIS2 resources."""
        try:
            if self._name_id:
                self.bus.release_name(MPRIS2_BUS_NAME)
            logger.info("MPRIS2: Cleaned up")
        except Exception as e:
            logger.error("MPRIS2: Error during cleanup: %s", e, exc_info=True)

