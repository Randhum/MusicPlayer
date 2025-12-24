"""MOC (Music On Console) synchronization helper.

This module handles synchronization between the application's internal playlist
and MOC's playlist, managing state, position tracking, and playback coordination.
"""

from pathlib import Path
from typing import Optional, Callable, List

import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib

from core.metadata import TrackMetadata
from core.moc_controller import MocController, MOC_PLAYLIST_PATH


class MocSyncHelper:
    """
    Helper class for managing MOC synchronization.
    
    Handles:
    - Playlist synchronization between app and MOC
    - Position and state tracking
    - End-of-track detection
    - External playlist change detection
    """
    
    def __init__(self, moc_controller: MocController, 
                 playlist_manager,
                 player_controls,
                 metadata_panel,
                 playlist_view,
                 is_video_track_fn: Callable[[Optional[TrackMetadata]], bool]):
        """
        Initialize MOC sync helper.
        
        Args:
            moc_controller: MocController instance
            playlist_manager: PlaylistManager instance
            player_controls: PlayerControls instance
            metadata_panel: MetadataPanel instance
            playlist_view: PlaylistView instance
            is_video_track_fn: Function to check if track is video
        """
        self.moc_controller = moc_controller
        self.playlist_manager = playlist_manager
        self.player_controls = player_controls
        self.metadata_panel = metadata_panel
        self.playlist_view = playlist_view
        self.is_video_track = is_video_track_fn
        
        self.use_moc = moc_controller.is_available()
        
        # State tracking
        self.last_position: float = 0.0
        self.last_duration: float = 0.0
        self.last_file: Optional[str] = None
        self.playlist_mtime: float = 0.0
        self.sync_enabled: bool = True
        self.end_detected: bool = False
        
        # Callbacks
        self.on_track_finished: Optional[Callable] = None
        self.on_shuffle_changed: Optional[Callable[[bool], None]] = None
        
        # Initialize playlist mtime if file exists
        if self.use_moc and MOC_PLAYLIST_PATH.exists():
            try:
                self.playlist_mtime = MOC_PLAYLIST_PATH.stat().st_mtime
            except OSError:
                self.playlist_mtime = 0.0
    
    def should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Check if MOC should be used for this track."""
        return self.use_moc and not self.is_video_track(track)
    
    def initialize(self):
        """Initialize MOC server and settings."""
        if not self.use_moc:
            return False
        
        if self.moc_controller.ensure_server():
            self.moc_controller.enable_autonext()
            self.sync_shuffle_from_moc()
            return True
        return False
    
    def sync_shuffle_from_moc(self):
        """Sync shuffle state from MOC to UI."""
        if not self.use_moc:
            return
        
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None and self.on_shuffle_changed:
            self.on_shuffle_changed(moc_shuffle)
    
    def sync_playlist_to_moc(self, start_playback: bool = False):
        """Sync current playlist to MOC."""
        if not self.use_moc or not self.sync_enabled:
            return
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if not tracks:
            self.moc_controller.set_playlist([], -1, start_playback=False)
            return
        
        track = self.playlist_manager.get_current_track()
        if track and self.should_use_moc(track) and start_playback:
            # Using MOC for playback - sync playlist and start playing
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            # Not using MOC for current track - just sync playlist
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
    
    def sync_playlist_for_playback(self):
        """Sync playlist to MOC when starting playback."""
        if not self.use_moc or not self.sync_enabled:
            return
        
        # Check if MOC is playing independently
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            current_track = self.playlist_manager.get_current_track()
            
            if moc_state == "PLAY" and moc_file and current_track:
                if moc_file != current_track.file_path:
                    # MOC is playing independently - don't sync
                    self.sync_enabled = False
                    return
        
        # Sync playlist and start playback
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if not tracks:
            self.moc_controller.set_playlist([], -1, start_playback=False)
            return
        
        track = self.playlist_manager.get_current_track()
        if track and self.should_use_moc(track):
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
        
        # Always ensure autonext is enabled so tracks advance automatically
        self.moc_controller.enable_autonext()
        
        # Sync shuffle state
        # Note: shuffle state is managed by main_window, not here
    
    def load_playlist_from_moc(self):
        """Load playlist from MOC's playlist file."""
        if not self.use_moc:
            return
        
        tracks, current_index = self.moc_controller.get_playlist()
        
        if tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(tracks)
            if current_index >= 0:
                self.playlist_manager.set_current_index(current_index)
            self.playlist_view.set_playlist(tracks, current_index)
        elif not tracks:
            # Check if MOC is playing something - if so, it has a playlist in memory
            status = self.moc_controller.get_status()
            if status and status.get("state") in ("PLAY", "PAUSE") and status.get("file_path"):
                # MOC is playing but we can't read the playlist file
                # Don't clear - MOC has tracks in memory that aren't saved yet
                pass
    
    def update_status(self) -> bool:
        """
        Update status from MOC and sync UI.
        
        Returns True to continue polling, False to stop.
        """
        if not self.use_moc:
            return False
        
        status = self.moc_controller.get_status()
        if not status:
            return True  # Try again later
        
        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))
        
        # Cache position and duration
        self.last_position = position
        self.last_duration = duration
        
        # Update UI state if we're using MOC for current track
        track = self.playlist_manager.get_current_track()
        if track and self.should_use_moc(track):
            # Update playback state
            self.player_controls.set_playing(state == "PLAY")
            
            # Update position display
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
            
            # Detect track change (MOC auto-advancement when track finishes)
            # MOC handles autonext automatically, so we detect when the file_path changes
            # This is the primary mechanism for track advancement
            if file_path and file_path != self.last_file:
                # Track changed - MOC has advanced to next track
                self.last_file = file_path
                self.end_detected = False
                
                # Update metadata and playlist
                new_track = TrackMetadata(file_path)
                self.metadata_panel.set_track(new_track)
                
                # Find and select this track in our playlist
                playlist = self.playlist_manager.get_playlist()
                found_in_playlist = False
                for idx, t in enumerate(playlist):
                    if t.file_path == file_path:
                        self.playlist_manager.set_current_index(idx)
                        self.playlist_view.set_playlist(playlist, idx)
                        found_in_playlist = True
                        break
                
                # If track not found in playlist, it means MOC advanced to a track
                # that's not in our current playlist - notify callback to handle it
                if not found_in_playlist and self.on_track_finished:
                    self.on_track_finished()
            
            # Fallback: Detect if track reached the end and MOC stopped unexpectedly
            # Only check this if we're still on the same file (no track change detected)
            # and MOC stopped but there's a next track available
            if duration > 0 and state == "STOP" and file_path == self.last_file:
                playlist = self.playlist_manager.get_playlist()
                current_index = self.playlist_manager.get_current_index()
                # Check if position is at or near the end (within 1 second)
                if position >= duration - 1.0 and current_index < len(playlist) - 1:
                    # Track finished and MOC stopped, but there's a next track
                    # This shouldn't happen if autonext is working, but handle it anyway
                    if self.on_track_finished:
                        self.on_track_finished()
        else:
            # Detect if MOC is playing independently (not synced from our app)
            if file_path and state == "PLAY":
                current_track = self.playlist_manager.get_current_track()
                if not current_track or file_path != current_track.file_path:
                    # MOC is playing independently - disable sync
                    if self.sync_enabled:
                        self.sync_enabled = False
                        self.last_file = file_path
                        # Update UI to reflect MOC's independent playback
                        track = TrackMetadata(file_path)
                        self.metadata_panel.set_track(track)
                        # Try to find and select this track in our playlist
                        playlist = self.playlist_manager.get_playlist()
                        for idx, t in enumerate(playlist):
                            if t.file_path == file_path:
                                self.playlist_manager.set_current_index(idx)
                                self.playlist_view.set_playlist(playlist, idx)
                                break
            elif state == "STOP":
                # Both are stopped - re-enable sync for next playback
                if not self.sync_enabled:
                    self.sync_enabled = True
        
        # Sync shuffle state from MOC if user changes it externally
        moc_shuffle = status.get("shuffle", False)
        # Note: shuffle sync is handled by main_window
        
        # Detect external playlist changes (e.g. from MOC UI) by watching the M3U file
        try:
            mtime = MOC_PLAYLIST_PATH.stat().st_mtime
        except OSError:
            mtime = self.playlist_mtime
        
        if mtime != self.playlist_mtime:
            self.playlist_mtime = mtime
            # Only reload if MOC sync is disabled (MOC is playing independently)
            if not self.sync_enabled:
                self.load_playlist_from_moc()
        
        return True
    
    def reset_end_detection(self):
        """Reset end-of-track detection flag."""
        self.end_detected = False
    
    def get_cached_duration(self) -> float:
        """Get cached duration if available."""
        if self.last_duration > 0:
            return self.last_duration
        # Fallback to status call if cache not available
        status = self.moc_controller.get_status(force_refresh=False)
        if status:
            return float(status.get("duration", 0.0))
        return 0.0
    
    def get_cached_position(self) -> float:
        """Get cached position if available."""
        return self.last_position

