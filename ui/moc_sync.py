"""MOC (Music On Console) synchronization helper.

This module handles synchronization between the application's internal playlist
and MOC's playlist, managing state, position tracking, and playback coordination.
"""

from pathlib import Path
from typing import Optional, Callable, List
import json
import random
import time

import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib

from core.metadata import TrackMetadata
from core.config import get_config
from core.moc_controller import MocController
from core.logging import get_logger

logger = get_logger(__name__)


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
                 is_video_track_fn: Callable[[Optional[TrackMetadata]], bool],
                 mpris2=None):
        """
        Initialize MOC sync helper.
        
        Args:
            moc_controller: MocController instance
            playlist_manager: PlaylistManager instance
            player_controls: PlayerControls instance
            metadata_panel: MetadataPanel instance
            playlist_view: PlaylistView instance
            is_video_track_fn: Function to check if track is video
            mpris2: Optional MPRIS2Manager instance for desktop integration
        """
        self.moc_controller = moc_controller
        self.playlist_manager = playlist_manager
        self.player_controls = player_controls
        self.metadata_panel = metadata_panel
        self.playlist_view = playlist_view
        self.is_video_track = is_video_track_fn
        self.mpris2 = mpris2
        
        self.use_moc = moc_controller.is_available()
        
        # State tracking
        self.last_position: float = 0.0
        self.last_duration: float = 0.0
        self.last_file: Optional[str] = None
        self.playlist_mtime: float = 0.0
        self.sync_enabled: bool = True
        self.end_detected: bool = False
        
        # Shuffle tracking - track which songs have been played in shuffle mode
        self.played_tracks_in_shuffle: set[str] = set()
        self.shuffle_enabled: bool = False
        self._shuffle_set_pending: bool = False  # Flag to prevent update_status from overwriting our shuffle state
        self._shuffle_set_pending_count: int = 0  # Counter to keep flag active for multiple update cycles
        
        # Callbacks
        self.on_track_finished: Optional[Callable] = None
        self.on_shuffle_changed: Optional[Callable[[bool], None]] = None
        
        # Debouncing for sync operations to prevent rapid-fire syncs
        self._sync_timeout_id: Optional[int] = None
        self._sync_pending: bool = False
        self._sync_start_playback: bool = False
        
        # Initialize playlist mtime if file exists
        config = get_config()
        moc_playlist_path = config.moc_playlist_path
        if self.use_moc and moc_playlist_path.exists():
            try:
                self.playlist_mtime = moc_playlist_path.stat().st_mtime
            except OSError:
                self.playlist_mtime = 0.0
    
    def should_use_moc(self, track: Optional[TrackMetadata]) -> bool:
        """Check if MOC should be used for this track."""
        return self.use_moc and not self.is_video_track(track)
    
    def initialize(self):
        """Initialize MOC server and settings.
        
        If MOC is already running, loads its current state but then
        maintains the app as orchestrator by syncing our playlist to MOC.
        """
        if not self.use_moc:
            return False
        
        success, was_already_running = self.moc_controller.ensure_server()
        if not success:
            return False
        
        # If MOC was already running, detect and load its current state
        if was_already_running:
            logger.info("MOC server was already running - detecting current state")
            # Load playlist and state from running MOC
            self._load_state_from_running_moc()
        
        # Always ensure autonext is enabled and sync shuffle state
        self.moc_controller.enable_autonext()
        self.sync_shuffle_from_moc()
        
        # Sync our playlist to MOC to take control (app remains orchestrator)
        # This ensures that even if MOC had a playlist, we sync ours to it
        # Only sync if we have a playlist (either loaded from MOC or already in app)
        tracks = self.playlist_manager.get_playlist()
        if tracks:
            current_index = self.playlist_manager.get_current_index()
            # Sync playlist to MOC but don't start playback - app controls playback
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
            logger.info("Synced %d tracks to MOC - app is now orchestrator", len(tracks))
        
        return True
    
    def _load_state_from_running_moc(self):
        """Load current state from a running MOC instance."""
        # Get current status
        status = self.moc_controller.get_status(force_refresh=True)
        if not status:
            return
        
        # Get current file from status to pass to get_playlist (avoids redundant status call)
        current_file = status.get("file_path")
        
        # Load playlist from MOC (pass current_file to avoid redundant status call)
        moc_tracks, moc_index = self.moc_controller.get_playlist(current_file=current_file)
        
        # If MOC has a playlist, load it into our app
        if moc_tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(moc_tracks)
            if moc_index >= 0:
                self.playlist_manager.set_current_index(moc_index)
            self.playlist_view.set_playlist(moc_tracks, moc_index)
            logger.info("Loaded %d tracks from running MOC instance", len(moc_tracks))
        
        # Update playback state
        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        
        if file_path:
            self.last_file = file_path
            # Update metadata
            track = TrackMetadata(file_path)
            self.metadata_panel.set_track(track)
        
        # Update UI playback state
        if state == "PLAY":
            self.player_controls.set_playing(True)
        elif state == "PAUSE":
            self.player_controls.set_playing(False)
        
        # Update position if available
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))
        if duration > 0:
            self.player_controls.update_progress(position, duration)
        
        # Sync shuffle state
        self.sync_shuffle_from_moc()
        
        logger.info("Loaded state from running MOC: %s, track: %s", state, file_path)
    
    def sync_shuffle_from_moc(self):
        """Sync shuffle state from MOC to UI."""
        if not self.use_moc:
            return
        
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None:
            self.shuffle_enabled = moc_shuffle
            # Reset played tracks when shuffle state changes
            if not moc_shuffle:
                self.played_tracks_in_shuffle.clear()
            if self.on_shuffle_changed:
                self.on_shuffle_changed(moc_shuffle)
    
    def set_shuffle_enabled(self, enabled: bool):
        """Set shuffle state and reset played tracks tracking."""
        self.shuffle_enabled = enabled
        if not enabled:
            # Clear played tracks when shuffle is disabled
            self.played_tracks_in_shuffle.clear()
        else:
            # When shuffle is enabled, mark current track as played if it exists
            current_track = self.playlist_manager.get_current_track()
            if current_track and current_track.file_path:
                self.played_tracks_in_shuffle.add(current_track.file_path)
    
    def sync_playlist_to_moc(self, start_playback: bool = False):
        """Sync current playlist to MOC with debouncing to prevent rapid-fire syncs."""
        if not self.use_moc or not self.sync_enabled:
            return
        
        # Cancel any pending sync
        if self._sync_timeout_id is not None:
            GLib.source_remove(self._sync_timeout_id)
            self._sync_timeout_id = None
        
        # Update pending sync parameters
        self._sync_pending = True
        self._sync_start_playback = start_playback or self._sync_start_playback
        
        # Schedule sync after a short delay (debounce)
        # This prevents multiple rapid syncs when adding many tracks
        self._sync_timeout_id = GLib.timeout_add(300, self._do_sync_playlist_to_moc)  # 300ms debounce
    
    def _do_sync_playlist_to_moc(self):
        """Actually perform the sync (called after debounce delay)."""
        self._sync_timeout_id = None
        
        if not self._sync_pending:
            return False
        
        self._sync_pending = False
        start_playback = self._sync_start_playback
        self._sync_start_playback = False
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if not tracks:
            self.moc_controller.set_playlist([], -1, start_playback=False)
            return False
        
        track = self.playlist_manager.get_current_track()
        if track and self.should_use_moc(track) and start_playback:
            # Using MOC for playback - sync playlist and start playing
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            # Not using MOC for current track - just sync playlist
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
        
        return False  # Don't repeat
    
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
        
        # Load playlist from MOC
        tracks, current_index = self.moc_controller.get_playlist()
        
        if tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(tracks)
            if current_index >= 0:
                self.playlist_manager.set_current_index(current_index)
            self.playlist_view.set_playlist(tracks, current_index)
            # Reset shuffle tracking when loading a new playlist
            self.reset_shuffle_tracking()
            
            # Load full metadata asynchronously in background
            # This prevents blocking the UI
            GLib.idle_add(self._load_metadata_async, 0)
        elif not tracks:
            # Check if MOC is playing something - if so, it has a playlist in memory
            status = self.moc_controller.get_status()
            if status and status.get("state") in ("PLAY", "PAUSE") and status.get("file_path"):
                # MOC is playing but we can't read the playlist file
                # Don't clear - MOC has tracks in memory that aren't saved yet
                pass
    
    def _load_metadata_async(self, start_index: int = 0) -> bool:
        """Load full metadata for tracks asynchronously (non-blocking)."""
        tracks = self.playlist_manager.get_playlist()
        if not tracks:
            return False
        
        # Process a batch of tracks (10 at a time) to keep UI responsive
        batch_size = 10
        end_index = min(start_index + batch_size, len(tracks))
        
        for i in range(start_index, end_index):
            track = tracks[i]
            if not track or not track.file_path:
                continue
            
            # Only load metadata if we don't have it yet (title is just filename)
            if not track.title or track.title == Path(track.file_path).stem:
                try:
                    full_metadata = TrackMetadata(track.file_path)
                    # Update track with full metadata
                    track.title = full_metadata.title
                    track.artist = full_metadata.artist
                    track.album = full_metadata.album
                    track.album_artist = full_metadata.album_artist
                    track.track_number = full_metadata.track_number
                    track.duration = full_metadata.duration
                    track.album_art_path = full_metadata.album_art_path
                    track.genre = full_metadata.genre
                    track.year = full_metadata.year
                except Exception as e:
                    logger.debug("Error loading metadata for %s: %s", track.file_path, e)
        
        # Update playlist view with what we have so far
        self.playlist_view.set_playlist(tracks, self.playlist_manager.get_current_index())
        
        # If there are more tracks to process, schedule continuation
        if end_index < len(tracks):
            GLib.idle_add(self._load_metadata_async, end_index)
            return False
        
        # All metadata loaded
        return False  # Don't repeat
    
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
            
            # Update MPRIS2 playback status
            if self.mpris2:
                is_playing = state == "PLAY"
                is_paused = state == "PAUSE"
                self.mpris2.update_playback_status(is_playing, is_paused=is_paused)
            
            # Update position display
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
            
            # Detect track change (MOC auto-advancement when track finishes or external change)
            # MOC handles autonext automatically, so we detect when the file_path changes
            # This is the primary mechanism for track advancement
            if file_path and file_path != self.last_file:
                # Track changed - MOC has advanced to next track or changed externally (e.g., via mocp next button)
                # Mark the previous track as played if shuffle is enabled
                if self.shuffle_enabled and self.last_file:
                    self.played_tracks_in_shuffle.add(self.last_file)
                
                self.last_file = file_path
                self.end_detected = False
                
                # When track changes (especially from external mocp commands), reload full playlist from MOC
                # This ensures we're in sync with MOC's current state
                # Pass current_file to avoid redundant status call
                moc_tracks, moc_index = self.moc_controller.get_playlist(current_file=file_path)
                if moc_tracks:
                    # MOC has a playlist - sync it to our app
                    self.playlist_manager.clear()
                    self.playlist_manager.add_tracks(moc_tracks)
                    # Find the current track in the loaded playlist
                    found_index = -1
                    for idx, t in enumerate(moc_tracks):
                        if t.file_path == file_path:
                            found_index = idx
                            break
                    if found_index >= 0:
                        self.playlist_manager.set_current_index(found_index)
                        self.playlist_view.set_playlist(moc_tracks, found_index)
                    else:
                        # Track not in playlist - use MOC's reported index
                        if moc_index >= 0:
                            self.playlist_manager.set_current_index(moc_index)
                            self.playlist_view.set_playlist(moc_tracks, moc_index)
                        else:
                            self.playlist_view.set_playlist(moc_tracks, -1)
                    
                    # Update metadata
                    new_track = TrackMetadata(file_path)
                    self.metadata_panel.set_track(new_track)
                    # Update MPRIS2 metadata
                    if self.mpris2:
                        self.mpris2.update_metadata(new_track)
                else:
                    # MOC is playing but playlist file not available - use status only
                    new_track = TrackMetadata(file_path)
                    self.metadata_panel.set_track(new_track)
                    # Update MPRIS2 metadata
                    if self.mpris2:
                        self.mpris2.update_metadata(new_track)
                    
                    # Try to find in current playlist
                    playlist = self.playlist_manager.get_playlist()
                    found_in_playlist = False
                    for idx, t in enumerate(playlist):
                        if t.file_path == file_path:
                            self.playlist_manager.set_current_index(idx)
                            self.playlist_view.set_playlist(playlist, idx)
                            found_in_playlist = True
                            break
                    
                    # If track not found in playlist, notify callback
                    if not found_in_playlist and self.on_track_finished:
                        self.on_track_finished()
            
            # Detect if track reached the end (position >= duration)
            # This handles cases where MOC doesn't auto-advance or stops at the end
            playlist = self.playlist_manager.get_playlist()
            current_index = self.playlist_manager.get_current_index()
            
            if duration > 0 and file_path == self.last_file and not self.end_detected:
                # Check if we've reached the end of the track
                # Use a small threshold (0.5 seconds) to account for timing differences
                if position >= duration - 0.5:
                    # Track has finished
                    self.end_detected = True
                    
                    # Mark current track as played if shuffle is enabled
                    if self.shuffle_enabled and file_path:
                        self.played_tracks_in_shuffle.add(file_path)
                    
                    # Check if there are more tracks to play
                    # In shuffle mode, check if all tracks have been played
                    # In sequential mode, check if there's a next track
                    has_more_tracks = False
                    if self.shuffle_enabled:
                        # In shuffle mode, check if all tracks have been played
                        playlist_file_paths = {t.file_path for t in playlist if t.file_path}
                        unplayed_tracks = playlist_file_paths - self.played_tracks_in_shuffle
                        has_more_tracks = len(unplayed_tracks) > 0
                        
                        # If all tracks have been played, reset and start over
                        if not has_more_tracks and len(playlist) > 0:
                            # All tracks played - reset and continue shuffling
                            self.played_tracks_in_shuffle.clear()
                            # Mark current track as played for the new cycle
                            if file_path:
                                self.played_tracks_in_shuffle.add(file_path)
                            has_more_tracks = len(playlist) > 1  # Continue if more than 1 track
                    else:
                        # Sequential mode - check if there's a next track
                        has_more_tracks = current_index < len(playlist) - 1
                    
                    if has_more_tracks:
                        # There are more tracks to play - trigger advancement
                        # Don't reset end_detected here - it will be reset when the track actually changes
                        # or in handle_track_finished after advancement
                        if self.on_track_finished:
                            self.on_track_finished()
                    elif state == "STOP":
                        # End of playlist (or all tracks played in shuffle) - ensure we're stopped
                        self.playlist_manager.set_current_index(-1)
                        self.playlist_view.set_playlist(playlist, -1)
                        # Reset played tracks when playback stops
                        if self.shuffle_enabled:
                            self.played_tracks_in_shuffle.clear()
            
            # Fallback: Detect if MOC stopped at the end (in case position detection missed it)
            # Only check this if we're still on the same file and MOC stopped
            if duration > 0 and state == "STOP" and file_path == self.last_file and not self.end_detected:
                # Check if position is at or near the end (within 1 second)
                if position >= duration - 1.0:
                    # Mark current track as played if shuffle is enabled
                    if self.shuffle_enabled and file_path:
                        self.played_tracks_in_shuffle.add(file_path)
                    
                    # Check if there are more tracks to play (same logic as above)
                    has_more_tracks = False
                    if self.shuffle_enabled:
                        playlist_file_paths = {t.file_path for t in playlist if t.file_path}
                        unplayed_tracks = playlist_file_paths - self.played_tracks_in_shuffle
                        has_more_tracks = len(unplayed_tracks) > 0
                        if not has_more_tracks and len(playlist) > 0:
                            self.played_tracks_in_shuffle.clear()
                            if file_path:
                                self.played_tracks_in_shuffle.add(file_path)
                            has_more_tracks = len(playlist) > 1
                    else:
                        has_more_tracks = current_index < len(playlist) - 1
                    
                    if has_more_tracks:
                        # Track finished and MOC stopped, but there are more tracks
                        # Don't reset end_detected here - it will be reset when the track actually changes
                        # or in handle_track_finished after advancement
                        if self.on_track_finished:
                            self.on_track_finished()
        else:
            # Not using MOC for current track, but MOC might be playing independently
            # Detect if MOC is playing a different track than our current one
            # This handles cases where user clicks "next" in mocp while app is using internal player
            if file_path and state == "PLAY":
                current_track = self.playlist_manager.get_current_track()
                if not current_track or file_path != current_track.file_path:
                    # MOC is playing independently (e.g., user clicked next in mocp)
                    # Reload playlist from MOC to sync with external changes
                    if self.sync_enabled:
                        # Disable sync temporarily to allow reloading from MOC
                        self.sync_enabled = False
                    # Force reload to sync with MOC's current state
                    self.load_playlist_from_moc()
                    # Update last_file to prevent duplicate track change detection
                    if file_path != self.last_file:
                        self.last_file = file_path
            elif state == "STOP":
                # Both are stopped - re-enable sync for next playback
                if not self.sync_enabled:
                    self.sync_enabled = True
        
        # Sync shuffle state from MOC if user changes it externally
        # BUT: Don't sync if we just set shuffle ourselves (prevent overwriting our state)
        # NOTE: MOC's shuffle/autonext commands don't seem to work reliably, so we ignore
        # MOC's reported state when we've set shuffle ourselves
        moc_shuffle = status.get("shuffle", False)
        if moc_shuffle != self.shuffle_enabled and not self._shuffle_set_pending:
            # Only sync if we didn't just set shuffle ourselves
            # But only sync FROM MOC if MOC actually has shuffle enabled (to detect external changes)
            # If MOC reports shuffle=false but we have it enabled, don't overwrite (MOC commands don't work)
            if moc_shuffle:
                # MOC has shuffle enabled externally - sync to our state
                self.set_shuffle_enabled(moc_shuffle)
            # If moc_shuffle is false but we have it enabled, ignore it (MOC's command didn't work)
        elif self._shuffle_set_pending:
            # Keep flag active for a few update cycles to allow MOC to update its status
            # Also clear if MOC now reports the correct shuffle state
            if moc_shuffle == self.shuffle_enabled:
                # MOC now matches our state - clear the flag
                self._shuffle_set_pending = False
                self._shuffle_set_pending_count = 0
            else:
                # Decrement counter, clear flag after 5 update cycles (~2.5 seconds)
                self._shuffle_set_pending_count -= 1
                if self._shuffle_set_pending_count <= 0:
                    self._shuffle_set_pending = False
                    self._shuffle_set_pending_count = 0
        # Note: shuffle sync is handled by main_window
        
        # Detect external playlist changes (e.g. from MOC UI or CLI) by watching the M3U file
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if moc_playlist_path.exists():
                mtime = moc_playlist_path.stat().st_mtime
            else:
                mtime = self.playlist_mtime
        except OSError:
            mtime = self.playlist_mtime
        
        # Track if file changed (before updating mtime)
        playlist_file_changed = mtime != self.playlist_mtime
        
        if playlist_file_changed:
            self.playlist_mtime = mtime
            # Reload playlist from MOC when file changes
            # If sync_enabled is False, MOC is playing independently - always reload
            # If sync_enabled is True, check if this is an external change
            # (we reload if track changed externally, detected earlier in this function)
            if not self.sync_enabled:
                # MOC is playing independently - reload to follow MOC
                self.load_playlist_from_moc()
            # Note: If sync_enabled is True and we just synced to MOC ourselves,
            # the track change detection above will have already handled reloading
        
        return True
    
    def reset_end_detection(self):
        """Reset end-of-track detection flag."""
        self.end_detected = False
    
    def reset_shuffle_tracking(self):
        """Reset shuffle tracking when playlist changes."""
        self.played_tracks_in_shuffle.clear()
        # Mark current track as played if shuffle is enabled
        if self.shuffle_enabled:
            current_track = self.playlist_manager.get_current_track()
            if current_track and current_track.file_path:
                self.played_tracks_in_shuffle.add(current_track.file_path)
    
    # ===================================================================
    # High-level playback control methods - main_window should use these
    # ===================================================================
    
    def play(self):
        """Start or resume playback."""
        if not self.use_moc:
            return
        self.moc_controller.play()
    
    def pause(self):
        """Pause playback."""
        if not self.use_moc:
            return
        self.moc_controller.pause()
    
    def stop(self):
        """Stop playback."""
        if not self.use_moc:
            return
        self.moc_controller.stop()
        self.playlist_manager.set_current_index(-1)
        self.playlist_view.set_playlist(self.playlist_manager.get_playlist(), -1)
        if self.shuffle_enabled:
            self.played_tracks_in_shuffle.clear()
    
    def next_track(self):
        """Advance to next track (handles shuffle if enabled)."""
        if not self.use_moc:
            return
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if self.shuffle_enabled:
            # Shuffle mode - select random unplayed track
            if len(tracks) == 0:
                return
            if len(tracks) == 1:
                new_index = 0
            else:
                # Get unplayed tracks
                playlist_file_paths = {t.file_path for t in tracks if t.file_path}
                unplayed = playlist_file_paths - self.played_tracks_in_shuffle
                
                if len(unplayed) == 0:
                    # All tracks played - reset and continue
                    self.played_tracks_in_shuffle.clear()
                    unplayed = playlist_file_paths
                    if current_index >= 0 and tracks[current_index].file_path:
                        self.played_tracks_in_shuffle.add(tracks[current_index].file_path)
                
                # Select random unplayed track
                unplayed_list = [t for t in tracks if t.file_path in unplayed]
                if unplayed_list:
                    selected = random.choice(unplayed_list)
                    new_index = tracks.index(selected)
                else:
                    return
        else:
            # Sequential mode
            if current_index < len(tracks) - 1:
                new_index = current_index + 1
            else:
                return  # End of playlist
        
        self.playlist_manager.set_current_index(new_index)
        self.playlist_view.set_playlist(tracks, new_index)
        self.play_track()
    
    def previous_track(self):
        """Go to previous track."""
        if not self.use_moc:
            return
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if current_index > 0:
            new_index = current_index - 1
            self.playlist_manager.set_current_index(new_index)
            self.playlist_view.set_playlist(tracks, new_index)
            self.play_track()
    
    def play_track(self):
        """Play the current track from playlist."""
        if not self.use_moc:
            return
        
        track = self.playlist_manager.get_current_track()
        if not track or not self.should_use_moc(track):
            return
        
        # Validate file exists
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            print(f"Error: Track file does not exist: {track.file_path}")
            return
        
        # Stop MOC if it's currently playing a different track
        # This ensures we can sync the new track without the sync being blocked
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            if moc_state == "PLAY" and moc_file and moc_file != track.file_path:
                # MOC is playing a different track - stop it first
                self.moc_controller.stop()
        
        # Sync playlist and start playback
        self.sync_playlist_for_playback()
        
        # For shuffle mode, disable MOC's autonext - we handle advancement ourselves
        # For sequential mode, enable autonext so MOC can auto-advance
        if self.shuffle_enabled:
            # Disable autonext - we'll manually advance using our shuffle logic
            self.moc_controller.disable_autonext()
            # Note: MOC's shuffle command doesn't work reliably, so we ignore it
            # and handle shuffle entirely in our code
        else:
            # Sequential mode - enable autonext so MOC can auto-advance
            self.moc_controller.enable_autonext()
            self.moc_controller.disable_shuffle()
        
        # Mark current track as played in shuffle mode
        if self.shuffle_enabled and track.file_path:
            self.played_tracks_in_shuffle.add(track.file_path)
        
        # Reset end detection
        self.reset_end_detection()
    
    def set_shuffle(self, enabled: bool):
        """Set shuffle mode and sync with MOC."""
        self.set_shuffle_enabled(enabled)
        if not self.use_moc:
            return
        
        if enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        
        # Always ensure autonext is enabled
        self.moc_controller.enable_autonext()
        # Set flag to prevent update_status from overwriting our state
        # Keep it active for 5 update cycles (~2.5 seconds) to allow MOC to update
        self._shuffle_set_pending = True
        self._shuffle_set_pending_count = 5
        # Note: Even if MOC doesn't report shuffle as enabled immediately, we keep our state
        # MOC's shuffle might work differently (e.g., only affects next track selection)
        
        # Notify UI of shuffle change
        if self.on_shuffle_changed:
            self.on_shuffle_changed(enabled)
    
    def get_shuffle_enabled(self) -> bool:
        """Get current shuffle state."""
        return self.shuffle_enabled
    
    def handle_track_finished(self):
        """Handle track completion - advance to next track if available."""
        if not self.use_moc:
            return
        
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        current_track = self.playlist_manager.get_current_track()
        
        # Mark current track as played if shuffle is enabled
        if self.shuffle_enabled and current_track and current_track.file_path:
            self.played_tracks_in_shuffle.add(current_track.file_path)
        
        # When shuffle is enabled, always use our shuffle logic instead of MOC's autonext
        # MOC's shuffle might not work reliably, so we handle it ourselves
        if self.shuffle_enabled:
            # Disable MOC's autonext to prevent conflicts with our shuffle logic
            # We'll manually advance using our shuffle algorithm
            self.moc_controller.disable_autonext()
            # Manually advance using our shuffle logic
            self.next_track()
            self.end_detected = False
            return
        
        # For sequential mode, check if MOC has already auto-advanced
        moc_status = self.moc_controller.get_status(force_refresh=True)
        
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            
            # Check if MOC has already advanced to a different track
            if moc_state == "PLAY" and moc_file and current_track and moc_file != current_track.file_path:
                # MOC has auto-advanced - sync our playlist index
                for idx, t in enumerate(tracks):
                    if t.file_path == moc_file:
                        self.playlist_manager.set_current_index(idx)
                        self.playlist_view.set_playlist(tracks, idx)
                        self.metadata_panel.set_track(t)
                        # Update MPRIS2 metadata
                        if self.mpris2:
                            self.mpris2.update_metadata(t)
                        # Update last_file to new track - this will reset end_detected in next update_status call
                        self.last_file = moc_file
                        # Reset end_detected since track has changed
                        self.end_detected = False
                        return
        
        # MOC hasn't auto-advanced - manually advance
        # Reset end_detected after we advance (next_track will change the track)
        self.next_track()
        # Reset end_detected after advancing to allow detection of next track end
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
    
    def seek(self, position: float):
        """Seek to position in current track."""
        if not self.use_moc:
            return
        
        # Get current position
        current_pos = self.get_cached_position()
        if current_pos == 0.0:
            status = self.moc_controller.get_status(force_refresh=False)
            if status:
                current_pos = float(status.get("position", 0.0))
        
        delta = position - current_pos
        if abs(delta) > 0.5:  # Only seek if delta is significant
            self.moc_controller.seek_relative(delta)
            # Reset end-detection if we seek away from the end
            duration = self.get_cached_duration()
            if duration > 0 and position < duration - 1.0:
                self.reset_end_detection()
            # Force refresh status cache after seek
            status_after = self.moc_controller.get_status(force_refresh=True)
            autonext_after = status_after.get("autonext", False) if status_after else False
            # Re-enable autonext if it was disabled by seek
            if not autonext_after:
                self.moc_controller.enable_autonext()

