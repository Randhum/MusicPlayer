> Beware I did not write this code, I am rather the more or less lazy reviewer of this generated code - so you might see weird stuff happening.

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

| Type | Formats | Backend | Notes |
|------|---------|---------|-------|
| 🎵 **Lossy (MOC)** | MP3, OGG, FLAC | MOC | Native MOC decoders — most reliable path |
| 🎵 **Lossy (GStreamer)** | AAC/M4A, Opus, WMA | GStreamer | `gst-plugins-good/bad/ugly` |
| 🎶 **Lossless (GStreamer)** | WAV, AIFF, ALAC, APE | GStreamer | `gst-plugins-good/bad` |
| 🎬 **Video** | MP4, MKV, WebM, AVI, MOV | GStreamer | `gst-plugins-bad`, `openh264` |

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
  - **Loop**: Cycle through Forward / Loop Track / Loop Playlist (click to change)
  - Shuffle and loop buttons are **visually highlighted** when active
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

- **Config**: `~/.config/musicplayer/config.ini`
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
- Configurable settings via INI config file (`config.ini`)
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
  - **On startup**, if MOC is running, the app syncs full state from MOC: playlist, playback state (playing/paused/stopped), position, duration, volume, shuffle, and autonext
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


---

## 🧠 Learning Resources & Challenges

<details>
<summary><strong>Understanding IoT Through This Project</strong></summary>

### What Even IS IoT?

**IoT** stands for **Internet of Things** — it's the idea that everyday devices (thermostats, speakers, lights, fridges) can connect and communicate with each other.

```
        ┌─────────────┐
        │  THE AETHER │
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
│   ├── playlist_manager.py       # Playlist data & persistence (source of truth)
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
└── 📁 data/                      # Service files and desktop entry
    ├── musicplayer.desktop
    ├── musicplayer.service
    └── musicplayer.init
```

### Architecture

The application follows a simple event-driven model:
- `PlaylistManager` owns playlist data and persistence.
- `PlaybackController` owns playback state and backend routing.
- UI components publish actions and subscribe to state changes.
- `EventBus` handles decoupled communication between modules.

This keeps responsibilities clear and avoids circular dependencies.

#### Core Components

1. `EventBus` (`core/events.py`)
   - Central publish/subscribe channel.
2. `PlaylistManager` (`core/playlist_manager.py`)
   - Single source of truth for playlist content and current index.
   - Publishes playlist/index/track change events.
3. `PlaybackController` (`core/playback_controller.py`)
   - Routes actions to backends.
   - Publishes playback state, progress, shuffle, loop, and volume updates.
4. Playback backends
   - `MocController` (`core/moc_controller.py`) for selected audio formats.
   - `AudioPlayer` (`core/audio_player.py`) for video and selected audio formats.
   - `BluetoothSink` (`core/bluetooth_sink.py`) when sink mode is active.

#### Event Flow

```text
UI action -> ACTION_* event -> Controller/Manager -> state change -> *_CHANGED event -> UI/MPRIS2 update
```

#### Playlist Event Contract

- `PLAYLIST_CHANGED`: content mutations only (add, remove, move, replace, clear). No playback intent.
  - Includes `sync_mode` (`replace` or `append`) so MOC sync can avoid destructive clears on queue additions.
- `CURRENT_INDEX_CHANGED`: active index changed.
- `TRACK_CHANGED`: active track object changed.
- Content mutation order: `PLAYLIST_CHANGED -> CURRENT_INDEX_CHANGED -> TRACK_CHANGED`.
- Pure index change order: `CURRENT_INDEX_CHANGED -> TRACK_CHANGED`.

#### Playback Intent

Playback intent is separate from playlist content changes:
- UI publishes `ACTION_REPLACE_PLAYLIST` (content) then `ACTION_PLAY` (intent) as two events.
- `PlaybackController` queues `ACTION_PLAY` if MOC sync is in progress and executes it after sync completes.

#### Engineering Guidelines

- Keep state ownership in managers, not UI widgets.
- Prefer event publication over direct cross-component calls.
- Use type hints and structured logging.
- Keep write paths and command execution validated and explicit.
- `PLAYBACK_STATE_CHANGED` publishes on any state *change* (guard: `old != new`), so transitions from `SEEKING` to `PAUSED` are not swallowed.
- On stop: publish `PLAYBACK_STATE_CHANGED("stopped")` and reset progress *before* clearing the index, so UI subscribers see a consistent stopped state before track/index cleared events arrive.
- Playback enforces a strict single-backend invariant: local MOC and internal player are never allowed to run simultaneously.
- If both backends are detected as active, conflict resolution compares the latest per-backend action timestamps and stops the older backend immediately.
- Next/previous/auto-next index changes are committed only after playback start succeeds; failed starts roll back to the previous index.

#### MOC Integration Architecture

MOC is integrated through a thin command wrapper (`mocp`) focused on reliability:
- `play_file()` uses `mocp --playit <file>` as the primary track-selection path.
- Status is read through `--info` with short caching to reduce command overhead.
- `ensure_server()` uses a single validation path: probe `--info`, then start the server only when needed.
- Replace sync runs in a background thread (`sync_playlist_async`) with paced per-track appends.
- `sync_playlist_async` validates `mocp --clear` and every per-track `mocp --append`; on first failure it clears again and reports sync failure.
- Append-only sync (`append_playlist_async`) appends new queue tracks without `--clear`, so current playback is preserved.
- If MOC is unreachable at sync start, the sync worker performs one controlled server restart (`mocp --exit` then `--server`) and retries connectivity before failing.
- Autonext in MOC is disabled by default; track progression is controlled by `PlaybackController`.
- MOC backend ownership and playlist index are only updated after `play_file()` succeeds, so failed starts do not leave stale controller state behind.
- `ACTION_PLAY` during MOC sync can start immediately, and the latest sync-time play intent is replayed after sync to reassert the intended track if sync clobbered runtime state (single reassert path in `PlaybackController`).
- Track-finished detection for MOC auto-next uses a simple near-end position threshold (`position >= duration - 1.0`) with per-file de-duplication, keeping behavior deterministic while avoiding repeated next triggers.

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

This approach keeps behavior deterministic and aligns MOC playback with the app's event-driven state model.

#### UI State Management

UI and playback interaction are controlled by explicit state enums:
- `SeekState`: `IDLE`, `DRAGGING`, `SEEKING`
- `PlaybackState`: `STOPPED`, `LOADING`, `PAUSED`, `PLAYING`, `SEEKING`
- `OperationState`: `IDLE`, `SEEKING`, `SYNCING`

These states reduce race conditions and make transitions traceable during debugging.

### Development

#### Code Quality

The codebase follows these standards:
- Type hints for public and critical internal paths
- Structured logging (no print-based diagnostics)
- XDG-compliant configuration and cache handling
- Input/path validation for filesystem and command execution
- Explicit state models for playback and UI interaction
- Metadata fallback from filename prefixes (e.g. `01 - Title`) when tags are missing, including cached metadata loaded from disk
- Track ordering groups by parent directory first, then `track_number` within each directory (library view and folder-add/replace playlist operations)
- Folder add/replace track discovery in UI uses canonical `AUDIO_EXTENSIONS` from `core.music_library`

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
