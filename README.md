# GTK Music Player with Bluetooth Streaming

A lightweight, modular music player built with GTK4 and Python that manages your local music library and handles Bluetooth audio streaming from mobile devices. Uses GStreamer with ALSA sink for reliable audio output.

## Features

- **Modular Dockable Panels**: Each panel (Library, Playlist, Now Playing, Bluetooth) can be detached as a separate window and rearranged
- **GStreamer + ALSA Playback**: Reliable audio playback using GStreamer with direct ALSA output
- **Browse and Play**: Browse your local music library (`~/Music` and `~/Musik`)
- **Enhanced Playlist Management**: 
  - Double-click tracks/albums to add to playlist and play
  - Right-click context menus for adding, removing, and reordering tracks
  - Save and load custom playlists
- **Bluetooth Speaker Mode**: Act as a Bluetooth audio receiver - stream audio from mobile phones to your speaker jack
- **Search**: Search and filter your music collection
- **Metadata Display**: Beautiful GTK4 interface with album art and track information
- **Layout Persistence**: Panel layout is saved and restored between sessions

## Requirements

### Gentoo Linux Dependencies

Install the following packages using `emerge`:

```bash
# GStreamer and plugins (required for playback)
emerge -av media-libs/gstreamer
emerge -av media-plugins/gst-plugins-base
emerge -av media-plugins/gst-plugins-good
emerge -av media-plugins/gst-plugins-bad
emerge -av media-plugins/gst-plugins-alsa  # ALSA output

# Bluetooth support
emerge -av net-wireless/bluez

# Audio system (choose one or both)
emerge -av media-sound/pulseaudio  # or
emerge -av media-video/pipewire

# Python and GTK
emerge -av dev-python/pygobject
emerge -av dev-python/mutagen
emerge -av dev-python/dbus-python

# ffmpeg for format support (optional but recommended)
emerge -av media-video/ffmpeg
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

The player automatically scans `~/Music` and `~/Musik` directories for audio files. Supported formats include:
- MP3
- FLAC  
- OGG
- M4A/AAC
- WAV
- Any format supported by GStreamer

### Dockable Panels

The application uses a modular panel system. Each panel has a header with:
- **Title**: Shows the panel name
- **Detach Button**: Click to pop out the panel as a separate window

Panels:
- **Library**: Browse artists, albums, and tracks
- **Playlist**: View and manage your current queue
- **Now Playing**: Display album art and track metadata
- **Bluetooth**: Manage Bluetooth connections and Speaker Mode

Panels can be resized by dragging the dividers between them. Layout is saved automatically.

### Adding Music to Playlist

From the Library panel:
- **Double-click** a track to replace playlist and play
- **Double-click** an album to add all tracks and play
- **Right-click** for context menu:
  - "Play Now" - Replace playlist and play
  - "Add to Playlist" - Append without playing

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
- PipeWire or PulseAudio running for audio routing
- Bluetooth adapter that supports A2DP sink profile

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

### Panel layout issues
Delete `~/.config/musicplayer/layout.json` to reset to default layout.

## License

This project is open source and available for personal use.
