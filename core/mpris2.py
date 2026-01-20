"""MPRIS2 (Media Player Remote Interfacing Specification) D-Bus interface.

This module implements MPRIS2 for desktop integration, allowing:
- Media key support (PlayPause, Next, Previous)
- Desktop environment integration (notifications, system tray)
- Remote control via D-Bus

Architecture:
- Uses dbus.service.Object for high-level D-Bus service implementation
- Implements org.freedesktop.DBus.Properties interface for property access
- Follows MPRIS2 specification for media player control
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from pathlib import Path
from typing import Any, Dict, List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.dbus_utils import DBusConnectionMonitor, dbus_safe_call
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.security import SecurityValidator

logger = get_logger(__name__)


# MPRIS2 interfaces
MPRIS2_BUS_NAME = "org.mpris.MediaPlayer2.musicplayer"
MPRIS2_OBJECT_PATH = "/org/mpris/MediaPlayer2"
MPRIS2_ROOT_INTERFACE = "org.mpris.MediaPlayer2"
MPRIS2_PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
MPRIS2_TRACKLIST_INTERFACE = "org.mpris.MediaPlayer2.TrackList"
MPRIS2_PLAYLISTS_INTERFACE = "org.mpris.MediaPlayer2.Playlists"


class MPRIS2Service(dbus.service.Object):
    """
    Combined MPRIS2 service implementing both root and player interfaces.

    Per MPRIS2 specification, both interfaces must be on the same object path.
    This single object implements:
    - org.mpris.MediaPlayer2 (root interface)
    - org.mpris.MediaPlayer2.Player (player interface)
    """

    PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

    def __init__(self, bus, object_path):
        super().__init__(bus, object_path)

        # Root interface properties
        self._can_quit = True
        self._can_raise = True
        self._has_track_list = True
        self._identity = "Music Player"
        self._supported_uri_schemes = ["file"]
        self._supported_mime_types = [
            "audio/mpeg",
            "audio/flac",
            "audio/ogg",
            "audio/mp4",
            "video/mp4",
            "video/x-matroska",
            "video/webm",
        ]

        # Player interface properties
        self._playback_status = "Stopped"  # Playing, Paused, Stopped
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
        self.on_quit: Optional[callable] = None
        self.on_raise: Optional[callable] = None

    @dbus.service.method(MPRIS2_ROOT_INTERFACE, in_signature="", out_signature="")
    def Quit(self):
        """Quit the application."""
        try:
            logger.info("MPRIS2: Quit requested")
            # Signal to main window to close
            if hasattr(self, "on_quit"):
                self.on_quit()
        except Exception as e:
            logger.error("MPRIS2: Error handling Quit request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_ROOT_INTERFACE, in_signature="", out_signature="")
    def Raise(self):
        """Raise the application window."""
        try:
            logger.debug("MPRIS2: Raise requested")
            if hasattr(self, "on_raise"):
                self.on_raise()
        except Exception as e:
            logger.error("MPRIS2: Error handling Raise request: %s", e, exc_info=True)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface_name: str, property_name: str):
        """Get a property value (org.freedesktop.DBus.Properties interface)."""
        try:
            # Handle root interface properties
            if interface_name == MPRIS2_ROOT_INTERFACE:
                prop_map = {
                    "CanQuit": dbus.Boolean(self._can_quit),
                    "CanRaise": dbus.Boolean(self._can_raise),
                    "HasTrackList": dbus.Boolean(self._has_track_list),
                    "Identity": dbus.String(self._identity),
                    "SupportedUriSchemes": dbus.Array(
                        self._supported_uri_schemes, signature="s"
                    ),
                    "SupportedMimeTypes": dbus.Array(
                        self._supported_mime_types, signature="s"
                    ),
                }
            # Handle player interface properties
            elif interface_name == MPRIS2_PLAYER_INTERFACE:
                prop_map = {
                    "PlaybackStatus": dbus.String(self._playback_status),
                    "Rate": dbus.Double(self._rate),
                    "Metadata": self._metadata,
                    "Volume": dbus.Double(self._volume),
                    "Position": dbus.Int64(int(self._position * 1_000_000)),
                    "MinimumRate": dbus.Double(self._minimum_rate),
                    "MaximumRate": dbus.Double(self._maximum_rate),
                    "CanGoNext": dbus.Boolean(self._can_go_next),
                    "CanGoPrevious": dbus.Boolean(self._can_go_previous),
                    "CanPlay": dbus.Boolean(self._can_play),
                    "CanPause": dbus.Boolean(self._can_pause),
                    "CanSeek": dbus.Boolean(self._can_seek),
                    "CanControl": dbus.Boolean(self._can_control),
                }
            else:
                raise dbus.exceptions.DBusException(
                    f"{self.__class__.__name__}.UnknownInterface",
                    f"Interface {interface_name} not found",
                )

            if property_name not in prop_map:
                raise dbus.exceptions.DBusException(
                    f"{self.__class__.__name__}.UnknownProperty",
                    f"Property {property_name} not found",
                )

            return prop_map[property_name]
        except dbus.exceptions.DBusException:
            raise
        except Exception as e:
            logger.error(
                "MPRIS2: Error getting property %s.%s: %s",
                interface_name,
                property_name,
                e,
                exc_info=True,
            )
            raise dbus.exceptions.DBusException(
                f"{self.__class__.__name__}.Error", f"Error getting property: {e}"
            )

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface_name: str):
        """Get all properties (org.freedesktop.DBus.Properties interface)."""
        try:
            if interface_name == MPRIS2_ROOT_INTERFACE:
                return {
                    "CanQuit": dbus.Boolean(self._can_quit),
                    "CanRaise": dbus.Boolean(self._can_raise),
                    "HasTrackList": dbus.Boolean(self._has_track_list),
                    "Identity": dbus.String(self._identity),
                    "SupportedUriSchemes": dbus.Array(
                        self._supported_uri_schemes, signature="s"
                    ),
                    "SupportedMimeTypes": dbus.Array(
                        self._supported_mime_types, signature="s"
                    ),
                }
            elif interface_name == MPRIS2_PLAYER_INTERFACE:
                return {
                    "PlaybackStatus": dbus.String(self._playback_status),
                    "Rate": dbus.Double(self._rate),
                    "Metadata": self._metadata,
                    "Volume": dbus.Double(self._volume),
                    "Position": dbus.Int64(int(self._position * 1_000_000)),
                    "MinimumRate": dbus.Double(self._minimum_rate),
                    "MaximumRate": dbus.Double(self._maximum_rate),
                    "CanGoNext": dbus.Boolean(self._can_go_next),
                    "CanGoPrevious": dbus.Boolean(self._can_go_previous),
                    "CanPlay": dbus.Boolean(self._can_play),
                    "CanPause": dbus.Boolean(self._can_pause),
                    "CanSeek": dbus.Boolean(self._can_seek),
                    "CanControl": dbus.Boolean(self._can_control),
                }
            else:
                raise dbus.exceptions.DBusException(
                    f"{self.__class__.__name__}.UnknownInterface",
                    f"Interface {interface_name} not found",
                )
        except dbus.exceptions.DBusException:
            raise
        except Exception as e:
            logger.error("MPRIS2: Error getting all properties: %s", e, exc_info=True)
            raise dbus.exceptions.DBusException(
                f"{self.__class__.__name__}.Error", f"Error getting properties: {e}"
            )

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv")
    def Set(self, interface_name: str, property_name: str, value):
        """Set a property value (org.freedesktop.DBus.Properties interface)."""
        try:
            if interface_name != MPRIS2_PLAYER_INTERFACE:
                raise dbus.exceptions.DBusException(
                    f"{self.__class__.__name__}.UnknownInterface",
                    f"Interface {interface_name} not found",
                )

            # Only Volume is writable according to MPRIS2 spec
            if property_name == "Volume":
                volume = float(value)
                volume = max(0.0, min(1.0, volume))
                if abs(self._volume - volume) > 0.01:
                    self._volume = volume
                    self.PropertiesChanged(
                        MPRIS2_PLAYER_INTERFACE,
                        {"Volume": dbus.Double(self._volume)},
                        [],
                    )
                    if self.on_set_volume:
                        self.on_set_volume(self._volume)
            else:
                raise dbus.exceptions.DBusException(
                    f"{self.__class__.__name__}.PropertyReadOnly",
                    f"Property {property_name} is read-only",
                )
        except dbus.exceptions.DBusException:
            raise
        except Exception as e:
            logger.error(
                "MPRIS2: Error setting property %s: %s", property_name, e, exc_info=True
            )
            raise dbus.exceptions.DBusException(
                f"{self.__class__.__name__}.Error", f"Error setting property: {e}"
            )

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(
        self, interface: str, changed: Dict[str, Any], invalidated: List[str]
    ):
        """Signal emitted when properties change."""
        pass

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def Next(self):
        """Skip to next track."""
        try:
            logger.info("MPRIS2: Next requested")
            if self.on_next:
                self.on_next()
        except Exception as e:
            logger.error("MPRIS2: Error handling Next request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def Previous(self):
        """Skip to previous track."""
        try:
            logger.info("MPRIS2: Previous requested")
            if self.on_previous:
                self.on_previous()
        except Exception as e:
            logger.error(
                "MPRIS2: Error handling Previous request: %s", e, exc_info=True
            )

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def Pause(self):
        """Pause playback."""
        try:
            logger.info("MPRIS2: Pause requested")
            if self.on_pause:
                self.on_pause()
        except Exception as e:
            logger.error("MPRIS2: Error handling Pause request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def PlayPause(self):
        """Toggle play/pause."""
        try:
            logger.info("MPRIS2: PlayPause requested")
            if self._playback_status == "Playing":
                if self.on_pause:
                    self.on_pause()
            else:
                if self.on_play:
                    self.on_play()
        except Exception as e:
            logger.error(
                "MPRIS2: Error handling PlayPause request: %s", e, exc_info=True
            )

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def Stop(self):
        """Stop playback."""
        try:
            logger.info("MPRIS2: Stop requested")
            if self.on_stop:
                self.on_stop()
        except Exception as e:
            logger.error("MPRIS2: Error handling Stop request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="", out_signature="")
    def Play(self):
        """Start or resume playback."""
        try:
            logger.info("MPRIS2: Play requested")
            if self.on_play:
                self.on_play()
        except Exception as e:
            logger.error("MPRIS2: Error handling Play request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="x", out_signature="")
    def Seek(self, offset: int):
        """Seek forward or backward by offset microseconds."""
        try:
            logger.debug("MPRIS2: Seek requested: %d microseconds", offset)
            if self.on_seek:
                seconds = offset / 1_000_000.0
                self.on_seek(seconds)
        except Exception as e:
            logger.error("MPRIS2: Error handling Seek request: %s", e, exc_info=True)

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="ox", out_signature="")
    def SetPosition(self, track_id: str, position: int):
        """Set position in microseconds for a specific track."""
        try:
            logger.debug(
                "MPRIS2: SetPosition requested: track_id=%s, position=%d",
                track_id,
                position,
            )
            if self.on_set_position:
                seconds = position / 1_000_000.0
                self.on_set_position(track_id, seconds)
        except Exception as e:
            logger.error(
                "MPRIS2: Error handling SetPosition request: %s", e, exc_info=True
            )

    @dbus.service.method(MPRIS2_PLAYER_INTERFACE, in_signature="s", out_signature="")
    def OpenUri(self, uri: str):
        """Open a URI for playback."""
        try:
            logger.info("MPRIS2: OpenUri requested: %s", uri)
            # Convert file:// URI to path
            if uri.startswith("file://"):
                file_path = uri[7:]  # Remove 'file://' prefix
                # Security: Validate path
                validated_path = SecurityValidator.validate_path(file_path)
                if validated_path and SecurityValidator.validate_file_extension(
                    str(validated_path)
                ):
                    if hasattr(self, "on_open_uri"):
                        self.on_open_uri(str(validated_path))
                else:
                    logger.warning("MPRIS2: Invalid or unsafe URI: %s", uri)
                    raise dbus.exceptions.DBusException(
                        "org.mpris.MediaPlayer2.Error.InvalidUri",
                        f"Invalid or unsafe URI: {uri}",
                    )
            else:
                logger.warning("MPRIS2: Unsupported URI scheme: %s", uri)
                raise dbus.exceptions.DBusException(
                    "org.mpris.MediaPlayer2.Error.UnsupportedUriScheme",
                    f"Unsupported URI scheme: {uri}",
                )
        except dbus.exceptions.DBusException:
            raise
        except Exception as e:
            logger.error("MPRIS2: Error handling OpenUri request: %s", e, exc_info=True)
            raise dbus.exceptions.DBusException(
                "org.mpris.MediaPlayer2.Error.Failed", f"Error opening URI: {e}"
            )

    @dbus.service.signal(MPRIS2_PLAYER_INTERFACE, signature="x")
    def Seeked(self, position: int):
        """Signal emitted when position changes via SetPosition."""
        pass

    # Property accessors for internal use (not DBus methods)
    @property
    def playback_status(self) -> str:
        """Current playback status: Playing, Paused, Stopped."""
        return self._playback_status

    @playback_status.setter
    def playback_status(self, value: str):
        """Set playback status and emit PropertiesChanged signal."""
        if self._playback_status != value:
            self._playback_status = value
            self.PropertiesChanged(
                MPRIS2_PLAYER_INTERFACE, {"PlaybackStatus": dbus.String(value)}, []
            )

    @property
    def metadata(self) -> Dict[str, Any]:
        """Current track metadata."""
        return self._metadata

    @metadata.setter
    def metadata(self, value: Dict[str, Any]):
        """Set metadata and emit PropertiesChanged signal."""
        if self._metadata != value:
            self._metadata = value
            # PropertiesChanged signature is 'sa{sv}as'
            # The changed dict (a{sv}) maps property names to Variants
            # D-Bus library automatically wraps values in Variants, so we just need proper D-Bus types
            try:
                # Convert metadata dict to proper D-Bus format
                # Each value should be a proper D-Bus type (dbus.String, dbus.Array, etc.)
                dbus_metadata = {}
                for key, val in value.items():
                    if isinstance(val, dbus.ObjectPath):
                        # ObjectPath is already a D-Bus type
                        dbus_metadata[key] = val
                    elif isinstance(val, list):
                        # Array of strings - convert to dbus.Array
                        dbus_metadata[key] = dbus.Array(
                            [dbus.String(str(v)) for v in val], signature="s"
                        )
                    elif isinstance(val, (int, float)):
                        # Numbers - use appropriate D-Bus numeric types
                        if key == "mpris:length":
                            dbus_metadata[key] = dbus.Int64(int(val))
                        elif key == "xesam:trackNumber":
                            dbus_metadata[key] = dbus.Int32(int(val))
                        else:
                            # Other numbers - let D-Bus convert automatically
                            dbus_metadata[key] = val
                    elif isinstance(val, str):
                        # Strings - convert to dbus.String
                        dbus_metadata[key] = dbus.String(val)
                    else:
                        # Other types - convert to string as fallback
                        dbus_metadata[key] = dbus.String(str(val))

                # PropertiesChanged automatically wraps values in Variants
                # Use dbus.Dictionary to ensure proper D-Bus dict type
                dbus_dict = dbus.Dictionary(dbus_metadata, signature="sv")
                changed_props = {"Metadata": dbus_dict}
                self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, changed_props, [])
            except Exception as e:
                logger.error(
                    "MPRIS2: Error emitting PropertiesChanged for Metadata: %s",
                    e,
                    exc_info=True,
                )
                # Fallback: try with minimal conversion (let D-Bus handle more automatically)
                try:
                    # Convert to basic D-Bus types without full conversion
                    fallback_metadata = {}
                    for key, val in value.items():
                        if isinstance(val, dbus.ObjectPath):
                            fallback_metadata[key] = val
                        elif isinstance(val, list):
                            # Convert list to dbus.Array
                            fallback_metadata[key] = dbus.Array(
                                [dbus.String(str(v)) for v in val], signature="s"
                            )
                        elif isinstance(val, (int, float)):
                            if key == "mpris:length":
                                fallback_metadata[key] = dbus.Int64(int(val))
                            else:
                                fallback_metadata[key] = val
                        else:
                            fallback_metadata[key] = dbus.String(str(val))

                    # Use dbus.Dictionary for fallback as well
                    fallback_dict = dbus.Dictionary(fallback_metadata, signature="sv")
                    changed_props = {"Metadata": fallback_dict}
                    self.PropertiesChanged(MPRIS2_PLAYER_INTERFACE, changed_props, [])
                except Exception as e2:
                    logger.error(
                        "MPRIS2: Fallback PropertiesChanged also failed: %s",
                        e2,
                        exc_info=True,
                    )

    @property
    def volume(self) -> float:
        """Volume (0.0 to 1.0)."""
        return self._volume

    @volume.setter
    def volume(self, value: float):
        """Set volume and emit PropertiesChanged signal."""
        if abs(self._volume - value) > 0.01:
            self._volume = max(0.0, min(1.0, value))
            self.PropertiesChanged(
                MPRIS2_PLAYER_INTERFACE, {"Volume": dbus.Double(self._volume)}, []
            )
            if self.on_set_volume:
                self.on_set_volume(self._volume)

    @property
    def position(self) -> int:
        """Current position in microseconds."""
        return int(self._position * 1_000_000)

    @position.setter
    def position(self, value: float):
        """Set position in seconds (internal use)."""
        self._position = value

    @property
    def can_go_next(self) -> bool:
        """Whether Next() is available."""
        return self._can_go_next

    @can_go_next.setter
    def can_go_next(self, value: bool):
        """Set CanGoNext and emit PropertiesChanged signal."""
        if self._can_go_next != value:
            self._can_go_next = value
            self.PropertiesChanged(
                MPRIS2_PLAYER_INTERFACE, {"CanGoNext": dbus.Boolean(value)}, []
            )

    @property
    def can_go_previous(self) -> bool:
        """Whether Previous() is available."""
        return self._can_go_previous

    @can_go_previous.setter
    def can_go_previous(self, value: bool):
        """Set CanGoPrevious and emit PropertiesChanged signal."""
        if self._can_go_previous != value:
            self._can_go_previous = value
            self.PropertiesChanged(
                MPRIS2_PLAYER_INTERFACE, {"CanGoPrevious": dbus.Boolean(value)}, []
            )

    def update_metadata(self, track: Optional[TrackMetadata]):
        """Update metadata from track."""
        if not track:
            self.metadata = {}
            return

        # Build MPRIS2 metadata dict
        # All values must be proper D-Bus types (strings, not None)
        metadata = {}

        # Track ID (required) - ensure file_path exists
        if not track.file_path:
            logger.warning("Track has no file_path, cannot create MPRIS2 metadata")
            self.metadata = {}
            return

        track_id = f"/org/mpris/MediaPlayer2/Track/{hash(track.file_path) & 0xFFFFFFFF}"
        metadata["mpris:trackid"] = dbus.ObjectPath(track_id)

        # File path as URI (required) - use native Python string
        try:
            file_path = Path(track.file_path).resolve()
            metadata["xesam:url"] = f"file://{file_path}"
        except (OSError, ValueError) as e:
            logger.warning("Failed to resolve file path for MPRIS2: %s", e)
            metadata["xesam:url"] = f"file://{track.file_path}"

        # Title - ensure it's a non-empty string (native Python string)
        if track.title:
            title = str(track.title).strip()
        else:
            try:
                file_path = Path(track.file_path).resolve()
                title = file_path.stem
            except (OSError, ValueError):
                title = "Unknown"

        if not title:
            title = "Unknown"
        metadata["xesam:title"] = title

        # Artist - must be array of strings (native Python list)
        artists = []
        if track.artist:
            artist_str = str(track.artist).strip()
            if artist_str:
                artists.append(artist_str)
        if track.album_artist and track.album_artist != track.artist:
            album_artist_str = str(track.album_artist).strip()
            if album_artist_str and album_artist_str not in artists:
                artists.append(album_artist_str)
        if artists:
            metadata["xesam:artist"] = artists  # Native Python list

        # Album - ensure it's a non-empty string (native Python string)
        if track.album:
            album_str = str(track.album).strip()
            if album_str:
                metadata["xesam:album"] = album_str

        # Duration in microseconds (native Python int)
        if track.duration and track.duration > 0:
            metadata["mpris:length"] = int(track.duration * 1_000_000)

        # Track number (native Python int)
        if track.track_number and track.track_number > 0:
            metadata["xesam:trackNumber"] = int(track.track_number)

        # Art URL - ensure it's a string and file exists (native Python string)
        if track.album_art_path:
            try:
                art_path = Path(track.album_art_path).resolve()
                if art_path.exists():
                    metadata["mpris:artUrl"] = f"file://{art_path}"
            except (OSError, ValueError):
                # Skip invalid art path
                pass

        self.metadata = metadata

    def update_position(self, position: float):
        """Update playback position in seconds."""
        self._position = position

    def update_playback_status(self, is_playing: bool, is_paused: bool = False):
        """Update playback status."""
        if is_playing:
            status = "Playing"
        elif is_paused:
            status = "Paused"
        else:
            status = "Stopped"
        self.playback_status = status


class MPRIS2Manager:
    """
    Manager for MPRIS2 D-Bus interfaces.

    Handles registration of MPRIS2 service on the session bus and manages
    the combined root and player interfaces for desktop integration.
    """

    def __init__(self):
        """Initialize MPRIS2 manager."""
        # DBusGMainLoop should be set once globally, but calling multiple times is safe
        try:
            DBusGMainLoop(set_as_default=True)
        except RuntimeError:
            # Already set, ignore
            pass

        self.bus = dbus.SessionBus()
        self.service: Optional[MPRIS2Service] = None
        self._name_id: Optional[int] = None
        self._initialized = False

        # Store callbacks for when service is ready
        self._playback_callbacks: Dict[str, Optional[callable]] = {}
        self._window_callbacks: Dict[str, Optional[callable]] = {}

        # D-Bus connection monitoring
        self._dbus_monitor = DBusConnectionMonitor(self.bus)

        # Request bus name with proper error handling (non-blocking)
        self._register_service()

    def _register_service(self):
        """Register MPRIS2 service on the session bus."""

        def _do_register():
            try:
                # Use non-blocking request with timeout
                self._name_id = self.bus.request_name(
                    MPRIS2_BUS_NAME,
                    dbus.bus.NAME_FLAG_REPLACE_EXISTING
                    | dbus.bus.NAME_FLAG_DO_NOT_QUEUE,
                )
                if self._name_id == dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER:
                    logger.info("MPRIS2: Acquired bus name %s", MPRIS2_BUS_NAME)
                    self._setup_interfaces()
                    self._initialized = True
                    return True
                else:
                    logger.warning(
                        "MPRIS2: Could not acquire bus name (may already be in use)"
                    )
                    self._initialized = False
                    return False
            except dbus.exceptions.DBusException as e:
                error_name = (
                    e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
                )
                logger.error("MPRIS2: D-Bus error registering service: %s", error_name)
                self._initialized = False
                return False
            except Exception as e:
                logger.error("MPRIS2: Failed to register service: %s", e, exc_info=True)
                self._initialized = False
                return False

        # Use safe call wrapper for registration (non-blocking)
        try:
            dbus_safe_call(_do_register, default_return=False, log_errors=True)
        except Exception as e:
            logger.error(
                "MPRIS2: Exception during service registration: %s", e, exc_info=True
            )
            self._initialized = False

    def _setup_interfaces(self):
        """
        Set up MPRIS2 interfaces.

        Creates a single service object that implements both root and player interfaces
        on the same object path, as required by the MPRIS2 specification.
        """
        try:
            # Create combined service (implements both root and player interfaces)
            self.service = MPRIS2Service(self.bus, MPRIS2_OBJECT_PATH)

            # Apply stored callbacks if any
            if self._playback_callbacks:
                self.service.on_play = self._playback_callbacks.get("on_play")
                self.service.on_pause = self._playback_callbacks.get("on_pause")
                self.service.on_stop = self._playback_callbacks.get("on_stop")
                self.service.on_next = self._playback_callbacks.get("on_next")
                self.service.on_previous = self._playback_callbacks.get("on_previous")
                self.service.on_seek = self._playback_callbacks.get("on_seek")
                self.service.on_set_position = self._playback_callbacks.get(
                    "on_set_position"
                )
                self.service.on_set_volume = self._playback_callbacks.get(
                    "on_set_volume"
                )

            if self._window_callbacks:
                self.service.on_quit = self._window_callbacks.get("on_quit")
                self.service.on_raise = self._window_callbacks.get("on_raise")

            logger.info(
                "MPRIS2: Service registered successfully on %s", MPRIS2_OBJECT_PATH
            )
        except dbus.exceptions.DBusException as e:
            error_name = e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
            logger.error("MPRIS2: D-Bus error setting up interfaces: %s", error_name)
            # Check connection health
            if not self._dbus_monitor.check_connection():
                logger.error("MPRIS2: D-Bus connection appears to be lost")
        except Exception as e:
            logger.error("MPRIS2: Failed to set up interfaces: %s", e, exc_info=True)

    def set_playback_callbacks(
        self,
        on_play=None,
        on_pause=None,
        on_stop=None,
        on_next=None,
        on_previous=None,
        on_seek=None,
        on_set_position=None,
        on_set_volume=None,
    ):
        """Set playback control callbacks."""
        # Store callbacks for when service is ready
        self._playback_callbacks = {
            "on_play": on_play,
            "on_pause": on_pause,
            "on_stop": on_stop,
            "on_next": on_next,
            "on_previous": on_previous,
            "on_seek": on_seek,
            "on_set_position": on_set_position,
            "on_set_volume": on_set_volume,
        }

        # Apply to service if it's ready
        if self.service:
            self.service.on_play = on_play
            self.service.on_pause = on_pause
            self.service.on_stop = on_stop
            self.service.on_next = on_next
            self.service.on_previous = on_previous
            self.service.on_seek = on_seek
            self.service.on_set_position = on_set_position
            self.service.on_set_volume = on_set_volume

    def set_window_callbacks(self, on_quit=None, on_raise=None):
        """Set window control callbacks."""
        # Store callbacks for when service is ready
        self._window_callbacks = {
            "on_quit": on_quit,
            "on_raise": on_raise,
        }

        # Apply to service if it's ready
        if self.service:
            self.service.on_quit = on_quit
            self.service.on_raise = on_raise

    def update_metadata(self, track: Optional[TrackMetadata]):
        """Update current track metadata."""
        if self.service:
            self.service.update_metadata(track)

    def update_position(self, position: float):
        """Update playback position."""
        if self.service:
            self.service.update_position(position)

    def update_playback_status(self, is_playing: bool, is_paused: bool = False):
        """Update playback status."""
        if self.service:
            self.service.update_playback_status(is_playing, is_paused)

    def update_volume(self, volume: float):
        """Update volume."""
        if self.service:
            self.service.volume = volume

    def update_can_go_next(self, can_go: bool):
        """Update whether Next() is available."""
        if self.service:
            self.service.can_go_next = can_go

    def update_can_go_previous(self, can_go: bool):
        """Update whether Previous() is available."""
        if self.service:
            self.service.can_go_previous = can_go

    def cleanup(self):
        """Clean up MPRIS2 resources."""

        def _do_cleanup():
            try:
                if self._name_id:
                    self.bus.release_name(MPRIS2_BUS_NAME)
                logger.info("MPRIS2: Cleaned up")
                return True
            except dbus.exceptions.DBusException as e:
                error_name = (
                    e.get_dbus_name() if hasattr(e, "get_dbus_name") else str(e)
                )
                logger.debug("MPRIS2: D-Bus error during cleanup: %s", error_name)
                return False
            except Exception as e:
                logger.error("MPRIS2: Error during cleanup: %s", e, exc_info=True)
                return False

        # Use safe call wrapper for cleanup
        dbus_safe_call(_do_cleanup, default_return=False, log_errors=False)
