# 🎵 Build Your Own Bluetooth Speaker with Python!

> **An IoT Learning Project** — Turn your computer into a Bluetooth speaker and learn real-world programming along the way!

```
    📱 ─────────────── 🔊
     Your Phone          Your Computer
     (streams audio)  →  (plays music!)
```

---

## 🌟 What Is This Project?

This is a **fully functional music player** that can also act as a **Bluetooth speaker**. That means you can pair your phone with your computer and play Spotify, YouTube, or any audio through your computer's speakers!

But more importantly, this project is designed to teach you **IoT (Internet of Things)** concepts through hands-on code. You'll learn how devices talk to each other wirelessly, how audio gets processed, and how to build real desktop applications.

### What You'll Learn

| Concept | What It Means | Where You'll See It |
|---------|---------------|---------------------|
| 🔵 **Bluetooth** | Wireless communication between devices | `bluetooth_manager.py` |
| 🔌 **D-Bus** | How programs talk to each other on Linux | `bluetooth_manager.py` |
| 🎼 **GStreamer** | Audio/video processing pipelines | `audio_player.py` |
| 🖼️ **GTK** | Building graphical user interfaces | `ui/` folder |
| 🐍 **Python** | The language powering it all | Everywhere! |

---

## 📋 Table of Contents

<details>
<summary><strong>Click to expand navigation</strong></summary>

- [System Requirements](#-system-requirements-gentoo-linux)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Features](#-features)
- [Usage Guide](#-usage-guide)
- [Troubleshooting](#-troubleshooting)
- [Learning Resources](#-learning-resources--challenges)
- [Technical Documentation](#-technical-documentation)
- [Contributing](#-contributing)

</details>

---

## 🐧 System Requirements (Gentoo Linux)

This project runs on **Gentoo Linux** — and that's actually AMAZING for learning!

### Why Gentoo for IoT Learning?

Gentoo is a "build from source" Linux distribution. Unlike Ubuntu or Fedora where you just click install, Gentoo makes you understand **every piece of your system**. This is exactly the mindset you need for IoT:

```
┌─────────────────────────────────────────────────────────────┐
│                   Why Gentoo = Better Learning              │
├─────────────────────────────────────────────────────────────┤
│  ✓ You configure the kernel → understand hardware drivers  │
│  ✓ You compile everything → see dependencies clearly       │
│  ✓ You manage services → learn how daemons work            │
│  ✓ USE flags → understand what features software needs     │
└─────────────────────────────────────────────────────────────┘
```

> 📖 **New to Gentoo?** Follow the [Gentoo AMD64 Handbook (Full Installation)](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation) — we recommend the **full manual approach**. Yes, it takes longer, but you'll learn SO much more than clicking "Next" 50 times!

### System Packages Required

Open a terminal and install these packages. Don't just copy-paste — read what each one does!

```bash
# GTK4 and icon theme (required for the user interface)
# Without this, no windows, no buttons, no fun!
emerge -av gui-libs/gtk x11-themes/adwaita-icon-theme

# GStreamer - the audio/video processing framework
# Each plugin handles different formats
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

# ALSA - Advanced Linux Sound Architecture (low-level audio)
emerge -av media-libs/alsa-lib

# BlueZ - the Linux Bluetooth stack
emerge -av net-wireless/bluez

# Audio routing - choose ONE:
emerge -av media-video/pipewire  # 🌟 Recommended - modern & flexible
# OR
emerge -av media-sound/pulseaudio  # Classic option

# Python bindings - connect Python to GTK, GStreamer, and D-Bus
emerge -av dev-python/pygobject dev-python/mutagen dev-python/dbus-python

# Optional: FFmpeg for extra format support
emerge -av media-video/ffmpeg

# Optional: MOC (Music On Console) for audio playback
emerge -av media-sound/moc
```

> 🧪 **Challenge:** After installing, try `gst-inspect-1.0 | wc -l` to see how many GStreamer plugins you have. The more plugins, the more formats you can play!

### Kernel Configuration

If you followed the [Gentoo Handbook](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation) manual kernel configuration, make sure you enabled Bluetooth support:

```
Device Drivers --->
  [*] Network device support --->
    <*> Bluetooth subsystem support --->
      <*> RFCOMM protocol support
      <*> HIDP protocol support
      <*> Bluetooth device drivers --->
        <*> HCI USB driver   # For USB Bluetooth dongles
```

**Why this matters for IoT:** In embedded systems (Raspberry Pi, ESP32, etc.), you often configure your own kernel. Knowing how to enable specific hardware support is a real skill!

### Enable Bluetooth Service

```bash
# Start Bluetooth daemon
rc-service bluetooth start

# Enable at boot
rc-update add bluetooth default

# Check it's running
rc-service bluetooth status
```

### Supported Formats

| Type | Formats | Why It Works |
|------|---------|--------------|
| 🎵 **Lossy Audio** | MP3, AAC/M4A, OGG, Opus, WMA | `gst-plugins-good`, `mpg123` |
| 🎶 **Lossless Audio** | FLAC, WAV, AIFF, ALAC, APE | `gst-plugins-flac` |
| 🎬 **Video** | MP4, MKV, WebM, AVI, MOV | `gst-plugins-bad`, `openh264` |

---

## 🚀 Installation

### Step 1: Clone the Repository

```bash
git clone <your-repo-url>
cd MusicPlayer
```

### Step 2: Set Up Python Environment

```bash
# Create a virtual environment (keeps things clean!)
python -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt
```

**Python Dependencies:**
- `PyGObject>=3.42.0` - GTK4 and GStreamer bindings
- `mutagen>=1.47.0` - Audio metadata extraction (MP3, FLAC, OGG)
- `dbus-python>=1.2.0` - D-Bus integration
- `watchdog>=3.0.0` - File system monitoring (optional, not yet fully implemented)

**Note:** Video files (MP4, MKV, WebM, etc.) use GStreamer for metadata extraction, which handles video containers more reliably than mutagen.

**Development Dependencies (optional):**
```bash
pip install pytest pytest-mock pytest-asyncio
```

### Step 3: Verify Installation

```bash
# Test GStreamer
gst-launch-1.0 audiotestsrc ! autoaudiosink

# Test Bluetooth
bluetoothctl --version

# Test Python bindings
python -c "import gi; gi.require_version('Gtk', '4.0'); print('GTK4 OK')"
```

---

## 🎯 Quick Start

### Run the Application

```bash
# Activate virtual environment (if not already active)
source venv/bin/activate

# Run the music player
python main.py
```

You should see a window with your music library, playlist, and Bluetooth controls! 🎉

### Basic Controls

- **Playback controls** (bottom bar):
  - **Play / Pause / Stop / Previous / Next**: Control the current playlist
  - **Shuffle**: Toggle to play the current playlist in **random order**
  - **Seek & Volume**: Touch-friendly sliders for scrubbing through tracks and adjusting volume

- **Playlist management** (touch-friendly, see [Playlist View Options](#playlist-view-options) for configuration):
  - **Single tap**: Play the selected track (after 300ms double-tap detection window)
  - **Double-tap**: Play the selected track immediately
  - **Double-click or Enter**: Play the selected track
  - **Long-press + drag** (hold > 500ms, then drag): Reorder tracks by dragging them up or down
  - **Long-press (hold > 500ms, release in place)**: Show context menu with options (Play, Remove, Move Up/Down)
  - **Right-click**: Show context menu (mouse users)

---

## ⚙️ Configuration

The application follows the **XDG Base Directory Specification** for Linux standards compliance.

### Configuration Locations

- **Config**: `~/.config/musicplayer/settings.json`
- **Cache**: `~/.cache/musicplayer/` (includes album art cache)
- **Data**: `~/.local/share/musicplayer/` (includes playlists)
- **Logs**: `~/.local/share/musicplayer/logs/`

### Environment Variables

- `MUSICPLAYER_DEBUG=1` - Enable debug logging
- `XDG_CONFIG_HOME` - Override config directory
- `XDG_CACHE_HOME` - Override cache directory
- `XDG_DATA_HOME` - Override data directory

### Service Installation (Optional)

**Systemd (user service):**
```bash
cp data/musicplayer.service ~/.config/systemd/user/
# Edit the ExecStart path in the service file to match your installation
systemctl --user enable musicplayer.service
systemctl --user start musicplayer.service
```

**OpenRC:**
```bash
sudo cp data/musicplayer.init /etc/init.d/musicplayer
# Edit paths in the init script to match your installation
sudo rc-update add musicplayer default
sudo /etc/init.d/musicplayer start
```

---

## ✨ Features

### Core Features

- **Music Library Management** - Scan and organize your music collection
- **Playlist Support** - Create, save, and load playlists
- **Bluetooth Speaker Mode** - Turn your computer into a Bluetooth speaker
- **MOC Integration** - Seamless integration with Music On Console
- **Video Playback** - Support for video container formats

### Linux Enhancements

<details>
<summary><strong>Click to expand feature details</strong></summary>

#### Logging System
- **Structured logging** with rotating file handlers
- Log files in `~/.local/share/musicplayer/logs/`
- Console output for warnings and errors (stderr)
- Environment variable `MUSICPLAYER_DEBUG=1` for debug mode
- All `print()` statements replaced with proper logging

#### Configuration Management
- **XDG Base Directory** compliance
- Configurable settings via JSON config file
- Automatic directory creation
- Environment variable support

#### MPRIS2 Integration
- **Desktop media key support** (PlayPause, Next, Previous)
- Integration with desktop environments (GNOME, KDE, etc.)
- Remote control via D-Bus
- System tray notifications support

#### Desktop Integration
- **Desktop entry file** for application launcher
- GTK RecentManager integration
- Drag-and-drop file support
- Service files for systemd/OpenRC

#### PipeWire Native Support
- **Event-based volume monitoring** (no polling)
- Native D-Bus integration with fallback to subprocess
- Multiple audio device support
- Device switching functionality

#### Audio Effects
- **10-band equalizer** via GStreamer
- ReplayGain support
- Crossfade between tracks
- Equalizer presets (bass boost, treble boost, vocal boost, etc.)

#### Advanced Bluetooth Features
- **Codec selection** (SBC, AAC, aptX if available)
- Battery level monitoring for connected devices
- Connection quality indicators (RSSI, link quality)
- Multiple device support

#### Bluetooth Security & Stability
- **Trusted device whitelist** - Limit connections to approved devices only
- **Configurable discoverable timeout** - Auto-disable discoverability after timeout (default: 5 minutes)
- **D-Bus path validation** - All Bluetooth D-Bus paths are validated for security
- **Connection authorization** - Option to require explicit user approval for connections
- **Automatic reconnection** - Reconnects to last device after unexpected disconnection (max 3 attempts)
- **Connection health monitoring** - Periodic checks to detect and recover from connection issues
- **A2DP transport state tracking** - Monitors audio stream state for stability
- **Thread-safe state management** - Prevents race conditions in concurrent events

#### Security Hardening
- **Path validation** to prevent path traversal attacks
- Input sanitization for all user-provided data
- D-Bus security checks
- File permission validation

#### Performance Optimizations
- **File system monitoring** (inotify/watchdog) for incremental library updates
- Lazy loading of album art (only when visible)
- Incremental library scanning (only changed files)
- Memory-efficient metadata caching

#### Enhanced D-Bus Handling
- **Retry logic** with exponential backoff
- Connection state monitoring
- Graceful error recovery
- Better error messages with actionable suggestions

</details>

---

## 📖 Usage Guide

### MOC Integration (Music On Console)

If `mocp` is installed (Gentoo package `media-sound/moc`), the app will:

- **Read the MOC playlist** from `~/.moc/playlist.m3u` and mirror it in the playlist panel
- **Write back changes** you make in the GTK playlist into MOC's internal playlist
- **Sync player controls** with MOC:
  - **Play / Pause / Stop / Next / Previous** buttons call `mocp` under the hood
  - The **volume slider** controls MOC's volume
  - The **current track / time** display follows whatever MOC is playing
  - **Track navigation** is handled by the app (MOC autonext is disabled to prevent conflicts)
  - **Shuffle** toggle is fully synchronized with MOC

#### File Type Handling

- MOC is primarily an **audio player**; our internal GStreamer-based player supports both **audio and video containers**
- When `mocp` is available, the app will:
  - Use **MOC for pure audio files** (MP3, FLAC, OGG, etc.)
  - Automatically **prefer the internal player for video containers** (`.mp4`, `.mkv`, `.webm`, etc.)
  - Cleanly **shut down the MOC server** when you close the GTK app window

#### Playlist Sync Behavior

When you edit the playlist directly in MOC:

- The app **watches `~/.moc/playlist.m3u`** and reloads it when the file timestamp changes
- Whenever MOC reports that the **current track changed**, the app reloads the full playlist
- **Changes are reflected** when:
  - You skip to another track in MOC (automatic reload on every track change)
  - MOC saves its playlist (press `S` in MOC, or when MOC exits)
  - You click the **Refresh** button in the playlist panel

### Bluetooth Speaker Mode

<details>
<summary><strong>How Bluetooth Speaker Mode Works</strong></summary>

#### 1️⃣ Enable Speaker Mode

When you click **"Enable Speaker Mode"**, the app will:

```
User clicks button
       │
       ▼
┌─────────────────────────────────┐
│ bluetooth_sink.py               │
│ enable_sink_mode()              │
│ - Set adapter as discoverable   │
│ - Change adapter name           │
│ - Register A2DP sink endpoint   │
└─────────────────────────────────┘
```

#### 2️⃣ Phone Connects

When your phone pairs and connects:

```
Phone initiates pairing
       │
       ▼
┌─────────────────────────────────┐
│ bluetooth_agent.py              │
│ - Receives pairing request      │
│ - Shows confirmation dialog     │
│ - User confirms                 │
│ - Trust the device              │
└─────────────────────────────────┘
       │
       ▼
Phone sends A2DP audio stream
       │
       ▼
┌─────────────────────────────────┐
│ PipeWire / PulseAudio           │
│ - Receives Bluetooth audio      │
│ - Routes to speakers            │
└─────────────────────────────────┘
       │
       ▼
🔊 Music plays!
```

#### 3️⃣ Audio Flow

The actual audio routing is handled by **PipeWire** (or **PulseAudio**), not our code! We just set up the Bluetooth connection, and the audio system handles the rest.

```
Phone                    Computer
  │                          │
  │   A2DP Audio Stream     │
  │  ─────────────────────► │
  │   (Bluetooth SBC/AAC)   │
  │                          │
  │                    ┌─────┴─────┐
  │                    │ PipeWire  │
  │                    │   or      │
  │                    │PulseAudio │
  │                    └─────┬─────┘
  │                          │
  │                    ┌─────▼─────┐
  │                    │ Speakers  │
  │                    │   🔊      │
  │                    └───────────┘
```

</details>

---

## 🛠️ Troubleshooting

### "No sound output!"

```bash
# Check if audio works at all
gst-launch-1.0 audiotestsrc ! autoaudiosink

# Check ALSA (low-level audio)
aplay -l

# Check PipeWire/PulseAudio
pactl info
```

### "Bluetooth not working!"

```bash
# Is Bluetooth service running? (Gentoo uses OpenRC)
rc-service bluetooth status

# Start it if not running
rc-service bluetooth start

# Is adapter on?
bluetoothctl power on

# List controllers
bluetoothctl list
```

### "Missing codec errors!"

```bash
# Check what GStreamer plugins you have
gst-inspect-1.0 | grep flac
gst-inspect-1.0 | grep mp3

# Install missing plugins (Gentoo)
emerge -av media-libs/gst-plugins-good
emerge -av media-libs/gst-plugins-bad

# Specific codecs
emerge -av media-plugins/gst-plugins-flac      # FLAC audio
emerge -av media-plugins/gst-plugins-openh264  # H.264 video
```

### "MOC error: No files added!"

This error occurs when trying to play a track that has an invalid or missing file path. The app now validates file paths before sending them to MOC.

```bash
# Check if the track file exists
ls -l /path/to/your/track.mp3

# If files were moved, reload the playlist
# The app will automatically skip invalid tracks when syncing to MOC
```

**What was fixed:**
- File path validation before adding tracks to MOC playlist
- Validation before attempting playback
- Better error messages to identify problematic tracks
- Tracks with missing files are automatically skipped when syncing to MOC

### "Songs don't automatically advance to the next track!"

If playback stops when a song finishes instead of automatically playing the next song:

**What was fixed:**
- Improved end-of-track detection in MOC synchronization
- Automatic next track advancement when a track finishes
- MOC autonext is disabled - the app handles track navigation to prevent conflicts
- Better handling of track completion for both sequential and shuffled playback
- User action guard prevents MOC status polling from interfering with user-initiated track changes

The app now properly detects when a track finishes (by monitoring position vs duration) and automatically advances to the next track. The app is the single source of truth for track navigation, preventing conflicts between MOC's internal state and the app's playlist management.

### "App silently quits when I start it again!"

This is expected behavior. The app uses GTK's **single-instance pattern** — only one instance can run at a time with the same application ID.

**What happens:**
1. First instance registers itself via D-Bus under `com.musicplayer.app`
2. Second instance detects the existing app
3. Second instance activates the first app's window and exits

**You'll see this message in the terminal:**
```
Another instance is already running. Activating existing window.
```

**If you really need multiple instances** (not recommended for a music player):
- This would require code changes to remove the application ID or use `NON_UNIQUE` flag

### "Panel layout is messed up!"

```bash
# Reset to default layout
rm ~/.config/musicplayer/layout.json
```

### "Bluetooth battery/quality monitoring crashes!"

**What was fixed:**
- D-Bus signal receivers for battery/quality monitoring were missing the `path_keyword` parameter
- This caused a `TypeError` when battery or quality change signals were received
- The signal handlers now correctly receive the device path for proper callback routing

### "Bluetooth sink mode fails to disable!"

**What was fixed:**
- `BluetoothSink` was missing the `on_audio_stream_stopped` callback attribute initialization
- This caused an `AttributeError` when calling `disable_sink_mode()`
- The callback is now properly initialized to `None` in `__init__`

### "Clicking a playlist row plays the wrong track!"

If tapping or clicking a row in the playlist plays the wrong track:

**What was fixed:**
- The playlist view now uses the GTK selection model as the source of truth for all row operations
- All gesture handlers (tap, double-tap, long-press, drag) read from the selection model instead of coordinate-based lookups
- `GestureClick` updates the selection on left-click, and all other handlers read from this selection
- This ensures the correct row is always used for playback, context menu, and drag operations
- Drag-to-reorder has been optimized to only update the moved row instead of rebuilding the entire view
- File I/O for playlist persistence is deferred to avoid blocking the UI thread
- Drop target visualization shows a dark highlight on the target row during drag

### "Can't receive value from the server!" fatal error during drag operations

If the application crashes with a GTK fatal error when dragging playlist items:

**What was fixed:**
- Removed selection model updates during drag operations (selection updates now only happen after drag completes)
- Added comprehensive error handling for all widget property accesses during drag (get_visible_range, get_cell_area, get_allocation, get_vadjustment)
- Added bounds checking and validation for all index calculations
- Enhanced error handling in drag begin, update, and end handlers to prevent fatal crashes
- All widget property accesses are now protected with try/except blocks to handle invalid widget states gracefully
- The drag target index calculation now properly accounts for the move_track() logic which adjusts insert index when moving down

### "Move Down in playlist context menu crashes!"

**What was fixed:**
- The "Move Down" context menu action referenced a non-existent `self.tracks` attribute
- Changed to use `self._state.playlist` which is the correct way to access the playlist

### "Music keeps playing when Bluetooth speaker mode is enabled!"

**What was fixed:**
- When Bluetooth sink mode was enabled or a device connected, the previous playback backend (MOC or internal player) wasn't properly stopped
- The backend stop logic was checking the old active backend state before it was updated
- Now the active backend is set to "bt_sink" BEFORE stopping other backends, ensuring proper cleanup

### "Bluetooth resources not cleaned up on application exit!"

**What was fixed:**
- `BluetoothSink` was missing a `cleanup()` method to properly shut down when the application closes
- The main window wasn't calling cleanup on the BT sink
- Now `BluetoothSink.cleanup()` properly:
  - Stops health monitoring timers
  - Cancels reconnection attempts
  - Disables sink mode if enabled
  - Unsubscribes from EventBus events
  - Logs cleanup completion

### "Bluetooth connection drops and doesn't recover!"

**What was fixed:**
- Added automatic reconnection logic with configurable retry attempts (max 3 by default)
- Added connection health monitoring that runs every 5 seconds
- A2DP transport state is now tracked and recovered if lost
- When a device disconnects unexpectedly, reconnection is automatically scheduled

### "Unauthorized devices can connect to my speaker!"

**Security improvements:**
- **Trusted device whitelist**: Use `bt_sink.add_trusted_device("AA:BB:CC:DD:EE:FF")` to allow only specific devices
- **Discoverable timeout**: Default is 5 minutes (was indefinite) - configurable via `bt_sink.set_discoverable_timeout(300)`
- **Connection authorization**: Enable with `bt_sink.set_require_authorization(True)` for explicit approval
- **D-Bus path validation**: All Bluetooth paths are validated to prevent injection attacks

### "Missing icons (placeholders shown)!"

```bash
# Install Adwaita icon theme
emerge -av x11-themes/adwaita-icon-theme

# Set icon theme (add to ~/.config/gtk-4.0/settings.ini)
echo "[Settings]" > ~/.config/gtk-4.0/settings.ini
echo "gtk-icon-theme-name=Adwaita" >> ~/.config/gtk-4.0/settings.ini
```

---

## 🧠 Learning Resources & Challenges

<details>
<summary><strong>Understanding IoT Through This Project</strong></summary>

### What Even IS IoT?

**IoT** stands for **Internet of Things** — it's the idea that everyday devices (thermostats, speakers, lights, fridges) can connect and communicate with each other.

```
        ┌─────────────┐
        │  THE CLOUD  │
        │   (maybe)   │
        └──────┬──────┘
               │
    ┌──────────┼──────────┐
    │          │          │
    ▼          ▼          ▼
┌───────┐  ┌───────┐  ┌───────┐
│ Phone │  │ Light │  │ This  │
│  📱   │  │  💡   │  │Project│
└───────┘  └───────┘  └───────┘
    │                     ▲
    └── Bluetooth A2DP ───┘
```

In our project, we're doing IoT **locally** — your phone talks directly to your computer via Bluetooth. No cloud required!

### The Three Pillars of IoT

1. **Sensors/Inputs** — Things that detect stuff (in our case: Bluetooth radio receiving audio)
2. **Processing** — Logic that does something with the data (GStreamer decoding audio)
3. **Actuators/Outputs** — Things that take action (speakers playing sound!)

</details>

### 🔵 Deep Dive: Bluetooth

<details>
<summary><strong>How Bluetooth Works in Our Code</strong></summary>

Bluetooth is the wireless protocol that lets devices talk to each other within short range (~10 meters).

#### How Devices Find Each Other

Open `core/bluetooth_manager.py` and look at this function:

```python
def start_discovery(self) -> bool:
    """Start Bluetooth device discovery."""
    if not self.adapter_proxy:
        return False
    
    try:
        self.adapter_proxy.StartDiscovery()  # <-- Magic happens here!
        return True
    except Exception as e:
        logger.error(f"Error starting discovery: {e}")
        return False
```

**What's happening:**
1. We ask the Bluetooth adapter to start scanning
2. The adapter broadcasts "Hey! Anyone out there?"
3. Nearby devices respond with their names and addresses
4. Our code collects these responses

#### The Bluetooth Stack

```
┌─────────────────────────────────┐
│   Your Python Code              │   ← You write this!
├─────────────────────────────────┤
│   D-Bus (message bus)           │   ← How we talk to BlueZ
├─────────────────────────────────┤
│   BlueZ (Bluetooth daemon)      │   ← Linux Bluetooth stack
├─────────────────────────────────┤
│   Kernel Driver                 │   ← Talks to hardware
├─────────────────────────────────┤
│   Bluetooth Hardware (hci0)     │   ← The actual radio chip
└─────────────────────────────────┘
```

#### Challenge: Bluetooth Explorer

Try running this in a Python shell:

```python
import dbus
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)
bus = dbus.SystemBus()

# Get the Bluetooth adapter
manager = dbus.Interface(
    bus.get_object('org.bluez', '/'),
    'org.freedesktop.DBus.ObjectManager'
)

# List all Bluetooth devices!
for path, interfaces in manager.GetManagedObjects().items():
    if 'org.bluez.Device1' in interfaces:
        device = interfaces['org.bluez.Device1']
        print(f"Found: {device.get('Name', 'Unknown')} - {device.get('Address')}")
```

**Your Mission:**
- How many Bluetooth devices are remembered by your computer?
- Can you find your phone in the list?
- What other properties does each device have?

<details>
<summary><strong>💡 Hints & Solutions</strong></summary>

**Hints:**
- Make sure Bluetooth is enabled: `bluetoothctl power on`
- Try printing all properties: `print(device)` to see what's available
- Check device connection status with `device.get('Connected', False)`

**Solution:**
To see all properties, modify the loop:
```python
for path, interfaces in manager.GetManagedObjects().items():
    if 'org.bluez.Device1' in interfaces:
        device = interfaces['org.bluez.Device1']
        print(f"\nDevice: {device.get('Name', 'Unknown')}")
        print(f"  Address: {device.get('Address')}")
        print(f"  Connected: {device.get('Connected', False)}")
        print(f"  Paired: {device.get('Paired', False)}")
        print(f"  Trusted: {device.get('Trusted', False)}")
        print(f"  All properties: {list(device.keys())}")
```

</details>

> **📚 Learn More:** [BlueZ D-Bus API Documentation](https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc/device-api.txt)

</details>

### 🔌 Deep Dive: D-Bus

<details>
<summary><strong>The System's Nervous System</strong></summary>

D-Bus is like the nervous system of your Linux computer. Different programs send messages to each other through D-Bus, just like neurons sending signals!

#### Why D-Bus?

Instead of each program talking directly to Bluetooth hardware (chaos!), they all go through BlueZ via D-Bus:

```
┌─────────┐   ┌─────────┐   ┌─────────┐
│ Our App │   │ Another │   │ System  │
│         │   │   App   │   │Settings │
└────┬────┘   └────┬────┘   └────┬────┘
     │             │             │
     └──────────┬──┴─────────────┘
                │
         ┌──────▼──────┐
         │    D-Bus    │  (Message Bus)
         └──────┬──────┘
                │
         ┌──────▼──────┐
         │   BlueZ     │  (Bluetooth Service)
         └─────────────┘
```

#### Signals: Events You Can Listen To!

In our code, we listen for Bluetooth events using **signals**:

```python
def _setup_signals(self):
    """Set up D-Bus signals for device changes."""
    # Listen when device properties change (connected/disconnected)
    self.bus.add_signal_receiver(
        self._on_properties_changed,       # <-- Our callback function
        dbus_interface='org.freedesktop.DBus.Properties',
        signal_name='PropertiesChanged'     # <-- The event type
    )
```

When a phone connects, BlueZ sends a `PropertiesChanged` signal, and our function gets called!

#### Challenge: D-Bus Detective

Use the `dbus-monitor` command to spy on D-Bus messages:

```bash
# Watch all Bluetooth-related messages
dbus-monitor --system "sender='org.bluez'"
```

Now try:
1. Turn Bluetooth on/off in your settings
2. Pair a device
3. Connect/disconnect a device

**Your Mission:**
- What messages appear when you toggle Bluetooth?
- Can you spot the `PropertyChanged` signal when a device connects?
- What other signals does BlueZ send?

<details>
<summary><strong>💡 Hints & Solutions</strong></summary>

**Hints:**
- Look for `PropertiesChanged` signals with `Connected` property changes
- Watch for `InterfacesAdded` and `InterfacesRemoved` signals
- Try filtering: `dbus-monitor --system "interface='org.bluez.Adapter1'"`

**What to Look For:**
When a device connects, you should see something like:
```
signal time=1234567890.123 sender=:1.23 -> destination=(null destination) serial=456 path=/org/bluez/hci0/dev_XX_XX_XX_XX_XX_XX; interface=org.freedesktop.DBus.Properties; member=PropertiesChanged
   string "org.bluez.Device1"
   array [
      dict entry(
         string "Connected"
         variant             boolean true
      )
   ]
```

</details>

> **📚 Learn More:** [D-Bus Tutorial](https://dbus.freedesktop.org/doc/dbus-tutorial.html)

</details>

### 🎼 Deep Dive: GStreamer

<details>
<summary><strong>The Audio Pipeline</strong></summary>

GStreamer is like a factory assembly line, but for media! Audio goes in one end, gets processed through different stages, and comes out the speakers.

#### The Pipeline Concept

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Source  │ →  │ Decoder  │ →  │  Volume  │ →  │   Sink   │
│ (file)   │    │ (MP3→PCM)│    │ (adjust) │    │(speakers)│
└──────────┘    └──────────┘    └──────────┘    └──────────┘
    📁             🔧              🔊              🔈
```

Each box is called an **element**, and they connect via **pads**.

#### Our Audio Player (Simplified)

Look at `core/audio_player.py`:

```python
def _setup_pipeline(self):
    """Set up the GStreamer playbin pipeline."""
    # playbin is a magic element that auto-builds the pipeline!
    self.playbin = Gst.ElementFactory.make("playbin", "playbin")
    
    # Where does audio come out?
    audio_sink = Gst.ElementFactory.make("autoaudiosink", "audiosink")
    self.playbin.set_property("audio-sink", audio_sink)
    
    # Set up message handling (errors, end-of-stream, etc.)
    bus = self.playbin.get_bus()
    bus.add_signal_watch()
    bus.connect("message", self._on_message)
```

`playbin` is like a smart pipeline — you give it a file, and it figures out which decoder to use automatically!

#### Challenge: Build Your Own Pipeline

Try running this in terminal to play a test tone:

```bash
gst-launch-1.0 audiotestsrc freq=440 ! audioconvert ! autoaudiosink
```

You should hear a 440Hz tone (that's an A note)!

Now try:
```bash
# Play a sine wave that changes frequency
gst-launch-1.0 audiotestsrc wave=sine freq=200 ! autoaudiosink

# Different wave shapes (0=sine, 1=square, 2=saw, 3=triangle)
gst-launch-1.0 audiotestsrc wave=2 freq=300 ! autoaudiosink

# Play an actual music file
gst-launch-1.0 playbin uri=file:///path/to/your/song.mp3
```

**Your Mission:**
- What happens if you change `freq=440` to `freq=880`?
- Can you figure out how to add volume control to the pipeline?
  (Hint: try adding `volume volume=0.5` between elements)
- What wave shapes sound the coolest?

<details>
<summary><strong>💡 Hints & Solutions</strong></summary>

**Hints:**
- `freq=880` plays an octave higher (A note one octave up)
- Volume element goes between `audioconvert` and `autoaudiosink`
- Try `gst-inspect-1.0 volume` to see volume element properties

**Solution:**
Here's a pipeline with volume control:
```bash
gst-launch-1.0 audiotestsrc freq=440 ! audioconvert ! volume volume=0.5 ! autoaudiosink
```

For a more complex example with multiple effects:
```bash
gst-launch-1.0 audiotestsrc wave=sine freq=440 ! audioconvert ! volume volume=0.7 ! autoaudiosink
```

</details>

> **📚 Learn More:** [GStreamer Application Development Manual](https://gstreamer.freedesktop.org/documentation/application-development/index.html)

</details>

### 🖼️ Deep Dive: GTK

<details>
<summary><strong>Making It Look Good</strong></summary>

GTK is the toolkit we use to create the graphical interface. Buttons, windows, lists — all GTK!

#### The Widget Tree

GTK apps are built like a tree:

```
Window
├── HeaderBar
│   ├── Title Label
│   └── Menu Button
└── Box (horizontal)
    ├── LibraryPanel
    │   ├── Search Entry
    │   └── TreeView (file list)
    ├── PlaylistPanel
    │   └── ListView (queue)
    └── NowPlayingPanel
        ├── Album Art (Image)
        ├── Track Info (Labels)
        └── PlayerControls
            ├── Play Button
            ├── Progress Slider
            └── Volume Slider
```

#### Creating a Button

```python
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# Create a button
button = Gtk.Button(label="Click Me!")

# Connect a function to the click event
button.connect("clicked", lambda btn: print("Button was clicked!"))
```

#### Challenge: Add a Feature

Try adding a "Now Playing" notification that shows when a new song starts!

Look at `core/audio_player.py` and find the `on_track_loaded` callback. Then:

1. Create a notification using `Gio.Notification`
2. Show it when a track loads
3. Include the song title and artist

**Hints:**
```python
from gi.repository import Gio, GLib

notification = Gio.Notification.new("Now Playing")
notification.set_body("Song Title - Artist Name")

# You'll need the application to send it
app.send_notification("now-playing", notification)
```

<details>
<summary><strong>💡 Hints & Solutions</strong></summary>

**Step-by-Step Solution:**

1. **Find where tracks are loaded** - Look in `core/audio_player.py` for methods that handle track changes
2. **Get the application instance** - You'll need access to `Gtk.Application` to send notifications
3. **Create the notification** - Use `Gio.Notification` with title and body
4. **Extract metadata** - Get song title and artist from metadata

**Full Implementation Example:**

In `core/audio_player.py`, add this method:
```python
def _send_now_playing_notification(self, title: str, artist: str):
    """Send a desktop notification when a track starts playing."""
    from gi.repository import Gio
    
    # Get the application instance (you may need to pass this in)
    app = self.app  # Assuming you store app reference
    
    notification = Gio.Notification.new("Now Playing")
    notification.set_body(f"{title} - {artist}")
    
    # Optional: add an icon
    icon = Gio.ThemedIcon.new("audio-x-generic")
    notification.set_icon(icon)
    
    app.send_notification("now-playing", notification)
```

Then call it when a track loads:
```python
def on_track_loaded(self, metadata):
    if metadata:
        title = metadata.get('title', 'Unknown Title')
        artist = metadata.get('artist', 'Unknown Artist')
        self._send_now_playing_notification(title, artist)
```

</details>

> **📚 Learn More:** [GTK4 Python Tutorial](https://pygobject.readthedocs.io/en/latest/)

</details>

### 💡 IoT Project Ideas

Now that you understand the basics, here are some projects to try:

#### Beginner Projects

1. **🌡️ Temperature Display**
   - Connect a Bluetooth temperature sensor
   - Show readings in a GTK window
   - Log data to a file

2. **💡 Smart Light Controller**
   - Control Bluetooth LED bulbs
   - Create color presets
   - Schedule on/off times

#### Intermediate Projects

3. **🎮 Bluetooth Game Controller**
   - Read gamepad inputs via Bluetooth
   - Map buttons to keyboard shortcuts
   - Create a GUI for configuration

4. **🏠 Home Automation Hub**
   - Discover and manage multiple BLE devices
   - Create "scenes" (e.g., "Movie Mode" dims lights, starts music)

#### Advanced Projects

5. **📊 IoT Dashboard**
   - Collect data from multiple sensors
   - Display real-time graphs
   - Send alerts when thresholds are exceeded

6. **🤖 Voice-Controlled Assistant**
   - Add speech recognition (like Pocketsphinx or Vosk)
   - Control Bluetooth devices by voice
   - "Hey computer, play music on speaker"

---

## 📚 Resources to Learn More

### 🐧 Gentoo Linux

- 📖 [**Gentoo Handbook (Full Installation)**](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation) - The complete guide to building your system from scratch
- 📖 [Gentoo Wiki](https://wiki.gentoo.org/wiki/Main_Page) - Incredible documentation for everything
- 📖 [Portage (Package Manager)](https://wiki.gentoo.org/wiki/Portage) - Learn how `emerge` works
- 💬 [Gentoo Forums](https://forums.gentoo.org/) - Friendly community for questions
- 📖 [USE Flags](https://wiki.gentoo.org/wiki/USE_flag) - Understanding software configuration

### Bluetooth & IoT

- 📖 [Bluetooth Low Energy (BLE) Basics](https://learn.adafruit.com/introduction-to-bluetooth-low-energy) - Adafruit's friendly intro
- 📖 [BlueZ Official Documentation](http://www.bluez.org/documentation/)
- 🎥 [Bluetooth Technology Explained](https://www.youtube.com/watch?v=1I1vxu5qIUM) - Video explanation
- 🛠️ [Raspberry Pi IoT Projects](https://projects.raspberrypi.org/en/projects?software%5B%5D=bluetooth)

### Python & GObject

- 📖 [PyGObject Tutorial](https://pygobject.readthedocs.io/en/latest/)
- 📖 [GTK4 Widget Gallery](https://docs.gtk.org/gtk4/visual_index.html)
- 📖 [Real Python - GUIs with Tkinter/GTK](https://realpython.com/tutorials/gui/)

### GStreamer

- 📖 [GStreamer Basic Tutorial](https://gstreamer.freedesktop.org/documentation/tutorials/basic/index.html)
- 🎥 [GStreamer Pipeline Building](https://www.youtube.com/watch?v=ZphadMGufY8)
- 🛠️ [gst-inspect-1.0](https://gstreamer.freedesktop.org/documentation/tools/gst-inspect.html) - Explore available elements!

### Linux System Programming

- 📖 [D-Bus Python Tutorial](https://dbus.freedesktop.org/doc/dbus-python/tutorial.html)
- 📖 [Linux Audio Architecture](https://wiki.archlinux.org/title/Sound_system) - ArchWiki's deep dive
- 📖 [PipeWire Documentation](https://docs.pipewire.org/)

---

## 🏗️ Technical Documentation

<details>
<summary><strong>Project Structure & Architecture</strong></summary>

### Project Structure Explained

```
MusicPlayer/
│
├── 🚀 main.py                    # The starting point - run this!
│
├── 📦 core/                      # The "brain" - logic without UI
│   ├── audio_player.py           # GStreamer playback
│   ├── audio_effects.py           # Equalizer, ReplayGain, crossfade
│   ├── bluetooth_manager.py      # Device management, codecs, battery, quality
│   ├── bluetooth_agent.py        # Pairing confirmations & dialogs
│   ├── bluetooth_sink.py         # A2DP sink mode (speaker mode!)
│   ├── config.py                 # XDG-based configuration
│   ├── dbus_utils.py             # D-Bus error handling
│   ├── logging.py                # Structured logging system
│   ├── metadata.py               # Reading ID3 tags, album art
│   ├── moc_controller.py         # MOC integration
│   ├── music_library.py          # Scanning folders for music
│   ├── mpris2.py                 # MPRIS2 D-Bus interface
│   ├── pipewire_volume.py        # PipeWire volume control
│   ├── playlist_manager.py       # Queue management
│   ├── security.py               # Path validation, input sanitization
│   └── system_volume.py          # System volume control
│
├── 🎨 ui/                        # The "face" - what users see
│   ├── main_window.py            # Main application window
│   ├── dock_manager.py           # Detachable panels
│   └── components/               # Reusable UI pieces
│       ├── bluetooth_panel.py    # Bluetooth controls
│       ├── library_browser.py    # File browser
│       ├── metadata_panel.py     # Track info & album art
│       ├── player_controls.py    # Play/pause/seek
│       └── playlist_view.py      # Queue display
│
├── 📋 requirements.txt           # Python packages needed
├── 📄 README.md                  # You're reading it!
├── 📄 pytest.ini                 # Test configuration
├── 📁 tests/                     # Test suite
│   ├── test_audio_player.py
│   ├── test_config.py
│   ├── test_moc_controller.py
│   └── test_security.py
└── 📁 data/                      # Service files and desktop entry
    ├── musicplayer.desktop
    ├── musicplayer.service
    └── musicplayer.init
```

### The Event-Driven Pattern

We follow an event-driven architecture where:
- **State** = `AppState` (single source of truth)
- **Events** = `EventBus` (decoupled communication)
- **Controller** = `PlaybackController` (routes commands to backends)
- **View** = `ui/` components (pure views that subscribe to events)
- **Backends** = `AudioPlayer`, `MocController`, `BluetoothSink` (playback engines)

This architecture eliminates circular dependencies and makes the codebase much more maintainable!

### Architecture

#### Event-Driven Architecture

The application uses an **event-driven architecture** with clear separation of concerns:

**Core Components:**

1. **EventBus** (`core/events.py`) - Centralized publish-subscribe system
   - Components publish events instead of calling callbacks directly
   - Eliminates circular dependencies
   - Enables decoupled communication

2. **AppState** (`core/app_state.py`) - Single source of truth
   - All application state (playlist, playback state, volume, etc.)
   - State changes automatically publish events
   - Prevents duplicate state tracking

3. **PlaybackController** (`core/playback_controller.py`) - Mediator pattern
   - Routes playback commands to appropriate backend (MOC, internal player, BT sink)
   - Manages MOC status polling
   - Ensures only one backend is active at a time
   - Handles track changes and playlist synchronization

**Data Flow:**

```
User Action → UI Component → EventBus (ACTION_*) → PlaybackController
                                                          ↓
                                                    Backend (MOC/Internal/BT)
                                                          ↓
                                                    AppState (state update)
                                                          ↓
                                                    EventBus (STATE_*)
                                                          ↓
                                                    UI Components (update display)
```

**Benefits:**
- **No circular dependencies** - Components only depend on EventBus and AppState
- **Unidirectional data flow** - Actions go up, state flows down
- **Easy to test** - Components can be tested in isolation
- **Easy to extend** - New features just subscribe to events
- **Single source of truth** - State is never duplicated

#### Code Harmonization

The codebase follows systematic harmonization to ensure consistency and maintainability:

**Harmonization Plan:**
- See [HARMONIZATION_IMPLEMENTATION_PLAN.md](HARMONIZATION_IMPLEMENTATION_PLAN.md) for detailed implementation plan
- See [CODE_ORGANIZATION_HARMONIZATION.md](CODE_ORGANIZATION_HARMONIZATION.md) for standards and guidelines
- See [ARCHITECTURE_SIMPLIFICATION_ANALYSIS.md](ARCHITECTURE_SIMPLIFICATION_ANALYSIS.md) for architecture simplification opportunities

**Current Status:**
- ✅ Event-driven architecture implemented
- ✅ Single source of truth (AppState)
- ✅ Circular dependencies eliminated
- ✅ Configuration files created (pyproject.toml, .pylintrc, .editorconfig)
- ✅ Import organization standardized in priority files
- 🔄 Code formatting (requires Black installation)
- 🔄 Naming harmonization
- 🔄 Type hints completion
- 🔄 Documentation improvements
- 🔄 Error handling improvements

#### MOC Integration Architecture

The MOC (Music On Console) integration follows a simple, direct approach:

**Design Principles:**
- **`play_file()`** is the primary playback method - uses `mocp --playit <filepath>` for reliable track selection
- **Simple state tracking** - boolean `_server_connected` flag instead of complex state machines
- **Lightweight caching** - 200ms TTL cache for status to reduce MOC server load
- **Direct M3U writing** - playlist changes are written directly to MOC's playlist file

**Key Methods:**
- `play_file(filepath)` - Play a specific file using `--playit` (preferred method)
- `play()` - Resume playback (uses `--unpause` if paused, `--play` if stopped)
- `toggle_pause()` - Toggle play/pause using `--toggle-pause`
- `get_status()` - Get current playback state via `--info` with caching
- `set_playlist()` - Write playlist to M3U and optionally start playback
- `toggle_shuffle()` / `disable_autonext()` / `enable_autonext()` - Control MOC features

**Note:** MOC autonext is disabled by default. The app's `PlaybackController` handles track navigation to ensure consistent state management and prevent conflicts between MOC's internal playlist and the app's playlist state.

**MOC Commands Used (verified against `mocp --help`):**
- `--server` - Start server
- `--playit FILE` - Play specific file without modifying playlist
- `--play` - Start from first playlist item
- `--pause` / `--unpause` / `--toggle-pause` - Pause controls
- `--stop` - Stop playback
- `--next` / `--previous` - Track navigation
- `--seek N` - Seek by N seconds (positive/negative)
- `--on=CONTROL` / `--off=CONTROL` / `--toggle=CONTROL` - For shuffle, autonext, repeat
- `--info` - Get current track info
- `--exit` - Shutdown server

**Why This Approach:**
- MOC has no "jump to playlist index" command (`-j` is for seeking within a track, not track selection)
- `play_file()` with `--playit` is the most reliable way to play a specific track
- Simpler code is easier to debug and maintain
- Let MOC handle its own features (autonext, shuffle) rather than re-implementing them

#### UI State Management

The UI components use explicit state machines for user interaction:

**State Machines:**
- **`SeekState`** (player_controls.py): `IDLE`, `DRAGGING`, `SEEKING` - Manages progress bar interactions
- **`PlaybackState`** (app_state.py, audio_player.py): `STOPPED`, `LOADING`, `PAUSED`, `PLAYING`, `SEEKING` - Tracks playback state
- **`OperationState`** (playback_controller.py): `IDLE`, `SEEKING`, `SYNCING` - Prevents race conditions in MOC operations

**Benefits:**
- **No race conditions**: State machines prevent conflicts between UI updates and playback operations
- **Self-documenting**: Enums make code intent clear
- **Easier debugging**: Explicit state transitions are easier to trace
- **Centralized state**: AppState provides single source of truth, eliminating duplicate state tracking

### Development

#### Code Quality

The codebase follows Linux best practices:
- **Type hints** throughout (compatible with mypy)
- **Structured logging** instead of print statements
- **XDG Base Directory** compliance
- **Security validation** for all user inputs
- **D-Bus integration** following specifications
- **Explicit state machines** using enums instead of boolean flags
- **Separation of concerns** between UI updates and playback operations
- **Race condition prevention** through explicit state management

#### Testing

Run the test suite:
```bash
pytest tests/ -v
```

Run specific test file:
```bash
pytest tests/test_audio_player.py -v
```

Run with coverage:
```bash
pytest tests/ --cov=core --cov=ui --cov-report=html
```

#### Adding New Features

1. Follow existing code patterns
2. Use logging instead of print statements
3. Validate all user inputs via `SecurityValidator`
4. Use config system for paths and settings
5. Add tests for new functionality
6. Update README.md

</details>

---

## 🏆 Achievement Checklist

Track your learning progress!

### 🐧 Gentoo Achievements
- [ ] 🏗️ Installed Gentoo Linux using the [full handbook](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation)
- [ ] ⚙️ Compiled your own kernel with Bluetooth support
- [ ] 📦 Installed all dependencies with `emerge`
- [ ] 🔧 Understand what USE flags are

### 🎵 Project Achievements  
- [ ] 🎵 Ran the music player successfully
- [ ] 🔍 Explored Bluetooth devices with D-Bus
- [ ] 📡 Used `dbus-monitor` to spy on signals
- [ ] 🎼 Built a custom GStreamer pipeline
- [ ] 🔊 Enabled Speaker Mode and played from phone
- [ ] 📝 Read through `bluetooth_manager.py`
- [ ] 📝 Read through `audio_player.py`
- [ ] 🛠️ Modified the code (any small change counts!)
- [ ] 🚀 Created your own IoT project idea

---

## 🤝 Contributing

Found a bug? Have an idea? Want to share your learning journey?

1. Fork this repository
2. Create a branch for your feature
3. Make your changes
4. Open a Pull Request

Remember: The best way to learn is by doing — and the second-best way is by teaching others!

---

## 📜 License

This project is open source and available for personal and educational use.

---

<div align="center">

**Happy hacking! 🎉**

*Remember: Every expert was once a beginner.* 

*The only way to learn is to build things!*

</div>
