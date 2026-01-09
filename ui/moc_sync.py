"""MOC (Music On Console) synchronization helper.

This module handles synchronization between the application's internal playlist
and MOC's playlist, managing state, position tracking, and playback coordination.
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from ui.components.metadata_panel import MetadataPanel
    from ui.components.player_controls import PlayerControls
    from ui.components.playlist_view import PlaylistView

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.config import get_config
from core.logging import get_logger
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.playlist_manager import PlaylistManager
from core.workflow_utils import is_video_file

if TYPE_CHECKING:
    from ui.components.metadata_panel import MetadataPanel
    from ui.components.player_controls import PlayerControls
    from ui.components.playlist_view import PlaylistView

logger = get_logger(__name__)


class OperationState(Enum):
    """State machine for MOC operations to prevent race conditions."""

    IDLE = "idle"  # No operation in progress
    RESUMING = "resuming"  # Resume operation in progress
    SEEKING = "seeking"  # Seek operation in progress
    SYNCING = "syncing"  # Playlist sync in progress


class SyncState(Enum):
    """State machine for sync mode."""

    ENABLED = "enabled"  # App controls MOC (normal mode)
    DISABLED = "disabled"  # MOC playing independently
    INITIALIZING = "initializing"  # Initial setup


class MocSyncHelper:
    """
    Helper class for managing MOC synchronization.
    
    Handles:
    - Playlist synchronization between app and MOC
    - Position and state tracking
    - End-of-track detection
    - External playlist change detection
    """
    
    def __init__(
        self,
        moc_controller: MocController,
        playlist_manager: "PlaylistManager",
        player_controls: "PlayerControls",
        metadata_panel: "MetadataPanel",
        playlist_view: "PlaylistView",
    ) -> None:
        """
        Initialize MOC sync helper.
        
        Args:
            moc_controller: MocController instance
            playlist_manager: PlaylistManager instance
            player_controls: PlayerControls instance
            metadata_panel: MetadataPanel instance
            playlist_view: PlaylistView instance
        """
        self.moc_controller = moc_controller
        self.playlist_manager = playlist_manager
        self.player_controls = player_controls
        self.metadata_panel = metadata_panel
        self.playlist_view = playlist_view
        
        self.use_moc = moc_controller.is_available()
        
        # State tracking
        self.last_position: float = 0.0
        self.last_duration: float = 0.0
        self.last_file: Optional[str] = None
        self.playlist_mtime: float = 0.0
        self.shuffle_enabled: bool = False
        self._recent_moc_write: Optional[float] = None  # Timestamp of last MOC write

        # Explicit state machines (replaces boolean flags)
        self._operation_state = OperationState.IDLE
        self._sync_state = SyncState.INITIALIZING
        
        # Callbacks
        self.on_track_finished: Optional[Callable] = None
        self.on_shuffle_changed: Optional[Callable[[bool], None]] = None
        
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
        if not track or not track.file_path:
            return False
        return self.use_moc and not is_video_file(track.file_path)

    def is_sync_enabled(self) -> bool:
        """Check if sync is currently enabled (app controls MOC)."""
        return self._sync_state == SyncState.ENABLED

    def enable_sync(self) -> None:
        """Enable sync mode (app controls MOC)."""
        self._sync_state = SyncState.ENABLED
    
    def initialize(self) -> bool:
        """Initialize MOC server and settings."""
        if not self.use_moc:
            self._sync_state = SyncState.DISABLED
            return False
        
        self._sync_state = SyncState.INITIALIZING

        if self.moc_controller.ensure_server():
            self.moc_controller.enable_autonext()
            self.sync_shuffle_from_moc()
            self._sync_state = SyncState.ENABLED
            return True

        self._sync_state = SyncState.DISABLED
        return False
    
    def sync_shuffle_from_moc(self) -> None:
        """Sync shuffle state from MOC to UI."""
        if not self.use_moc:
            return
        
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None and self.on_shuffle_changed:
            self.on_shuffle_changed(moc_shuffle)
    
    def update_moc_playlist(self, start_playback: bool = False) -> None:
        """Update MOC playlist to reflect current UI state."""
        if not self.use_moc:
            return
        # Get current state from playlist_view
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()
        track = self.playlist_view.get_current_track()
        
        # Determine if we should start playback (only for audio tracks)
        should_start = start_playback and track is not None and not is_video_file(track.file_path)
        
        # Update MOC state directly
        self.moc_controller.set_playlist(tracks, current_index, start_playback=should_start)
        
        # Don't enable autonext here - _sync_moc_options() will handle it
        # This avoids duplicate commands and reduces ensure_server() calls
        
        # Track when we write to MOC - use this to avoid reading our own writes immediately
        # But we still want to read MOC's updates, so use a short window (0.5s)
        self._recent_moc_write = time.time()
        
        # Update playlist mtime after write to track the file state
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if moc_playlist_path.exists():
                self.playlist_mtime = moc_playlist_path.stat().st_mtime
        except OSError:
            pass
    
    
    def load_playlist_from_moc(self, force_refresh: bool = False) -> None:
        """Load playlist from MOC's playlist file and save to JSON.
        
        Args:
            force_refresh: If True, always update the playlist even if M3U file is empty.
                          This is useful for the refresh button to ensure we read the current state.
        """
        if not self.use_moc:
            return
        
        tracks, current_index = self.moc_controller.get_playlist()
        
        # Always update the playlist if we have tracks, or if force_refresh is True
        if tracks or force_refresh:
            # Update JSON playlist directly to reflect MOC state (bypass playlist_view methods to avoid MOC updates)
            # This prevents playlist_view from triggering MOC updates during load
            self.playlist_manager.clear()
            if tracks:
                self.playlist_manager.add_tracks(tracks)
                if current_index >= 0:
                    self.playlist_manager.set_current_index(current_index)
            # _sync_to_file() is called automatically by clear() and add_tracks()
            # Update view directly from playlist_manager's in-memory state
            tracks_copy = self.playlist_manager.get_playlist()
            current_index_copy = self.playlist_manager.get_current_index()
            self.playlist_view.set_playlist(tracks_copy, current_index_copy)
            
            # Update playlist mtime after load
            try:
                config = get_config()
                moc_playlist_path = config.moc_playlist_path
                if moc_playlist_path.exists():
                    self.playlist_mtime = moc_playlist_path.stat().st_mtime
            except OSError:
                pass
        elif not tracks:
            # Check if MOC is playing something - if so, it has a playlist in memory
            status = self.moc_controller.get_status()
            if status and status.get("state") in ("PLAY", "PAUSE") and status.get("file_path"):
                # MOC is playing but we can't read the playlist file
                # If force_refresh, still clear the playlist to reflect that file is empty
                if force_refresh:
                    self.playlist_manager.clear()
                    self.playlist_view.set_playlist([], -1)
                # Otherwise, don't clear - MOC has tracks in memory that aren't saved yet
    
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
        track = self.playlist_view.get_current_track()
        if track and self.should_use_moc(track):
            # Update playback state
            self.player_controls.set_playing(state == "PLAY")
            
            # Update position display (but not during seek to avoid overwriting)
            # Only update if we're not in the middle of a seek operation
            if self._operation_state != OperationState.SEEKING:
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
                
                # Read MOC's current playlist from file to see what it's actually playing
                # This ensures we're in sync with what MOC has
                moc_tracks, moc_index = self.moc_controller.get_playlist(current_file=file_path)
                
                # Update metadata and playlist
                new_track = TrackMetadata(file_path)
                self.metadata_panel.set_track(new_track)
                
                # Find and select this track in our playlist
                playlist = self.playlist_view.get_playlist()
                found_in_playlist = False
                for idx, t in enumerate(playlist):
                    # Normalize paths for comparison
                    if str(Path(t.file_path).resolve()) == str(Path(file_path).resolve()):
                        self.playlist_view.set_current_index(idx)
                        found_in_playlist = True
                        break
                
                # If track not found in our playlist, but MOC is playing it,
                # it means MOC's playlist differs from ours - reload from MOC
                if not found_in_playlist and moc_tracks:
                    # MOC has a different playlist - sync to it
                    self.load_playlist_from_moc(force_refresh=False)
                elif found_in_playlist:
                    # Track is in our playlist - ensure MOC's playlist matches ours
                    # and autonext is enabled for next track
                    self.moc_controller.enable_autonext()
                    # Verify MOC's playlist matches - if not, update it
                    if moc_tracks and len(moc_tracks) != len(playlist):
                        # Playlist mismatch - update MOC to match our playlist
                        self.update_moc_playlist(start_playback=False)
                    
                    # Update player_controls state to reflect the track change
                    # This ensures UI is in sync with MOC's playback
                    self.player_controls.set_playing(state == "PLAY")
                    self.player_controls.emit("track-changed", new_track)
                    if self.player_controls.mpris2:
                        self.player_controls.mpris2.update_metadata(new_track)
            
            # Fallback: Detect if track reached the end and MOC stopped unexpectedly
            # Only check this if we're still on the same file (no track change detected)
            # and MOC stopped but there's a next track available
            if duration > 0 and state == "STOP" and file_path == self.last_file:
                playlist = self.playlist_view.get_playlist()
                current_index = self.playlist_view.get_current_index()
                # Check if position is at or near the end (within 1 second)
                if position >= duration - 1.0 and current_index < len(playlist) - 1:
                    # Track finished and MOC stopped, but there's a next track
                    # This shouldn't happen if autonext is working, but handle it anyway
                    # Ensure autonext is enabled and try to advance manually
                    self.moc_controller.enable_autonext()
                    # Try to advance to next track using player_controls
                    next_track = self.playlist_view.get_next_track()
                    if next_track:
                        # Update MOC playlist to ensure next track is available and play it
                        self.update_moc_playlist(start_playback=True)
                    elif self.on_track_finished:
                        self.on_track_finished()
        else:
            # Detect if MOC is playing independently (not synced from our app)
            if file_path and state == "PLAY":
                current_track = self.playlist_view.get_current_track()
                if not current_track or file_path != current_track.file_path:
                    # MOC is playing independently - disable sync
                    if self._sync_state == SyncState.ENABLED:
                        self._sync_state = SyncState.DISABLED
                        self.last_file = file_path
                        # Update UI to reflect MOC's independent playback
                        track = TrackMetadata(file_path)
                        self.metadata_panel.set_track(track)
                        # Try to find and select this track in our playlist
                        playlist = self.playlist_view.get_playlist()
                        for idx, t in enumerate(playlist):
                            if t.file_path == file_path:
                                self.playlist_view.set_current_index(idx)
                                break
            elif state == "STOP":
                # Both are stopped - re-enable sync for next playback
                if self._sync_state == SyncState.DISABLED:
                    self._sync_state = SyncState.ENABLED
        
        # Sync shuffle state from MOC if user changes it externally
        moc_shuffle = status.get("shuffle", False)
        # Note: shuffle sync is handled by main_window
        
        # Detect playlist file changes - MOC writes to this file when its playlist changes
        # We should always read from the file as the source of truth when MOC is active
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            if moc_playlist_path.exists():
                mtime = moc_playlist_path.stat().st_mtime
                
                # Check if file changed (with 0.1s threshold to avoid race conditions)
                if abs(mtime - self.playlist_mtime) > 0.1:
                    # Check if we wrote it very recently (within 0.5s) - if so, skip to avoid reading our own write
                    # Otherwise, read from file (MOC might have updated it, or it's an external change)
                    if not self._recent_moc_write or (time.time() - self._recent_moc_write > 0.5):
                        # File changed - read from it as the source of truth
                        self.load_playlist_from_moc(force_refresh=False)
                    self.playlist_mtime = mtime
            else:
                # File doesn't exist - if we had a playlist before, clear it
                if self.playlist_mtime > 0:
                    self.playlist_manager.clear()
                    self.playlist_view.set_playlist([], -1)
                    self.playlist_mtime = 0.0
        except OSError:
            # File access error - keep current mtime
            pass
        
        return True
    
    
    
    def play(self) -> None:
        """Resume playback in MOC."""
        if not self.use_moc:
            return
        self.moc_controller.play()
    
    def pause(self) -> None:
        """Pause playback in MOC."""
        if not self.use_moc:
            return
        self.moc_controller.pause()
    
    def stop(self) -> None:
        """Stop playback in MOC."""
        if not self.use_moc:
            return
        self.moc_controller.stop()
        self.playlist_view.set_current_index(-1)
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
    
    def shutdown(self) -> None:
        """Shutdown MOC server."""
        if not self.use_moc:
            return
        self.moc_controller.shutdown()
    
    def get_status(self, force_refresh: bool = False) -> Optional[Dict]:
        """
        Get MOC status (wrapper around moc_controller.get_status()).
        
        Args:
            force_refresh: If True, bypass cache and get fresh status
            
        Returns:
            Status dict or None if unavailable
        """
        if not self.use_moc:
            return None
        return self.moc_controller.get_status(force_refresh=force_refresh)
    
    def navigate_track(self, direction: int) -> None:
        """Navigate to next (1) or previous (-1) track."""
        if not self.use_moc:
            return
        
        if direction == 1:
            track = self.playlist_view.get_next_track()
        else:
            track = self.playlist_view.get_previous_track()
        
        if track:
            # get_next_track()/get_previous_track() already updated the index
            current_index = self.playlist_view.get_current_index()
            # Use moc_controller.jump_to_index() to jump to the new track and play
            self.moc_controller.jump_to_index(current_index, start_playback=True)
            # Update UI
            tracks = self.playlist_view.get_playlist()
            self.playlist_view.set_playlist(tracks, current_index)
        else:
            # No track available - stop playback
            self.moc_controller.stop()
            self.playlist_view.set_current_index(-1)
            tracks = self.playlist_view.get_playlist()
            self.playlist_view.set_playlist(tracks, -1)
    
    def next_track(self) -> None:
        """Move to next track."""
        self.navigate_track(1)
    
    def previous_track(self) -> None:
        """Move to previous track."""
        self.navigate_track(-1)
    
    def play_track(self) -> None:
        """Play current track - uses moc_controller.set_playlist() for coordination."""
        if not self.use_moc:
            return
        track = self.playlist_view.get_current_track()
        if not track or (track.file_path and is_video_file(track.file_path)):
            return
        
        # Validate track file exists
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            logger.error("Track file does not exist: %s", track.file_path)
            return
        
        # Stop MOC if playing different track
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            if moc_state == "PLAY" and moc_file and moc_file != track.file_path:
                self.moc_controller.stop()
        
        # Sync playlist and start playback using moc_controller.set_playlist()
        tracks = self.playlist_view.get_playlist()
        current_index = self.playlist_view.get_current_index()
        self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        
        # Set shuffle state if needed
        if self.shuffle_enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        
        # Update UI with current state from playlist_view
        self.playlist_view.set_playlist(tracks, current_index)
        self.metadata_panel.set_track(track)
        if hasattr(self, "mpris2") and self.mpris2:
            self.mpris2.update_metadata(track)
    
    def handle_track_finished(self) -> None:
        """Handle track finished event using playlist_view."""
        if not self.use_moc:
            return
        tracks = self.playlist_view.get_playlist()
        current_track = self.playlist_view.get_current_track()
        moc_status = self.moc_controller.get_status(force_refresh=True)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            if (
                moc_state == "PLAY"
                and moc_file
                and current_track
                and moc_file != current_track.file_path
            ):
                # Find the track in playlist and set it as current
                for idx, track_item in enumerate(tracks):
                    if track_item.file_path == moc_file:
                        self.playlist_view.set_current_index(idx)
                        current_index = self.playlist_view.get_current_index()
                        self.playlist_view.set_playlist(tracks, current_index)
                        self.metadata_panel.set_track(track_item)
                        if hasattr(self, "mpris2") and self.mpris2:
                            self.mpris2.update_metadata(track_item)
                        self.last_file = moc_file
                        return
    
    
    def seek(self, position: float, force: bool = False) -> None:
        """
        Seek to a specific position in the current track.

        This method always refreshes the current position from MOC before calculating
        the delta, ensuring accurate relative seeks even if the cache is stale.

        Uses explicit state machine to prevent race conditions with update_status().
        
        Args:
            position: Target position in seconds
            force: If True, seek even if delta is small (use with caution)
        """
        if not self.use_moc:
            return
        
        # Set operation state to prevent update_status from overwriting position
        self._operation_state = OperationState.SEEKING

        try:
            # Clamp position to valid range
            position = max(0.0, position)
            # Use cached duration or get from status
            duration = self.last_duration if self.last_duration > 0 else 0.0
            if duration == 0:
                status = self.moc_controller.get_status(force_refresh=False)
                if status:
                    duration = float(status.get("duration", 0.0))
            if duration > 0:
                position = min(position, duration)
            
            # CRITICAL: Always refresh position from MOC before seeking
            # This prevents stale cache from causing incorrect relative seeks
            # MOC only supports relative seeks, so we need accurate current position
            status = self.moc_controller.get_status(force_refresh=True)
            if status:
                current_pos = float(status.get("position", 0.0))
                # Update cache with fresh value for next time
                self.last_position = current_pos
            else:
                # Fallback to cache if status unavailable (shouldn't happen normally)
                current_pos = self.last_position
            
            # Calculate delta for relative seek
            delta = position - current_pos

            # Only perform seek if:
            # 1. Force flag is set (user-initiated seek), OR
            # 2. Delta is significant (>= 0.5 seconds)
            # This prevents tiny seeks that cause audio glitches
            if force or abs(delta) >= 0.5:
                # MOC uses relative seeks, so we send the delta
                self.moc_controller.seek_relative(delta)
                # Update cache to reflect expected position after seek
                self.last_position = position
            # If delta is too small and not forced, silently ignore
            # (prevents audio glitches from micro-seeks)
        finally:
            # Always reset state, even if seek fails
            self._operation_state = OperationState.IDLE
    
    def set_shuffle(self, enabled: bool) -> None:
        """Set shuffle state in MOC."""
        if not self.use_moc:
            return
        self.shuffle_enabled = enabled
        if enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        if self.on_shuffle_changed:
            self.on_shuffle_changed(enabled)
    
    
    def set_autonext_enabled(self, enabled: bool) -> None:
        """Set autonext state in MOC."""
        if not self.use_moc:
            return
        if enabled:
            self.moc_controller.enable_autonext()
        else:
            self.moc_controller.disable_autonext()
    
    def toggle_autonext(self) -> bool:
        """Toggle autonext state."""
        if not self.use_moc:
            return True
        autonext_state = self.moc_controller.get_autonext_state()
        current_state = autonext_state if autonext_state is not None else True
        new_state = not current_state
        self.set_autonext_enabled(new_state)
        return new_state
