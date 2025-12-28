"""MOC (Music On Console) synchronization helper.

This module handles synchronization between the application's internal playlist
and MOC's playlist, managing state, position tracking, and playback coordination.
"""

from pathlib import Path
from typing import Optional, Callable, List
import json
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
        self._resuming: bool = False  # Flag to prevent playlist sync during resume
        
        # Shuffle state - rely on MOC's shuffle when available
        self.shuffle_enabled: bool = False
        
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
    
    def sync_add_track_file(self, index: int, track: TrackMetadata):
        """
        Add a track at a specific index to both JSON and M3U playlist files.
        
        Args:
            index: Index where to add the track
            track: Track to add
        """
        # Add to JSON playlist file
        self.playlist_manager.add_track_at_index_file(index, track)
        
        # Add to M3U file if using MOC and track is audio
        if self.use_moc and self.sync_enabled and not self.is_video_track(track):
            file_path = str(Path(track.file_path).resolve())
            self.moc_controller.add_track_at_index_m3u(index, file_path)
    
    def sync_remove_track_file(self, index: int):
        """
        Remove a track at a specific index from both JSON and M3U playlist files.
        
        Args:
            index: Index of track to remove
        """
        # Remove from JSON playlist file
        self.playlist_manager.remove_track_at_index_file(index)
        
        # Remove from M3U file if using MOC
        if self.use_moc and self.sync_enabled:
            self.moc_controller.remove_track_at_index_m3u(index)
    
    def sync_move_track_file(self, from_index: int, to_index: int):
        """
        Move a track from one index to another in both JSON and M3U playlist files.
        
        Args:
            from_index: Original index of the track
            to_index: New index of the track
        """
        # Move in JSON playlist file
        self.playlist_manager.move_track_in_file(from_index, to_index)
        
        # Move in M3U file if using MOC
        if self.use_moc and self.sync_enabled:
            self.moc_controller.move_track_in_m3u(from_index, to_index)
    
    def sync_jump_to_index_file(self, index: int, start_playback: bool = False):
        """
        Jump to a specific index in MOC (uses MOC command, not file operation).
        
        Args:
            index: Index to jump to
            start_playback: Whether to start playback after jumping
        """
        if not self.sync_enabled:
            return
        
        track = self.playlist_manager.get_track_at_index_file(index)
        if track and self.is_video_track(track):
            return  # Don't sync video tracks to MOC
        
        # Use MOC command to jump (this updates MOC's internal state)
        self.moc_controller.jump_to_index(index, start_playback=start_playback)
        
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
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None:
            self.shuffle_enabled = moc_shuffle
            if self.on_shuffle_changed:
                self.on_shuffle_changed(moc_shuffle)
    
    def set_shuffle_enabled(self, enabled: bool):
        """Set shuffle state (relies on MOC's shuffle when available)."""
        self.shuffle_enabled = enabled
    
    def sync_playlist_to_moc(self, start_playback: bool = False):
        """Sync current playlist to MOC with debouncing to prevent rapid-fire syncs."""
        if not self.sync_enabled:
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
        if track and not self.is_video_track(track) and start_playback:
            # Using MOC for playback - sync playlist and start playing
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            # Not using MOC for current track - just sync playlist
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
        
        return False  # Don't repeat
    
    def sync_playlist_for_playback(self):
        """Sync playlist to MOC when starting playback."""
        if not self.sync_enabled:
            return
        # Don't sync if we're in the middle of resuming - this would reset the playlist
        if self._resuming:
            return
        
        # Check if MOC is already paused on the current track - if so, don't sync (would reset position)
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            current_track = self.playlist_manager.get_current_track()
            
            # If MOC is paused on the current track, don't sync (would reset position)
            if moc_state == "PAUSE" and moc_file and current_track:
                from pathlib import Path
                moc_file_abs = str(Path(moc_file).resolve())
                track_file_abs = str(Path(current_track.file_path).resolve())
                if moc_file_abs == track_file_abs:
                    return
            
            # Check if MOC is playing independently
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
        if track and not self.is_video_track(track):
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
        
        # Sync shuffle state
        # Note: shuffle state is managed by main_window, not here
    
    def load_playlist_from_moc(self):
        """Load playlist from MOC's playlist file."""
        # Load playlist from MOC
        tracks, current_index = self.moc_controller.get_playlist()
        
        if tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(tracks)
            if current_index >= 0:
                self.playlist_manager.set_current_index(current_index)
            self.playlist_view.set_playlist(tracks, current_index)
            # Reset shuffle tracking when loading a new playlist
            
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
        
        # If last_file is None and we have a file_path, set it to prevent false track change detection
        # This is especially important when resuming, as last_file might not be set yet
        if self.last_file is None and file_path:
            self.last_file = file_path
        
        # Update UI state if we're using MOC for current track
        track = self.playlist_manager.get_current_track()
        if track and not self.is_video_track(track):
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
            # BUT: Don't treat state change from PAUSE to PLAY as a track change (it's just resuming)
            # Only treat it as a track change if the file_path actually changed AND we're not just resuming
            # Also, if last_file is None (first time), don't treat it as a track change
            if file_path and file_path != self.last_file and self.last_file is not None:
                # Don't reload playlist if we're in the middle of resuming - this would reset the playlist
                if self._resuming:
                    # Just update last_file to match current file
                    self.last_file = file_path
                    self.end_detected = False
                    return True
                
                # Check if this is just a resume (same track, state changed from PAUSE to PLAY)
                # If so, don't reload the playlist - just update last_file
                current_track = self.playlist_manager.get_current_track()
                if current_track and current_track.file_path:
                    from pathlib import Path
                    current_file_abs = str(Path(current_track.file_path).resolve())
                    new_file_abs = str(Path(file_path).resolve())
                    if current_file_abs == new_file_abs:
                        # Same track - just resuming, don't reload playlist
                        self.last_file = file_path
                        self.end_detected = False
                        return True
                
                # Track actually changed - MOC has advanced to next track or changed externally
                # MOC handles shuffle automatically, no need to track played tracks
                
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
                    
                    # Check if there are more tracks to play
                    # When using MOC, it handles shuffle automatically, so just check if there's a next track
                    has_more_tracks = current_index < len(playlist) - 1
                    
                    if has_more_tracks:
                        # There are more tracks to play - trigger advancement
                        # Don't reset end_detected here - it will be reset when the track actually changes
                        # or in handle_track_finished after advancement
                        if self.on_track_finished:
                            self.on_track_finished()
                    elif state == "STOP":
                        # End of playlist - ensure we're stopped
                        self.playlist_manager.set_current_index(-1)
                        self.playlist_view.set_playlist(playlist, -1)
            
            # Fallback: Detect if MOC stopped at the end (in case position detection missed it)
            # Only check this if we're still on the same file and MOC stopped
            if duration > 0 and state == "STOP" and file_path == self.last_file and not self.end_detected:
                # Check if position is at or near the end (within 1 second)
                if position >= duration - 1.0:
                    # Check if there are more tracks to play
                    # When using MOC, it handles shuffle automatically
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
        # Since we rely on MOC's shuffle, always sync from MOC's reported state
        moc_shuffle = status.get("shuffle", False)
        if moc_shuffle != self.shuffle_enabled:
            # MOC's shuffle state changed - sync to our state
            self.set_shuffle_enabled(moc_shuffle)
            if self.on_shuffle_changed:
                self.on_shuffle_changed(moc_shuffle)
        
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
        
    # ===================================================================
    # High-level playback control methods - main_window should use these
    # ===================================================================
    
    def play(self):
        """Start or resume playback."""
        # Set resuming flag to prevent playlist sync during resume
        self._resuming = True
        
        # Set last_file to current track to prevent false track change detection during resume
        current_track = self.playlist_manager.get_current_track()
        if current_track and current_track.file_path:
            self.last_file = current_track.file_path
        
        self.moc_controller.play()
        # Clear resuming flag after a short delay to allow MOC to resume
        # Use GLib.timeout_add to clear after resume completes
        def clear_resuming():
            self._resuming = False
            return False  # Don't repeat
        from gi.repository import GLib
        GLib.timeout_add(1000, clear_resuming)  # Clear after 1 second
    
    def pause(self):
        """Pause playback."""
        self.moc_controller.pause()
    
    def stop(self):
        """Stop playback."""
        self.moc_controller.stop()
        self.playlist_manager.set_current_index(-1)
        self.playlist_view.set_playlist(self.playlist_manager.get_playlist(), -1)
    
    def next_track(self):
        """Go to next track."""
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if current_index < len(tracks) - 1:
            new_index = current_index + 1
            self.playlist_manager.set_current_index(new_index)
            self.playlist_view.set_playlist(tracks, new_index)
            self.play_track()
        else:
            # No next track - stop playback
            self.moc_controller.stop()
            self.playlist_manager.set_current_index(-1)
            self.playlist_view.set_playlist(tracks, -1)
    
    def previous_track(self):
        """Go to previous track."""
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        
        if current_index > 0:
            new_index = current_index - 1
            self.playlist_manager.set_current_index(new_index)
            self.playlist_view.set_playlist(tracks, new_index)
            self.play_track()
    
    def play_track(self):
        """Play the current track from playlist."""
        track = self.playlist_manager.get_current_track()
        if not track or self.is_video_track(track):
            return
        
        # Validate file exists
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            logger.error("Track file does not exist: %s", track.file_path)
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
        
        # Set shuffle state in MOC
        if self.shuffle_enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        
        # Update playlist view to ensure current track is highlighted and visible
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
        
        # Update metadata panel with new track
        self.metadata_panel.set_track(track)
        # Update MPRIS2 metadata
        if self.mpris2:
            self.mpris2.update_metadata(track)
        
        # Reset end detection
        self.reset_end_detection()
    
    def set_shuffle(self, enabled: bool):
        """Set shuffle mode and sync with MOC."""
        self.shuffle_enabled = enabled
        if enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        if self.on_shuffle_changed:
            self.on_shuffle_changed(enabled)
    
    def get_shuffle_enabled(self) -> bool:
        """Get current shuffle state."""
        return self.shuffle_enabled
    
    def get_autonext_enabled(self) -> bool:
        """Get current autonext state from MOC."""
        autonext_state = self.moc_controller.get_autonext_state()
        return autonext_state if autonext_state is not None else True
    
    def set_autonext_enabled(self, enabled: bool):
        """Set autonext state in MOC."""
        if enabled:
            self.moc_controller.enable_autonext()
        else:
            self.moc_controller.disable_autonext()
    
    def toggle_autonext(self) -> bool:
        """Toggle autonext state and return new state."""
        new_state = not self.get_autonext_enabled()
        self.set_autonext_enabled(new_state)
        return new_state
    
    def handle_track_finished(self):
        """Handle track completion - let MOC handle advancement (including shuffle)."""
        # MOC handles shuffle automatically when enabled, so we don't need to do anything
        # MOC's autonext will advance to the next track (shuffled if shuffle is enabled)
        # Just reset end_detected flag
        self.end_detected = False
        
        # Check if MOC has already auto-advanced
        tracks = self.playlist_manager.get_playlist()
        current_track = self.playlist_manager.get_current_track()
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
        
        # MOC hasn't auto-advanced - MOC will handle it automatically with autonext
        # No need to manually advance when using MOC shuffle
    
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
    
    def seek(self, position: float, force: bool = False):
        """
        Seek to position in current track.
        
        Args:
            position: Target position in seconds
            force: If True, always seek regardless of threshold (for user-initiated seeks)
        """
        # Clamp position to valid range
        position = max(0.0, position)
        duration = self.get_cached_duration()
        if duration > 0:
            position = min(position, duration)
        
        # Get current position
        current_pos = self.get_cached_position()
        if current_pos == 0.0:
            status = self.moc_controller.get_status(force_refresh=False)
            if status:
                current_pos = float(status.get("position", 0.0))
        
        delta = position - current_pos
        # Always seek if forced (user-initiated) or if delta is significant (>= 0.5 seconds)
        # The 0.5 second threshold prevents tiny seeks from automatic playback position updates
        if force or abs(delta) >= 0.5:
            self.moc_controller.seek_relative(delta)
            # Reset end-detection when seeking (whether away from or to the end)
            # This ensures end detection can trigger properly after seeking
            if duration > 0:
                # Always reset end detection when seeking, so the next update_status
                # can properly detect if we're at the end and trigger autoplay
                self.reset_end_detection()
            # Force refresh status cache after seek
            status_after = self.moc_controller.get_status(force_refresh=True)
            if status_after:
                # Update cached position after seek
                new_position = float(status_after.get("position", position))
                self.last_position = new_position
            logger.debug("Seeked to position %.2f (delta: %.2f, forced: %s)", position, delta, force)
        else:
            logger.debug("Seek skipped - delta too small: %.2f seconds", abs(delta))

