# GTK Music Player with Bluetooth Streaming

A lightweight music player built with GTK4 and Python that manages your local music library and handles Bluetooth audio streaming from mobile devices. Uses GStreamer for reliable audio and video playback.

## Features

- **Automatic Format Handling**: GStreamer playbin handles all audio/video formats automatically
- **Video Support**: Video files (MP4, MKV, WebM, etc.) play with both audio and video
- **Modular Dockable Panels**: Each panel (Library, Playlist, Now Playing, Bluetooth) can be detached as a separate window
- **Folder-Based Library Browser**: Browse your music library using the original folder structure
- **Touch-Friendly Interface**: Large buttons, increased row heights, and generous spacing
- **Playlist Management**: 
  - Double-click tracks/folders to add to playlist and play
  - Right-click context menus for adding, removing, and reordering
  - Save and load custom playlists
- **Bluetooth Speaker Mode**: Act as a Bluetooth audio receiver
- **Search**: Search and filter your music collection
- **Metadata Display**: Beautiful GTK4 interface with album art and track information
- **Layout Persistence**: Panel layout is saved and restored between sessions

## Requirements

### Gentoo Linux Dependencies

```bash
# Core GTK / GStreamer
emerge -av \
  media-libs/gstreamer \
  media-libs/gst-plugins-base \
  media-libs/gst-plugins-good \
  media-libs/gst-plugins-bad \
  media-libs/gst-plugins-ugly \
  media-plugins/gst-plugins-mpg123 \
  media-plugins/gst-plugins-faac \
  media-plugins/gst-plugins-flac \ 
  media-plugins/gst-plugins-faad \
  media-plugins/gst-plugins-openh264 \
  media-plugins/gst-plugins-bluez

# Audio stack
emerge -av media-libs/alsa-lib

# Bluetooth support
emerge -av net-wireless/bluez

# Audio routing (choose one)
emerge -av media-video/pipewire  # recommended
# or
emerge -av media-sound/pulseaudio

# Python bindings
emerge -av dev-python/pygobject dev-python/mutagen dev-python/dbus-python

# Optional: extra format support
emerge -av media-video/ffmpeg
```

### Python Dependencies

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

### Music Library

The player automatically scans `~/Music` and `~/Musik` directories.

**Supported Audio Formats:**
- **Lossy**: MP3, AAC/M4A, OGG Vorbis, Opus, WMA
- **Lossless**: FLAC, WAV, AIFF, ALAC, APE

**Supported Video Formats:**
- **MP4, MKV, WebM, AVI, MOV, FLV, WMV, M4V**
- Video files play with both audio and video output
- Audio-only files play without spawning a video window

**Metadata Extraction:**
- Automatic format detection (FLAC, MP3, MP4, OGG, etc.)
- Extracts title, artist, album, track number, duration
- Falls back to filename if metadata is missing
- Album art extraction from embedded covers

**Library Indexing:**
- Index saved to `~/.config/musicplayer/library_index.json`
- Only new/modified files are rescanned on startup

### Dockable Panels

Each panel has a header with a detach button to pop it out as a separate window.

- **Library**: Browse music using folder structure
- **Playlist**: View and manage current queue
- **Now Playing**: Album art and track info
- **Bluetooth**: Manage connections and Speaker Mode

### Adding Music to Playlist

**From Library panel:**
- Double-click track → replace playlist and play
- Double-click folder → add all tracks and play
- Right-click for context menu

**From Playlist panel:**
- Double-click → play track
- Right-click → remove, reorder, save playlist

### Bluetooth Speaker Mode

1. Click **"Enable Speaker Mode"** in the Bluetooth panel
2. Your computer becomes discoverable as "Music Player Speaker"
3. Pair from your mobile device
4. Audio streams through your computer's speakers

**Requirements:**
- BlueZ daemon running (`systemctl start bluetooth`)
- GStreamer BlueZ plugin: `media-plugins/gst-plugins-bluez`
- Bluetooth adapter with A2DP sink support

## Project Structure

```
MusicPlayer/
├── main.py                    # Entry point
├── requirements.txt           # Python dependencies
├── ui/                        # UI components
│   ├── main_window.py         # Main window
│   ├── dock_manager.py        # Panel management
│   └── components/            # UI widgets
├── core/                      # Core functionality
│   ├── music_library.py       # Library scanning
│   ├── audio_player.py        # GStreamer playback
│   ├── playlist_manager.py    # Playlist handling
│   ├── metadata.py            # Metadata extraction
│   ├── bluetooth_manager.py   # BlueZ integration
│   └── bluetooth_sink.py      # A2DP sink mode
└── ~/.config/musicplayer/     # User config
```

## Troubleshooting

### No sound output
```bash
gst-inspect-1.0 autoaudiosink  # Check audio sink
aplay -l                        # Verify ALSA
gst-launch-1.0 audiotestsrc ! autoaudiosink  # Test GStreamer
```

### Missing codec errors
```bash
# FLAC
emerge -av media-plugins/gst-plugins-flac
gst-inspect-1.0 flacdec

# H.264 video
emerge -av media-plugins/gst-plugins-openh264

# General codecs
emerge -av media-libs/gst-plugins-good media-libs/gst-plugins-bad
```

### Bluetooth not working
```bash
systemctl status bluetooth      # Check BlueZ
bluetoothctl power on           # Power on adapter
```

### Reset panel layout
Delete `~/.config/musicplayer/layout.json`

## License

This project is open source and available for personal use.
