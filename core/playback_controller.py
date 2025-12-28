"""Playback controller - handles all playback logic and state management."""

from pathlib import Path
from typing import Optional, Callable

from typing import TYPE_CHECKING

from core.audio_player import AudioPlayer, VIDEO_EXTENSIONS
from core.metadata import TrackMetadata
from core.moc_controller import MocController
from core.playlist_manager import PlaylistManager
from ui.components import player_controls
from ui.moc_sync import MocSyncHelper
from core.logging import get_logger

if TYPE_CHECKING:
    from ui.components.player_controls import PlayerControls

logger = get_logger(__name__)


class PlaybackController:
    """
    Central controller for all playback operations.
    
    Handles:
    - Playing, pausing, stopping tracks
    - Resuming paused tracks
    - Seeking
    - Track navigation (next/previous)
    - Player selection (MOC vs internal player)
    """
    
    def __init__(
        self,
        playlist_manager: PlaylistManager,
        moc_sync: MocSyncHelper,
        player: AudioPlayer,
        moc_controller: MocController,
        player_controls: 'PlayerControls',
        is_video_track: Callable[[Optional[TrackMetadata]], bool],
        normalize_path: Callable[[Optional[str]], Optional[str]],
        on_track_changed: Optional[Callable[[TrackMetadata], None]] = None,
        on_playback_state_changed: Optional[Callable[[bool], None]] = None,
    ):
        """
        Initialize playback controller.
        
        Args:
            playlist_manager: Manages the playlist
            moc_sync: MOC synchronization helper
            player: Internal GStreamer player
            moc_controller: MOC controller for status queries
            player_controls: UI component for player controls
            is_video_track: Function to check if track is video
            normalize_path: Function to normalize file paths
            on_track_changed: Callback when track changes
            on_playback_state_changed: Callback when playback state changes
        """
        self.playlist_manager = playlist_manager
        self.moc_sync = moc_sync
        self.player = player
        self.moc_controller = moc_controller
        self.player_controls = player_controls
        self._is_video_track = is_video_track
        self._normalize_path = normalize_path
        self.on_track_changed = on_track_changed
        self.on_playback_state_changed = on_playback_state_changed
        
        # Expose player callbacks for main_window to set
        # These forward to the internal player for video tracks
        self.on_state_changed = None
        self.on_position_changed = None
        self.on_track_finished = None
        self.on_track_loaded = None
        
        # Setup player callbacks to forward to our callbacks
        self.player.on_state_changed = lambda playing: self._on_player_state_changed(playing)
        self.player.on_position_changed = lambda pos: self._on_player_position_changed(pos)
        self.player.on_track_finished = lambda: self._on_player_track_finished()
        self.player.on_track_loaded = lambda: self._on_player_track_loaded()
    
    def is_track_playing(self, track: TrackMetadata) -> bool:
        """
        Check if a track is currently playing.
        
        Args:
            track: The track to check
            
        Returns:
            True if the track is currently playing, False otherwise
        """
        if not self._is_video_track(track):
            # Check if MOC is playing this track
            moc_status = self.moc_controller.get_status(force_refresh=False)
            if moc_status:
                moc_state = moc_status.get("state", "STOP")
                moc_file = moc_status.get("file_path")
                # Normalize paths for comparison
                if moc_file and track.file_path:
                    moc_file_abs = self._normalize_path(moc_file)
                    track_file_abs = self._normalize_path(track.file_path)
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        return moc_state == "PLAY"
            return False
        else:
            # Check if internal player is playing this track
            if self.player.current_track and self.player.is_playing:
                current_file_abs = self._normalize_path(self.player.current_track.file_path)
                track_file_abs = self._normalize_path(track.file_path)
                if current_file_abs and track_file_abs and current_file_abs == track_file_abs:
                    return True
            return False
    
    def can_resume_track(self, track: TrackMetadata) -> bool:
        """
        Check if a track is currently paused and can be resumed.
        
        Args:
            track: The track to check
            
        Returns:
            True if the track is paused and can be resumed, False otherwise
        """
        if not self._is_video_track(track):
            # Check if MOC is paused on this track
            moc_status = self.moc_controller.get_status(force_refresh=True)
            if moc_status:
                moc_state = moc_status.get("state", "STOP")
                moc_file = moc_status.get("file_path")
                # Normalize paths for comparison
                if moc_file and track.file_path:
                    moc_file_abs = self._normalize_path(moc_file)
                    track_file_abs = self._normalize_path(track.file_path)
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        return moc_state == "PAUSE"
            return False
        else:
            # Check if internal player is paused on this track
            if self.player.current_track:
                current_file_abs = self._normalize_path(self.player.current_track.file_path)
                track_file_abs = self._normalize_path(track.file_path)
                if current_file_abs and track_file_abs and current_file_abs == track_file_abs:
                    return not self.player.is_playing
            return False
    
    def resume_track(self, track: TrackMetadata):
        """
        Resume playback of a paused track.
        
        Args:
            track: The track to resume
        """
        # Reset user interaction state to ensure duration labels update properly
        if hasattr(self.player_controls, '_user_interacting'):
            self.player_controls._user_interacting = False
        
        if not self._is_video_track(track):
            # Resume MOC playback
            self._stop_internal_player()
            self.moc_sync.play()
            # Update player controls with current position after resume
            # This ensures UI reflects any seeks done while paused
            position = self.moc_sync.get_cached_position()
            duration = self.moc_sync.get_cached_duration()
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
        else:
            # Resume internal player playback
            self.player.play()
            # Update player controls with current position after resume
            position = self.player.get_position()
            duration = self.player.get_duration()
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
        
        # Update UI state immediately
        self.player_controls.set_playing(True)
        
        if self.on_playback_state_changed:
            self.on_playback_state_changed(True)
        
        if self.on_track_changed:
            self.on_track_changed(track)
    
    def play_current_track(self):
        """Play the current track from playlist - use MOC for audio, internal player for video."""
        track = self.playlist_manager.get_current_track()
        if not track:
            return
        
        # Validate track file exists
        if not track.file_path:
            logger.error("Track has no file path")
            return
        
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            logger.error("Track file does not exist: %s", track.file_path)
            return
        
        # Stop all currently playing tracks before starting a new one
        self._stop_all_players()
        
        # Reset position display when starting a new track
        self.player_controls.update_progress(0.0, 0.0)
        
        # Decide which player to use based on file type
        if not self._is_video_track(track):
            # Use MOC for audio files - delegate to moc_sync
            self._stop_internal_player()
            self.moc_sync.play_track()
        else:
            # Use internal player for video files
            self.player.load_track(track)
            self.player.play()
            
            # Sync MOC playlist (but don't play in MOC for video files)
            self.moc_sync.sync_enabled = True
            self.moc_sync.sync_playlist_to_moc(start_playback=False)
        
        # Update UI state immediately
        self.player_controls.set_playing(True)
        
        if self.on_playback_state_changed:
            self.on_playback_state_changed(True)
        
        if self.on_track_changed:
            self.on_track_changed(track)
    
    def play(self, selected_index: Optional[int] = None):
        """
        Handle play action - resume, play selected, or play current.
        
        Args:
            selected_index: Optional index of selected track to play
        """
        # Step 1: Check if we can resume a paused track
        current_track = self.playlist_manager.get_current_track()
        
        if current_track:
            # Check if this track is already playing - do nothing
            if self.is_track_playing(current_track):
                return
            
            # Check if this track is paused and can be resumed
            if self.can_resume_track(current_track):
                self.resume_track(current_track)
                return
        
        # Step 2: Check if there's a selected track in the playlist
        if selected_index is not None and selected_index >= 0:
            playlist = self.playlist_manager.get_playlist()
            if 0 <= selected_index < len(playlist):
                self.playlist_manager.set_current_index(selected_index)
                self.play_current_track()
                return
        
        # Step 3: Play current track (if exists)
        if current_track:
            self.play_current_track()
    
    def pause(self):
        """Handle pause action."""
        # Reset user interaction state to ensure duration labels update properly
        if hasattr(self.player_controls, '_user_interacting'):
            self.player_controls._user_interacting = False
        
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.pause()
        else:
            # Use internal player for video files
            self.player.pause()
        
        # Update UI state immediately
        self.player_controls.set_playing(False)
        
        if self.on_playback_state_changed:
            self.on_playback_state_changed(False)
    
    def stop(self):
        """Handle stop action."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.stop()
        else:
            # Use internal player for video files
            self.player.stop()
        
        # Update UI state immediately
        self.player_controls.set_playing(False)
        
        if self.on_playback_state_changed:
            self.on_playback_state_changed(False)
    
    def next(self):
        """Handle next track action."""
        track = self.playlist_manager.get_current_track()
        if self.moc_sync.use_moc and not self._is_video_track(track):
                # Use MOC for audio files
                # moc_sync.next_track() handles checking for next track and stopping if needed
                self.moc_sync.next_track()
        else:
            # Get next track (this updates current_index internally)
            next_track = self.playlist_manager.get_next_track()
            if next_track:
                self.play_current_track()
            else:
                # No next track - stop playback
                logger.debug("No next track available, stopping playback")
                self.stop()
    
    def previous(self):
        """Handle previous track action."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.previous_track()
        else:
            # Use internal player for video files
            prev_track = self.playlist_manager.get_previous_track()
            if prev_track:
                self.play_current_track()
    
    def seek(self, position: float):
        """Handle seek action - UI already updated, just perform the seek."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Use MOC for audio files - force seek since this is user-initiated
            self.moc_sync.seek(position, force=True)
        else:
            # Use internal player for video files
            self.player.seek(position)
    
    def get_current_duration(self) -> float:
        """Get current track duration from the active player."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Use cached duration if available, otherwise get from MOC
            return self.moc_sync.get_cached_duration()
        else:
            # Get duration from internal player
            return self.player.get_duration()
    
    def get_current_position(self) -> float:
        """Get current track position from the active player."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Get position from MOC
            return self.moc_sync.get_cached_position()
        else:
            # Get position from internal player
            return self.player.get_position()
    
    def is_playing(self) -> bool:
        """Check if playback is currently active."""
        track = self.playlist_manager.get_current_track()
        if not self._is_video_track(track):
            # Check MOC state
            moc_status = self.moc_controller.get_status(force_refresh=False)
            if moc_status:
                return moc_status.get("state", "STOP") == "PLAY"
            return False
        else:
            # Check internal player state
            return self.player.is_playing
    
    def cleanup(self):
        """Cleanup all playback resources."""
        self.player.cleanup()
    
    def _on_player_state_changed(self, playing: bool):
        """Forward player state change to callback."""
        if self.on_state_changed:
            self.on_state_changed(playing)
    
    def _on_player_position_changed(self, position: float):
        """Forward player position change to callback."""
        if self.on_position_changed:
            self.on_position_changed(position)
    
    def _on_player_track_finished(self):
        """Forward player track finished to callback."""
        if self.on_track_finished:
            self.on_track_finished()
    
    def _on_player_track_loaded(self):
        """Forward player track loaded to callback."""
        if self.on_track_loaded:
            self.on_track_loaded()
    
    def _stop_internal_player(self):
        """Stop internal GStreamer player if it's active."""
        if self.player.is_playing or self.player.current_track:
            self.player.stop()
    
    def _stop_all_players(self):
        """Stop all players (MOC and internal) before starting a new track."""
        # Stop internal player
        self._stop_internal_player()
        
        # Stop MOC if playing
        self.moc_sync.stop()
    
    def play_random_track(self):
        """Play a random track from the current playlist (for video files only)."""
        import random
        tracks = self.playlist_manager.get_playlist()
        if not tracks:
            return
        current_index = self.playlist_manager.get_current_index()
        if len(tracks) == 1:
            new_index = 0
        else:
            indices = [i for i in range(len(tracks)) if i != current_index]
            if not indices:
                return
            new_index = random.choice(indices)
        self.playlist_manager.set_current_index(new_index)
        self.play_current_track()

