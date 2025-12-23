# GTK Music Player with Bluetooth Streaming

A lightweight, modular music player built with GTK4 and Python that manages your local music library and handles Bluetooth audio streaming from mobile devices. Uses GStreamer with ALSA sink for reliable audio output.

## Features

- **Professional Audio Quality**: High-fidelity audio playback with:
  - 24-bit PCM audio processing
  - 44.1 kHz sample rate (CD quality)
  - Stereo (2-channel) output
  - FLAC bitstream decoding support
  - Automatic format conversion and resampling for consistent quality
- **Modular Dockable Panels**: Each panel (Library, Playlist, Now Playing, Bluetooth) can be detached as a separate window and rearranged
- **GStreamer + ALSA Playback**: Reliable audio playback using GStreamer with direct ALSA output and professional audio processing pipeline
- **Folder-Based Library Browser**: Browse your music library using the original folder structure from your Music directory
- **Touch-Friendly Interface**: Large buttons, increased row heights, and generous spacing optimized for touch screens
- **Enhanced Playlist Management**: 
  - Double-click tracks/folders to add to playlist and play
  - Right-click context menus for adding, removing, and reordering tracks
  - Save and load custom playlists
- **Bluetooth Speaker Mode**: Act as a Bluetooth audio receiver - stream audio from mobile phones to your speaker jack
- **Search**: Search and filter your music collection
- **Metadata Display**: Beautiful GTK4 interface with album art and track information
- **Layout Persistence**: Panel layout is saved and restored between sessions
- **Smart Track Loading**: Waits for tracks to fully load before playback to prevent audio glitches

## Requirements

### Gentoo Linux Dependencies

Install the following packages using `emerge`:

```bash
# Core GTK / GStreamer (required for playback)
# Base plugins provide essential codecs (WAV, OGG, etc.)
# Good plugins provide additional open formats (Opus, etc.)
# Bad plugins provide additional formats (WMA, APE, ALAC, etc.)
# Ugly plugins provide patented formats (MP3, AAC via alternative codecs)
emerge -av \
  media-libs/gstreamer \
  media-libs/gst-plugins-base \
  media-libs/gst-plugins-good \
  media-libs/gst-plugins-bad \
  media-libs/gst-plugins-ugly \
  media-plugins/gst-plugins-mpg123 \
  media-plugins/gst-plugins-faac \
  media-plugins/gst-plugins-flac \
  media-plugins/gst-plugins-openh264 \
  media-plugins/gst-plugins-bluez

# Audio stack
emerge -av media-libs/alsa-lib

# Bluetooth support
emerge -av net-wireless/bluez

# Audio system (choose one or both)
# Note: GStreamer BlueZ plugin works independently, but these provide additional routing options
emerge -av media-video/pipewire     # recommended
# or
emerge -av media-sound/pulseaudio

# Python bindings / libraries
emerge -av dev-python/pygobject dev-python/mutagen dev-python/dbus-python

# Optional but recommended: extra format support and tools
emerge -av media-video/ffmpeg dev-util/gst-devtools
```

### Python Dependencies

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Contents of `requirements.txt`:
```
PyGObject
mutagen
dbus-python
```

## Installation

1. Clone or download this repository
2. Install system dependencies (see above)
3. Install Python dependencies: `pip install -r requirements.txt`

## Usage

Run the application:

```bash
python main.py
```

### Music Library

The player automatically scans `~/Music` and `~/Musik` directories for audio files. 

**Supported Formats (~90% of common audio formats):**

**Lossy Formats:**
- **MP3** - MPEG Audio Layer 3 (most common)
- **AAC/M4A** - Advanced Audio Coding (iTunes/Apple)
- **OGG Vorbis** - Open source lossy format
- **Opus** - Modern efficient codec
- **WMA** - Windows Media Audio

**Lossless Formats:**
- **FLAC** - Free Lossless Audio Codec (with full metadata support and 24-bit bitstream decoding)
- **WAV** - Uncompressed waveform audio
- **AIFF** - Audio Interchange File Format
- **ALAC** - Apple Lossless (also uses .m4a extension)
- **APE** - Monkey's Audio

**Container Formats:**
- **MP4** - MPEG-4 container (may contain AAC/ALAC audio)
- **MKV** - Matroska container (may contain various audio codecs)
- **WebM** - WebM container (may contain Opus/Vorbis audio)

**Note:** If a format is not directly supported by GStreamer, the player can use FFmpeg as a fallback decoder (if installed). This ensures maximum compatibility with rare or proprietary formats.

**Metadata Extraction:**
The player uses a generic, format-agnostic metadata extraction system that works across all audio formats:
- Automatically detects and extracts metadata from FLAC (Vorbis comments), MP3 (ID3), MP4 (iTunes tags), OGG, and other formats
- Extracts title, artist, album, album artist, genre, year, track number, and duration
- Falls back to filename if metadata is missing, ensuring tracks are always identifiable
- Supports album art extraction from embedded cover images

**Audio Quality:**
All audio is processed and output at professional quality:
- **24-bit PCM** (S24LE format) for maximum dynamic range
- **44.1 kHz sample rate** (CD quality standard)
- **Stereo (2-channel)** output
- Automatic format conversion and resampling ensures consistent quality regardless of source format
- FLAC files are decoded from their native bitstream format and processed at full quality

**Library Indexing:**
- The library index is automatically saved to `~/.config/musicplayer/library_index.json`
- On startup, the index is loaded from disk for instant access
- Only new or modified files are rescanned, making subsequent scans much faster
- The index tracks file modification times to detect changes

### Dockable Panels

The application uses a modular panel system. Each panel has a header with:
- **Title**: Shows the panel name
- **Detach Button**: Click to pop out the panel as a separate window

Panels:
- **Library**: Browse your music using the original folder structure from your Music directory
- **Playlist**: View and manage your current queue with touch-friendly list items
- **Now Playing**: Display album art and track metadata
- **Bluetooth**: Manage Bluetooth connections and Speaker Mode

Panels can be resized by dragging the dividers between them. Layout is saved automatically.

### Adding Music to Playlist

From the Library panel:
- **Double-click** a track to replace playlist and play
- **Double-click** a folder to add all tracks in that folder (and subfolders) and play
- **Right-click** for context menu:
  - "Play Now" / "Play Folder" - Replace playlist and play
  - "Add to Playlist" / "Add Folder to Playlist" - Append without playing

From the Playlist panel:
- **Double-click** a track to play it
- **Right-click** for context menu:
  - "Play" - Play the selected track
  - "Remove" - Remove from playlist
  - "Move Up/Down" - Reorder tracks
  - "Clear Playlist" - Remove all tracks
  - "Save Playlist..." - Save as named playlist

### Bluetooth Speaker Mode

To use your computer as a Bluetooth speaker:

1. Click **"Enable Speaker Mode"** in the Bluetooth panel
2. Your computer becomes discoverable as "Music Player Speaker"
3. On your mobile device, scan for and pair with your computer
4. Connect and select your computer as the audio output
5. Audio from your phone will stream through your computer's speakers

**Requirements for Bluetooth audio:**
- BlueZ daemon running (`systemctl start bluetooth`)
- GStreamer BlueZ plugin (recommended): `media-plugins/gst-plugins-bluez`
  - Provides native GStreamer integration with BlueZ D-Bus for A2DP audio
  - Automatically handles audio routing when devices connect
- Alternative: PipeWire or PulseAudio for audio routing (if GStreamer BlueZ plugin not available)
- Bluetooth adapter that supports A2DP sink profile

**Bluetooth Implementation:**
- Uses BlueZ D-Bus API for device management (pairing, connection, discovery)
- **Standards-Compliant Implementation**: Fully compliant with BlueZ Agent1 interface specification
  - Proper D-Bus method signatures matching BlueZ specifications
  - Correct error handling with BlueZ-specific D-Bus exceptions
  - Proper agent registration and cleanup on shutdown
- **Pairing Confirmations**: Full support for modern Bluetooth pairing with passkey/PIN confirmations
  - Automatically handles passkey display and confirmation dialogs
  - Supports 6-digit passkey matching (Numeric Comparison pairing, 000000-999999)
  - Supports PIN code entry when required (4-16 digits, validated)
  - Shows authorization dialogs for device connections
  - Proper validation of all pairing inputs according to Bluetooth standards
- **Device Trust Management**: Automatically trusts devices after successful pairing
  - Trusted devices can reconnect automatically without user intervention
  - Follows Bluetooth security best practices
- **Connection State Management**: Robust handling of connection state transitions
  - Proper handling of pairing, connection, and disconnection states
  - Signal-based property change monitoring
  - Clean resource management and cleanup
- **A2DP Sink Profile**: Verifies A2DP sink profile availability before enabling
  - Prefers GStreamer BlueZ plugin for audio streaming when available
  - Falls back to PipeWire/PulseAudio routing if GStreamer plugin not installed
  - All Bluetooth operations use the official BlueZ library via D-Bus

## Project Structure

```
MusicPlayer/
├── main.py                    # Application entry point
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── ui/                        # UI components
│   ├── main_window.py         # Main window with dockable panels
│   ├── dock_manager.py        # Panel docking and layout management
│   └── components/            # Reusable UI components
│       ├── library_browser.py # Library tree view with context menu
│       ├── playlist_view.py   # Playlist list view with context menu
│       ├── player_controls.py # Playback controls
│       ├── metadata_panel.py  # Track metadata and album art
│       └── bluetooth_panel.py # Bluetooth and Speaker Mode controls
├── core/                      # Core functionality
│   ├── music_library.py       # Library scanning and indexing
│   ├── audio_player.py        # GStreamer-based audio player with ALSA
│   ├── playlist_manager.py    # Playlist handling and persistence
│   ├── metadata.py            # Audio file metadata extraction
│   ├── bluetooth_manager.py   # BlueZ D-Bus integration
│   └── bluetooth_sink.py      # Bluetooth A2DP sink mode
└── ~/.config/musicplayer/     # User configuration
    └── layout.json            # Saved panel layout
```

## Troubleshooting

### No sound output
1. Check that GStreamer ALSA plugin is installed: `gst-inspect-1.0 alsasink`
2. Verify ALSA is working: `aplay -l`
3. Check GStreamer can play audio: `gst-launch-1.0 audiotestsrc ! alsasink`

### Bluetooth not working
1. Ensure BlueZ is running: `systemctl status bluetooth`
2. Check adapter is powered: `bluetoothctl power on`
3. Verify PipeWire/PulseAudio Bluetooth modules are loaded

### Bluetooth device refresh errors
If you see errors like `module 'dbus' has no attribute 'UTF8String'`:
- This is fixed in the current version - the code now uses modern dbus-python APIs
- Ensure you have the latest version of `dbus-python` installed
- The code automatically handles dbus type conversions for compatibility

### FLAC playback not working
If you see errors like "Missing decoder: Free Lossless Audio Codec (FLAC)":

1. **Install the FLAC plugin package**:
   ```bash
   emerge -av media-plugins/gst-plugins-flac
   ```

2. **Verify FLAC decoder is available**:
   ```bash
   gst-inspect-1.0 flacdec
   ```
   This should show information about the FLAC decoder. If it says "No such element", the plugin is not installed correctly.

3. **Alternative: Check all available FLAC-related plugins**:
   ```bash
   gst-inspect-1.0 | grep -i flac
   ```

### Panel layout issues
Delete `~/.config/musicplayer/layout.json` to reset to default layout.

## License

This project is open source and available for personal use.
