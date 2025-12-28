"""MOC synchronization helper."""

from pathlib import Path
from typing import Optional, Callable
import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib
from core.metadata import TrackMetadata
from core.config import get_config
from core.moc_controller import MocController
from core.logging import get_logger

logger = get_logger(__name__)

class MocSyncHelper:
    def __init__(self, moc_controller: MocController, playlist_manager, player_controls,
            metadata_panel, playlist_view, is_video_track_fn: Callable[[Optional[TrackMetadata]], bool], mpris2=None):
        self.moc_controller = moc_controller
        self.playlist_manager = playlist_manager
        self.player_controls = player_controls
        self.metadata_panel = metadata_panel
        self.playlist_view = playlist_view
        self.is_video_track = is_video_track_fn
        self.mpris2 = mpris2
        self.use_moc = moc_controller.is_available()
        self.last_position = 0.0
        self.last_duration = 0.0
        self.last_file = None
        self.playlist_mtime = 0.0
        self.sync_enabled = True
        self.end_detected = False
        self._resuming = False
        self.shuffle_enabled = False
        self._seeking = False  # Flag to prevent update_status from overwriting position during seek
        self.on_track_finished = None
        self.on_shuffle_changed = None
        self._sync_timeout_id = None
        self._sync_pending = False
        self._sync_start_playback = False
        config = get_config()
        moc_playlist_path = config.moc_playlist_path
        if self.use_moc and moc_playlist_path.exists():
            try:
                self.playlist_mtime = moc_playlist_path.stat().st_mtime
            except OSError:
                self.playlist_mtime = 0.0
    
    def sync_add_track_file(self, index: int, track: TrackMetadata):
        self.playlist_manager.add_track_at_index_file(index, track)
        if self.use_moc and self.sync_enabled and not self.is_video_track(track):
            self.moc_controller.add_track_at_index_m3u(index, str(Path(track.file_path).resolve()))
    
    def sync_remove_track_file(self, index: int):
        self.playlist_manager.remove_track_at_index_file(index)
        if self.use_moc and self.sync_enabled:
            self.moc_controller.remove_track_at_index_m3u(index)
    
    def sync_move_track_file(self, from_index: int, to_index: int):
        self.playlist_manager.move_track_in_file(from_index, to_index)
        if self.use_moc and self.sync_enabled:
            self.moc_controller.move_track_in_m3u(from_index, to_index)
    
    def sync_jump_to_index_file(self, index: int, start_playback: bool = False):
        if not self.sync_enabled:
            return
        track = self.playlist_manager.get_track_at_index_file(index)
        if track and self.is_video_track(track):
            return
        self.moc_controller.jump_to_index(index, start_playback=start_playback)
    
    def initialize(self):
        if not self.use_moc:
            return False
        success, was_already_running = self.moc_controller.ensure_server()
        if not success:
            return False
        if was_already_running:
            logger.info("MOC server was already running - detecting current state")
            self._load_state_from_running_moc()
        self.moc_controller.enable_autonext()
        self.sync_shuffle_from_moc()
        tracks = self.playlist_manager.get_playlist()
        if tracks:
            current_index = self.playlist_manager.get_current_index()
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
            logger.info("Synced %d tracks to MOC - app is now orchestrator", len(tracks))
        return True
    
    def _load_state_from_running_moc(self):
        status = self.moc_controller.get_status(force_refresh=True)
        if not status:
            return
        current_file = status.get("file_path")
        moc_tracks, moc_index = self.moc_controller.get_playlist(current_file=current_file)
        if moc_tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(moc_tracks)
            if moc_index >= 0:
                self.playlist_manager.set_current_index(moc_index)
            self.playlist_view.set_playlist(moc_tracks, moc_index)
            logger.info("Loaded %d tracks from running MOC instance", len(moc_tracks))
        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        if file_path:
            self.last_file = file_path
            self.metadata_panel.set_track(TrackMetadata(file_path))
        if state == "PLAY":
            self.player_controls.set_playing(True)
        elif state == "PAUSE":
            self.player_controls.set_playing(False)
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))
        if duration > 0:
            self.player_controls.update_progress(position, duration)
        self.sync_shuffle_from_moc()
        logger.info("Loaded state from running MOC: %s, track: %s", state, file_path)
    
    def sync_shuffle_from_moc(self):
        """Sync shuffle state from MOC and store it locally."""
        moc_shuffle = self.moc_controller.get_shuffle_state()
        if moc_shuffle is not None:
            self.shuffle_enabled = moc_shuffle
    
    def set_shuffle_enabled(self, enabled: bool):
        self.shuffle_enabled = enabled
    
    def sync_playlist_to_moc(self, start_playback: bool = False):
        if not self.sync_enabled:
            return
        if self._sync_timeout_id is not None:
            GLib.source_remove(self._sync_timeout_id)
            self._sync_timeout_id = None
        self._sync_pending = True
        self._sync_start_playback = start_playback or self._sync_start_playback
        self._sync_timeout_id = GLib.timeout_add(300, self._do_sync_playlist_to_moc)
    
    def _do_sync_playlist_to_moc(self):
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
            self.moc_controller.set_playlist(tracks, current_index, start_playback=True)
        else:
            self.moc_controller.set_playlist(tracks, current_index, start_playback=False)
        return False
    
    def sync_playlist_for_playback(self):
        if not self.sync_enabled or self._resuming:
            return
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            current_track = self.playlist_manager.get_current_track()
            if moc_state == "PAUSE" and moc_file and current_track:
                if str(Path(moc_file).resolve()) == str(Path(current_track.file_path).resolve()):
                    return
            if moc_state == "PLAY" and moc_file and current_track and moc_file != current_track.file_path:
                self.sync_enabled = False
                return
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
    
    def load_playlist_from_moc(self):
        moc_tracks, moc_index = self.moc_controller.get_playlist()
        if moc_tracks:
            self.playlist_manager.clear()
            self.playlist_manager.add_tracks(moc_tracks)
            if moc_index >= 0:
                self.playlist_manager.set_current_index(moc_index)
            self.playlist_view.set_playlist(moc_tracks, moc_index)
            GLib.idle_add(self._load_metadata_async, 0)
        elif not moc_tracks:
            status = self.moc_controller.get_status()
            if status and status.get("state") in ("PLAY", "PAUSE") and status.get("file_path"):
                pass
    
    def _load_metadata_async(self, start_index: int = 0) -> bool:
        tracks = self.playlist_manager.get_playlist()
        if not tracks:
            return False
        batch_size = 10
        end_index = min(start_index + batch_size, len(tracks))
        for i in range(start_index, end_index):
            track = tracks[i]
            if not track or not track.file_path:
                continue
            if not track.title or track.title == Path(track.file_path).stem:
                try:
                    full_metadata = TrackMetadata(track.file_path)
                    for attr in ['title', 'artist', 'album', 'album_artist', 'track_number', 'duration', 'album_art_path', 'genre', 'year']:
                        setattr(track, attr, getattr(full_metadata, attr))
                except Exception as e:
                    logger.debug("Error loading metadata for %s: %s", track.file_path, e)
        self.playlist_view.set_playlist(tracks, self.playlist_manager.get_current_index())
        if end_index < len(tracks):
            GLib.idle_add(self._load_metadata_async, end_index)
            return False
        return False
    
    def update_status(self) -> bool:
        status = self.moc_controller.get_status()
        if not status:
            return True
        state = status.get("state", "STOP")
        file_path = status.get("file_path")
        position = float(status.get("position", 0.0))
        duration = float(status.get("duration", 0.0))
        
        # Don't update cached position if we're in the middle of a seek operation
        # This prevents periodic updates from overwriting the seeked position immediately
        if not self._seeking:
            self.last_position = position
        else:
            # While seeking, use the cached position (which is the exact seeked position)
            position = self.last_position
        # Always update duration
        self.last_duration = duration
        if self.last_file is None and file_path:
            self.last_file = file_path
        track = self.playlist_manager.get_current_track()
        if track and not self.is_video_track(track):
            self.player_controls.set_playing(state == "PLAY")
            if self.mpris2:
                self.mpris2.update_playback_status(state == "PLAY", is_paused=(state == "PAUSE"))
            if duration > 0:
                self.player_controls.update_progress(position, duration)
            elif position > 0:
                self.player_controls.update_progress(position, 0.0)
            if file_path and file_path != self.last_file and self.last_file is not None:
                if self._resuming:
                    self.last_file = file_path
                    self.end_detected = False
                    return True
                current_track = self.playlist_manager.get_current_track()
                if current_track and current_track.file_path:
                    if str(Path(current_track.file_path).resolve()) == str(Path(file_path).resolve()):
                        self.last_file = file_path
                        self.end_detected = False
                        return True
                self.last_file = file_path
                self.end_detected = False
                moc_tracks, moc_index = self.moc_controller.get_playlist(current_file=file_path)
                if moc_tracks:
                    self.playlist_manager.clear()
                    self.playlist_manager.add_tracks(moc_tracks)
                    found_index = -1
                    for idx, track_item in enumerate(moc_tracks):
                        if track_item.file_path == file_path:
                            found_index = idx
                            break
                    if found_index >= 0:
                        self.playlist_manager.set_current_index(found_index)
                        self.playlist_view.set_playlist(moc_tracks, found_index)
                    else:
                        if moc_index >= 0:
                            self.playlist_manager.set_current_index(moc_index)
                            self.playlist_view.set_playlist(moc_tracks, moc_index)
                        else:
                            self.playlist_view.set_playlist(moc_tracks, -1)
                    new_track = TrackMetadata(file_path)
                    self.metadata_panel.set_track(new_track)
                    if self.mpris2:
                        self.mpris2.update_metadata(new_track)
                else:
                    new_track = TrackMetadata(file_path)
                    self.metadata_panel.set_track(new_track)
                    if self.mpris2:
                        self.mpris2.update_metadata(new_track)
                    playlist = self.playlist_manager.get_playlist()
                    found_in_playlist = False
                    for idx, track_item in enumerate(playlist):
                        if track_item.file_path == file_path:
                            self.playlist_manager.set_current_index(idx)
                            self.playlist_view.set_playlist(playlist, idx)
                            found_in_playlist = True
                            break
                    if not found_in_playlist and self.on_track_finished:
                        self.on_track_finished()
            playlist = self.playlist_manager.get_playlist()
            current_index = self.playlist_manager.get_current_index()
            if duration > 0 and file_path == self.last_file and not self.end_detected:
                if position >= duration - 0.5:
                    self.end_detected = True
                    if current_index < len(playlist) - 1:
                        if self.on_track_finished:
                            self.on_track_finished()
                    elif state == "STOP":
                        self.playlist_manager.set_current_index(-1)
                        self.playlist_view.set_playlist(playlist, -1)
            if duration > 0 and state == "STOP" and file_path == self.last_file and not self.end_detected:
                if position >= duration - 1.0:
                    if current_index < len(playlist) - 1:
                        if self.on_track_finished:
                            self.on_track_finished()
        else:
            if file_path and state == "PLAY":
                current_track = self.playlist_manager.get_current_track()
                if not current_track or file_path != current_track.file_path:
                    if self.sync_enabled:
                        self.sync_enabled = False
                    self.load_playlist_from_moc()
                    if file_path != self.last_file:
                        self.last_file = file_path
            elif state == "STOP":
                if not self.sync_enabled:
                    self.sync_enabled = True
        moc_shuffle = status.get("shuffle", False)
        if moc_shuffle != self.shuffle_enabled:
            self.set_shuffle_enabled(moc_shuffle)
            if self.on_shuffle_changed:
                self.on_shuffle_changed(moc_shuffle)
        try:
            config = get_config()
            moc_playlist_path = config.moc_playlist_path
            mtime = moc_playlist_path.stat().st_mtime if moc_playlist_path.exists() else self.playlist_mtime
        except OSError:
            mtime = self.playlist_mtime
        if mtime != self.playlist_mtime:
            self.playlist_mtime = mtime
            if not self.sync_enabled:
                self.load_playlist_from_moc()
        return True
    
    def reset_end_detection(self):
        self.end_detected = False
    
    def play(self):
        self._resuming = True
        current_track = self.playlist_manager.get_current_track()
        if current_track and current_track.file_path:
            self.last_file = current_track.file_path
        self.moc_controller.play()
        def clear_resuming():
            self._resuming = False
            return False
        GLib.timeout_add(1000, clear_resuming)
    
    def pause(self):
        self.moc_controller.pause()
    
    def stop(self):
        self.moc_controller.stop()
        self.playlist_manager.set_current_index(-1)
        self.playlist_view.set_playlist(self.playlist_manager.get_playlist(), -1)
    
    def next_track(self):
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        if current_index < len(tracks) - 1:
            new_index = current_index + 1
            self.playlist_manager.set_current_index(new_index)
            self.playlist_view.set_playlist(tracks, new_index)
            self.play_track()
        else:
            self.moc_controller.stop()
            self.playlist_manager.set_current_index(-1)
            self.playlist_view.set_playlist(tracks, -1)
    
    def previous_track(self):
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        if current_index > 0:
            new_index = current_index - 1
            self.playlist_manager.set_current_index(new_index)
            self.playlist_view.set_playlist(tracks, new_index)
            self.play_track()
    
    def play_track(self):
        track = self.playlist_manager.get_current_track()
        if not track or self.is_video_track(track):
            return
        file_path = Path(track.file_path)
        if not file_path.exists() or not file_path.is_file():
            logger.error("Track file does not exist: %s", track.file_path)
            return
        moc_status = self.moc_controller.get_status(force_refresh=False)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            if moc_state == "PLAY" and moc_file and moc_file != track.file_path:
                self.moc_controller.stop()
        self.sync_playlist_for_playback()
        if self.shuffle_enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        tracks = self.playlist_manager.get_playlist()
        current_index = self.playlist_manager.get_current_index()
        self.playlist_view.set_playlist(tracks, current_index)
        self.metadata_panel.set_track(track)
        if self.mpris2:
            self.mpris2.update_metadata(track)
        self.reset_end_detection()
    
    def set_shuffle(self, enabled: bool):
        self.shuffle_enabled = enabled
        if enabled:
            self.moc_controller.enable_shuffle()
        else:
            self.moc_controller.disable_shuffle()
        if self.on_shuffle_changed:
            self.on_shuffle_changed(enabled)
    
    def get_shuffle_enabled(self) -> bool:
        return self.shuffle_enabled
    
    def get_autonext_enabled(self) -> bool:
        autonext_state = self.moc_controller.get_autonext_state()
        return autonext_state if autonext_state is not None else True
    
    def set_autonext_enabled(self, enabled: bool):
        if enabled:
            self.moc_controller.enable_autonext()
        else:
            self.moc_controller.disable_autonext()
    
    def toggle_autonext(self) -> bool:
        new_state = not self.get_autonext_enabled()
        self.set_autonext_enabled(new_state)
        return new_state
    
    def handle_track_finished(self):
        self.end_detected = False
        tracks = self.playlist_manager.get_playlist()
        current_track = self.playlist_manager.get_current_track()
        moc_status = self.moc_controller.get_status(force_refresh=True)
        if moc_status:
            moc_state = moc_status.get("state", "STOP")
            moc_file = moc_status.get("file_path")
            if moc_state == "PLAY" and moc_file and current_track and moc_file != current_track.file_path:
                for idx, track_item in enumerate(tracks):
                    if track_item.file_path == moc_file:
                        self.playlist_manager.set_current_index(idx)
                        self.playlist_view.set_playlist(tracks, idx)
                        self.metadata_panel.set_track(track_item)
                        if self.mpris2:
                            self.mpris2.update_metadata(track_item)
                        self.last_file = moc_file
                        self.end_detected = False
                        return
    
    def get_cached_duration(self) -> float:
        if self.last_duration > 0:
            return self.last_duration
        status = self.moc_controller.get_status(force_refresh=False)
        if status:
            return float(status.get("duration", 0.0))
        return 0.0
    
    def get_cached_position(self) -> float:
        return self.last_position
    
    def seek(self, position: float, force: bool = False):
        position = max(0.0, position)
        duration = self.get_cached_duration()
        if duration > 0:
            position = min(position, duration)
        current_pos = self.get_cached_position()
        if current_pos == 0.0:
            status = self.moc_controller.get_status(force_refresh=False)
            if status:
                current_pos = float(status.get("position", 0.0))
        delta = position - current_pos
        if force or abs(delta) >= 0.5:
            # Set seeking flag to prevent update_status from overwriting position
            self._seeking = True
            # Update cached position immediately to the exact seeked position
            # This ensures UI updates immediately without waiting for MOC response
            self.last_position = position
            
            self.moc_controller.seek_relative(delta)
            if duration > 0:
                self.reset_end_detection()
            
            # Get actual position from MOC (may be slightly different)
            status_after = self.moc_controller.get_status(force_refresh=True)
            if status_after:
                actual_position = float(status_after.get("position", position))
                # Only update if very close (within 0.5s) to prevent jumping
                if abs(actual_position - position) < 0.5:
                    self.last_position = actual_position
                # Otherwise keep the exact seeked position
            
            # Clear seeking flag after a brief delay to allow normal updates
            def clear_seeking():
                self._seeking = False
                return False
            GLib.timeout_add(300, clear_seeking)  # 300ms grace period
            
            logger.debug("Seeked to position %.2f (delta: %.2f, forced: %s)", position, delta, force)
        else:
            logger.debug("Seek skipped - delta too small: %.2f seconds", abs(delta))
