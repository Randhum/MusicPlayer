"""Playback controller - handles all playback operations."""

from pathlib import Path
from typing import Optional, Callable

from core.metadata import TrackMetadata
from core.logging import get_logger

logger = get_logger(__name__)


class PlaybackController:
    """Controller for managing playback operations."""
    
    def __init__(
        self,
        playlist_manager,
        moc_sync,
        player,
        player_controls,
        metadata_panel,
        playlist_view,
        mpris2,
        is_video_track: Callable,
        normalize_path: Callable,
        update_playlist_view: Callable,
        update_mpris2_navigation: Callable,
    ):
        """
        Initialize playback controller.
        
        Args:
            playlist_manager: PlaylistManager instance
            moc_sync: MocSyncHelper instance
            player: AudioPlayer instance
            player_controls: PlayerControls instance
            metadata_panel: MetadataPanel instance
            playlist_view: PlaylistView instance
            mpris2: MPRIS2Manager instance
            is_video_track: Function to check if track is video
            normalize_path: Function to normalize file paths
            update_playlist_view: Function to update playlist view
            update_mpris2_navigation: Function to update MPRIS2 navigation
        """
        self.playlist_manager = playlist_manager
        self.moc_sync = moc_sync
        self.player = player
        self.player_controls = player_controls
        self.metadata_panel = metadata_panel
        self.playlist_view = playlist_view
        self.mpris2 = mpris2
        self.is_video_track = is_video_track
        self.normalize_path = normalize_path
        self.update_playlist_view = update_playlist_view
        self.update_mpris2_navigation = update_mpris2_navigation
    
    def play(self, selected_track_index: Optional[int] = None):
        """
        Handle play button click.
        
        Args:
            selected_track_index: Optional index of selected track in playlist
        """
        # Step 1: Check if we can resume a paused track
        current_track = self.playlist_manager.get_current_track()
        
        if current_track:
            # Check if this track is already playing - do nothing
            if self._is_track_playing(current_track):
                return
            
            # Check if this track is paused and can be resumed
            if self._can_resume_track(current_track):
                self.resume(current_track)
                return
        
        # Step 2: Check if there's a selected track in the playlist
        if selected_track_index is not None and selected_track_index >= 0:
            playlist = self.playlist_manager.get_playlist()
            if 0 <= selected_track_index < len(playlist):
                self.playlist_manager.set_current_index(selected_track_index)
                self.update_playlist_view()
                self.play_current_track()
                return
        
        # Step 3: Play current track (if exists)
        if current_track:
            self.play_current_track()
    
    def pause(self):
        """Handle pause button click."""
        track = self.playlist_manager.get_current_track()
        if not self.is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.pause()
            self.player_controls.set_playing(False)
        else:
            # Use internal player for video files
            self.player.pause()
            self.player_controls.set_playing(False)
    
    def stop(self):
        """Handle stop button click."""
        track = self.playlist_manager.get_current_track()
        if not self.is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.stop()
        else:
            # Use internal player for video files
            self.player.stop()
        
        # Update player controls state
        self.player_controls.set_playing(False)
        
        # Update MPRIS2 playback status
        if self.mpris2:
            self.mpris2.update_playback_status(False, is_paused=False)
        self.update_playlist_view()
        self.update_mpris2_navigation()
    
    def next(self):
        """Handle next button click."""
        track = self.playlist_manager.get_current_track()
        if not self.is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.next_track()
        else:
            # Use internal player for video files
            if self.moc_sync.get_shuffle_enabled():
                self._play_random_track()
            else:
                next_track = self.playlist_manager.get_next_track()
                if next_track:
                    self.update_playlist_view()
                    self.play_current_track()
        # Update MPRIS2 navigation capabilities after track change
        self.update_mpris2_navigation()
    
    def previous(self):
        """Handle previous button click."""
        track = self.playlist_manager.get_current_track()
        if not self.is_video_track(track):
            # Use MOC for audio files
            self.moc_sync.previous_track()
        else:
            # Use internal player for video files
            prev_track = self.playlist_manager.get_previous_track()
            if prev_track:
                self.update_playlist_view()
                self.play_current_track()
        # Update MPRIS2 navigation capabilities after track change
        self.update_mpris2_navigation()
    
    def seek(self, position: float):
        """Handle seek operation."""
        track = self.playlist_manager.get_current_track()
        if not self.is_video_track(track):
            # Use MOC for audio files - force seek since this is user-initiated
            self.moc_sync.seek(position, force=True)
        else:
            # Use internal player for video files
            self.player.seek(position)
    
    def play_current_track(self):
        """Play the current track from playlist."""
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
        if not self.is_video_track(track):
            # Use MOC for audio files
            self._stop_internal_player()
            self.moc_sync.play_track()
            self.player_controls.set_playing(True)
        else:
            # Use internal player for video files
            self.player.load_track(track)
            self.player.play()
            self.player_controls.set_playing(True)
            
            # Sync MOC playlist (but don't play in MOC for video files)
            if hasattr(self.moc_sync, 'sync_enabled'):
                self.moc_sync.sync_enabled = True
                self.moc_sync.sync_playlist_to_moc(start_playback=False)
        
        self.metadata_panel.set_track(track)
        
        # Update MPRIS2 metadata and navigation capabilities
        if self.mpris2:
            self.mpris2.update_metadata(track)
            self.update_mpris2_navigation()
    
    def resume(self, track: TrackMetadata):
        """
        Resume playback of a paused track.
        
        Args:
            track: The track to resume
        """
        # Reset user interaction state to ensure duration labels update properly
        self.player_controls._user_interacting = False
        
        if not self.is_video_track(track):
            # Resume MOC playback
            self._stop_internal_player()
            self.moc_sync.play()
            self.player_controls.set_playing(True)
        else:
            # Resume internal player playback
            self.player.play()
            self.player_controls.set_playing(True)
        
        # Update metadata panel and MPRIS2 when resuming
        self.metadata_panel.set_track(track)
        if self.mpris2:
            self.mpris2.update_metadata(track)
    
    def _is_track_playing(self, track: TrackMetadata) -> bool:
        """Check if a track is currently playing."""
        if not self.is_video_track(track):
            # Check if MOC is playing this track
            self._stop_internal_player()
            moc_status = self.moc_sync.moc_controller.get_status(force_refresh=False)
            if moc_status:
                moc_state = moc_status.get("state", "STOP")
                moc_file = moc_status.get("file_path")
                # Normalize paths for comparison
                if moc_file and track.file_path:
                    moc_file_abs = self.normalize_path(moc_file)
                    track_file_abs = self.normalize_path(track.file_path)
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        return moc_state == "PLAY"
            return False
        else:
            # Check if internal player is playing this track
            if self.player.current_track and self.player.is_playing:
                current_file_abs = self.normalize_path(self.player.current_track.file_path)
                track_file_abs = self.normalize_path(track.file_path)
                if current_file_abs and track_file_abs and current_file_abs == track_file_abs:
                    return True
            return False
    
    def _can_resume_track(self, track: TrackMetadata) -> bool:
        """Check if a track is currently paused and can be resumed."""
        if not self.is_video_track(track):
            # Check if MOC is paused on this track
            self._stop_internal_player()
            moc_status = self.moc_sync.moc_controller.get_status(force_refresh=True)
            if moc_status:
                moc_state = moc_status.get("state", "STOP")
                moc_file = moc_status.get("file_path")
                # Normalize paths for comparison
                if moc_file and track.file_path:
                    moc_file_abs = self.normalize_path(moc_file)
                    track_file_abs = self.normalize_path(track.file_path)
                    if moc_file_abs and track_file_abs and moc_file_abs == track_file_abs:
                        return moc_state == "PAUSE"
            return False
        else:
            # Check if internal player is paused on this track
            if self.player.current_track:
                current_file_abs = self.normalize_path(self.player.current_track.file_path)
                track_file_abs = self.normalize_path(track.file_path)
                if current_file_abs and track_file_abs and current_file_abs == track_file_abs:
                    return not self.player.is_playing
            return False
    
    def _stop_internal_player(self):
        """Stop internal GStreamer player if it's active."""
        if self.player.is_playing or self.player.current_track:
            self.player.stop()
    
    def _stop_all_players(self):
        """Stop all players (MOC and internal) before starting a new track."""
        # Stop internal player
        self._stop_internal_player()
        
        # Stop MOC if playing
        if hasattr(self.moc_sync, 'stop'):
            self.moc_sync.stop()
    
    def _play_random_track(self):
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
        self.update_playlist_view()
        self.play_current_track()

