# GTK Music Player with Bluetooth Streaming

A custom music player built with GTK4 and Python that manages your local music library and handles Bluetooth audio streaming from mobile devices.

## Features

- Browse and play music from your local library (`~/Music` and `~/Musik`)
- Search and filter your music collection
- Playlist management (create, save, and load playlists)
- Bluetooth audio streaming from mobile phones
- Beautiful GTK4 interface with metadata display

## Requirements

### Gentoo Linux Dependencies

Install the following packages using `emerge`:

```bash
# GStreamer and plugins
emerge -av media-libs/gstreamer
emerge -av media-plugins/gst-plugins-base
emerge -av media-plugins/gst-plugins-good
emerge -av media-plugins/gst-plugins-bad

# Bluetooth support
emerge -av net-wireless/bluez

# Audio system (choose one)
emerge -av media-sound/pulseaudio  # or
emerge -av media-video/pipewire

# Python and GTK
emerge -av dev-python/pygobject
emerge -av dev-python/mutagen
emerge -av dev-python/dbus-python
```

### Python Dependencies

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Or using Gentoo's package manager:

```bash
emerge -av dev-python/pygobject dev-python/mutagen dev-python/dbus-python
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

### Bluetooth Streaming

1. Click the Bluetooth button in the top bar
2. Pair your mobile device with your computer
3. Connect the device
4. Start playing audio on your phone - it will stream through your sound system

## Project Structure

```
MusicPlayer/
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── ui/                    # UI components
│   ├── main_window.py     # Main GTK window
│   └── components/        # Reusable UI components
├── core/                  # Core functionality
│   ├── music_library.py   # Library scanning
│   ├── audio_player.py    # GStreamer playback
│   ├── bluetooth_manager.py  # Bluetooth management
│   ├── playlist_manager.py   # Playlist handling
│   └── metadata.py        # Metadata extraction
└── data/
    └── playlists/         # Saved playlists
```

## License

This project is open source and available for personal use.

