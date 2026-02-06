"""Custom exception hierarchy for the music player."""


class MusicPlayerError(Exception):
    pass


class PlayerError(MusicPlayerError):
    pass


class MOCError(MusicPlayerError):
    pass


class PlaylistError(MusicPlayerError):
    pass


class ConfigurationError(MusicPlayerError):
    pass


class MetadataError(MusicPlayerError):
    pass


class BluetoothError(MusicPlayerError):
    pass


class SecurityError(MusicPlayerError):
    pass
