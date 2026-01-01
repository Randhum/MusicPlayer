# Architecture Refactoring - Tracking Document

## Goal
Ensure all calls from main → core are consistent, with no duplications, clear distinction, perfect efficiency, and zero leftovers.

## Current Architecture Issues

### 1. Component Initialization Chain

**Current State:**
- `main.py` → Creates `MainWindow`
- `MainWindow.__init__()` → Creates core components (PlaylistManager, AudioPlayer, etc.)
- `MainWindow._create_ui()` → Creates UI components (PlaylistView, PlayerControls, etc.)
- `MainWindow` → Creates `MocSyncHelper` with references to both core and UI components

**Issues:**
- ❌ `PlaylistView` no longer has `playlist_manager` attribute (was removed)
- ❌ `MocSyncHelper` tries to access `playlist_view.playlist_manager` (doesn't exist)
- ❌ `MocSyncHelper` calls `playlist_view.get_playlist()` but method doesn't exist
- ❌ `MainWindow` duplicates playlist operations (calls `playlist_manager` + `_update_playlist_view()`)

### 2. PlaylistView Component

**Current State:**
- `PlaylistView.__init__()` takes no parameters
- Only has `set_playlist()` and `set_current_index()` methods
- No access to `PlaylistManager` internally

**Expected by Other Components:**
- `MocSyncHelper` expects: `get_playlist()`, `get_current_index()`, `get_current_track()`, `get_next_track()`, `get_previous_track()`
- `MainWindow` expects: Direct playlist operations through signals

**Issues:**
- ❌ Missing methods that `MocSyncHelper` needs
- ❌ No connection to `PlaylistManager` for data operations

### 3. MocSyncHelper Component

**Current State:**
- Has both `playlist_manager` and `playlist_view` as attributes
- Tries to use `playlist_view.get_playlist()` (doesn't exist)
- Tries to use `playlist_view.playlist_manager` (doesn't exist)

**Issues:**
- ❌ Inconsistent access patterns
- ❌ Should use `playlist_manager` directly for data operations
- ❌ Should use `playlist_view` only for UI updates

### 4. MainWindow Component

**Current State:**
- Directly calls `playlist_manager` methods
- Then calls `_update_playlist_view()` to sync UI
- Duplicates playlist state management

**Issues:**
- ❌ Duplication: Every playlist operation requires two calls
- ❌ Inconsistent: Some places update directly, others through signals
- ❌ Should delegate to `PlaylistView` which should handle both data and UI

## Proposed Architecture

### Component Responsibilities

1. **PlaylistManager (core/)** - Data layer
   - Manages in-memory playlist state
   - Persists to JSON file
   - Provides: `get_playlist()`, `get_current_index()`, `add_track()`, `remove_track()`, etc.

2. **PlaylistView (ui/components/)** - View layer
   - Displays playlist in UI
   - Handles user interactions (clicks, context menu)
   - **SHOULD** have reference to `PlaylistManager` for data operations
   - **SHOULD** provide wrapper methods: `get_playlist()`, `get_current_index()`, etc.
   - **SHOULD** automatically sync UI when playlist changes

3. **MocSyncHelper (ui/)** - Integration layer
   - Syncs between MOC and application playlist
   - Uses `PlaylistManager` for data operations
   - Uses `PlaylistView` for UI updates
   - Uses `PlaylistView` wrapper methods for reading state

4. **MainWindow (ui/)** - Orchestration layer
   - Creates and connects all components
   - Handles high-level application logic
   - **SHOULD** delegate playlist operations to `PlaylistView`
   - **SHOULD NOT** directly manipulate `PlaylistManager` (except for initialization)

## Refactoring Plan

### Phase 1: Fix PlaylistView
- [ ] Add `playlist_manager` parameter to `__init__()`
- [ ] Add wrapper methods: `get_playlist()`, `get_current_index()`, `get_current_track()`, `get_next_track()`, `get_previous_track()`
- [ ] Add playlist operation methods: `add_track()`, `remove_track()`, `move_track()`, `clear()`
- [ ] Ensure all operations update both data and UI automatically

### Phase 2: Fix MocSyncHelper
- [ ] Remove all `playlist_view.playlist_manager` references
- [ ] Use `playlist_manager` directly for data operations
- [ ] Use `playlist_view` wrapper methods for reading state
- [ ] Use `playlist_view.set_playlist()` for UI updates

### Phase 3: Fix MainWindow
- [ ] Remove direct `playlist_manager` calls (except initialization)
- [ ] Use `playlist_view` methods for all playlist operations
- [ ] Remove `_update_playlist_view()` method (no longer needed)
- [ ] Connect signals to `playlist_view` methods

### Phase 4: Cleanup
- [ ] Remove unused methods
- [ ] Remove duplicate code
- [ ] Verify all components follow the architecture
- [ ] Update documentation

## Implementation Checklist

### Files to Modify

1. **ui/components/playlist_view.py**
   - [x] Add `playlist_manager` parameter to `__init__()`
   - [x] Add wrapper methods for reading state
   - [x] Add playlist operation methods
   - [x] Ensure automatic UI updates

2. **ui/moc_sync.py**
   - [x] Fix all `playlist_view.playlist_manager` → `playlist_manager`
   - [x] Fix all `playlist_view.get_*()` calls (ensure methods exist)
   - [x] Use public methods instead of private attributes
   - [x] Verify all methods work correctly

3. **ui/main_window.py**
   - [x] Pass `playlist_manager` to `PlaylistView.__init__()`
   - [x] Replace direct `playlist_manager` calls with `playlist_view` methods
   - [x] Remove `_update_playlist_view()` method
   - [x] Remove all `_update_playlist_view()` calls

4. **main.py**
   - [x] Verify no direct playlist operations (should be fine)

## Summary of Changes

### Completed ✅

1. **PlaylistView** - Now has:
   - `playlist_manager` parameter in `__init__()`
   - Wrapper methods: `get_playlist()`, `get_current_index()`, `get_current_track()`, `get_next_track()`, `get_previous_track()`
   - Playlist operation methods: `add_track()`, `add_tracks()`, `remove_track()`, `move_track()`, `clear()`
   - All operations automatically update both data (PlaylistManager) and UI

2. **MocSyncHelper** - Now:
   - Uses `playlist_manager` directly for data operations
   - Uses `playlist_view` wrapper methods for reading state
   - Uses `playlist_view.set_playlist()` for UI updates
   - No longer accesses `playlist_view.playlist_manager` (doesn't exist)

3. **MainWindow** - Now:
   - Passes `playlist_manager` to `PlaylistView.__init__()`
   - Uses `playlist_view` methods for all playlist operations
   - Removed `_update_playlist_view()` method entirely
   - Removed all `_update_playlist_view()` calls (24 instances)
   - No direct `playlist_manager` calls except in `load_playlist_from_moc()` (intentional bypass)

4. **main.py** - Fixed:
   - Uses `playlist_view.add_track()` instead of direct `playlist_manager` call
   - Removed `_update_playlist_view()` call

## Additional Fixes

### Playback Handling
- [x] Removed `_add_to_recent_files()` call (method doesn't exist)
- [x] Added `play_current_track()` method to `PlayerControls`
- [x] Connected `PlayerControls` to `MainWindow._play_current_track()` via callback
- [x] Updated `_on_playlist_track_activated()` to use `player_controls.play_current_track()`

### Playback Controls (Seek, Pause, Resume)
- [x] Fixed resume logic: 
  - Now properly handles PAUSE, PLAY, and STOP states
  - Checks if MOC is paused/playing on the current track before deciding action
  - If MOC is paused on current track, uses `--unpause` to resume from pause position
  - If MOC is stopped but was on current track, just calls `play()` to resume
  - Only calls `_play_current_track()` if MOC is on a different track or no track
- [x] Fixed seek/drag: 
  - Emit seek signal on every value change during drag for responsive seeking
  - Set `_seeking` flag first to prevent `update_status` from interfering
  - Use cached position when available to reduce status calls
  - Update cached position immediately after seek
  - Seek flag is cleared after 500ms delay to allow position to update
  - `update_status()` checks `_seeking` flag before updating position display
- [x] Fixed pause: 
  - UI state is updated immediately via `set_playing(False)` for immediate feedback
  - `update_status()` also updates UI state periodically
- [x] Fixed MOC `play()` method:
  - Now checks if MOC is paused and uses `--unpause` to resume from pause position
  - Otherwise uses `--play` to start/resume

### MPRIS2 Integration
- [x] Fixed MPRIS2 metadata update error:
  - Added proper error handling for file path resolution
  - Ensured all string values are non-empty before adding to metadata
  - Fixed PropertiesChanged signal emission by wrapping metadata in Variant
  - Added fallback error handling for D-Bus signal emission
  - Validates file_path exists before creating track ID
  - Handles empty strings and None values properly
  - Validates album art path exists before adding to metadata

## Testing Checklist

- [ ] Playlist operations work (add, remove, move, clear)
- [ ] MOC sync works (load from MOC, update to MOC)
- [ ] UI updates correctly when playlist changes
- [ ] No duplicate updates or sync loops
- [ ] All signals work correctly
- [ ] Playback works when track is activated from playlist
- [ ] MPRIS2 metadata updates without errors
- [ ] No leftover unused code

## Known Issues Fixed

### MPRIS2 Metadata TypeError
**Error:** `TypeError: Expected a string or unicode object` when updating metadata
**Root Cause:** 
- PropertiesChanged signal expects metadata dict to be wrapped in Variant
- Some metadata values could be empty strings or None
- File path resolution could fail for invalid paths

**Fix:**
- Wrap metadata dict in `dbus.types.Variant('a{sv}', value)` for PropertiesChanged
- Validate all string values are non-empty before adding to metadata
- Add error handling for file path resolution
- Validate album art path exists before adding
- Add fallback error handling for D-Bus signal emission

## Notes

- Keep JSON file as source of truth
- MOC M3U file should sync with JSON when MOC is enabled
- UI should always reflect current state
- No complex sync flags or debouncing needed
- MPRIS2 metadata must use proper D-Bus types and Variant wrapping

