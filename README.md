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

### Installing Dependencies

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
  media-plugins/gst-plugins-bluez \
  media-plugins/gst-plugins-wavpack

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

# WavPack support (lossless audio format)
emerge -av media-sound/wavpack
```

> 🧪 **Challenge:** After installing, try `gst-inspect-1.0 | wc -l` to see how many GStreamer plugins you have. The more plugins, the more formats you can play!

### 🧪 Bonus Challenge: Kernel Configuration

**Difficulty:** ⭐⭐⭐⭐⭐ (Advanced!)

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

### 🔧 Enable Bluetooth Service

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
| 🎶 **Lossless Audio** | FLAC, WAV, AIFF, ALAC, APE, WavPack | `gst-plugins-base` (WAV, AIFF), `gst-plugins-flac`, `gst-plugins-wavpack` |
| 🎬 **Video** | MP4, MKV, WebM, AVI, MOV | `gst-plugins-bad`, `openh264` |

---

## 🚀 Quick Start (Get It Running!)

### Step 1: Clone and Enter the Project

```bash
git clone <your-repo-url>
cd MusicPlayer
```

### Step 2: Set Up Your Environment

```bash
# Create a virtual environment (keeps things clean!)
python -m venv venv
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt
```

### Step 3: Run It!

```bash
python main.py
```

You should see a window with your music library, playlist, and Bluetooth controls! 🎉

### Basic Controls

- **Playback controls** (bottom bar):
  - **Play / Pause / Stop / Previous / Next**: control the current playlist.
    - **Play button**: If a track is selected in the playlist, starts playing from the selected track. If no track is selected, plays the current track. If paused, resumes from the paused position instead of restarting.
    - **Pause button**: Pauses playback at the current position. Pressing Play again resumes from the paused position.
  - **Shuffle**: toggle to play the current playlist in **random order**; the *Next* button and automatic track advance will pick a random track instead of the next in sequence.
  - **Seek & Volume**: larger, touch-friendly sliders for scrubbing through the track and adjusting volume.
    - **Progress slider**: Click or drag to seek to any position in the track. The slider can reach the full end of the song (100% position). Time labels update in real-time during seeking for immediate feedback.
    - **Time display**: Shows current position (left), total duration (right), and time remaining (below duration) for easy tracking of playback progress.
- **Playlist context menu**: Right-click (or long-press on touch) a track in the playlist to access options like Play, Remove, Move Up/Down. The menu properly captures clicks and applies actions to the selected track.

### Desktop Integration (MPRIS2)

The player supports **MPRIS2** (Media Player Remote Interfacing Specification) for seamless desktop integration:

- **Media keys support**: Use your keyboard's media keys (Play/Pause, Next, Previous) to control playback
- **Desktop notifications**: Some desktop environments show playback information in notifications
- **System integration**: The player appears in system media controls and can be controlled remotely via D-Bus
- **Metadata sync**: Track information (title, artist, album, artwork) is automatically synchronized with the desktop environment
- **Position tracking**: Playback position is continuously updated for accurate progress display

### MOC Integration (Optional)

If `mocp` is installed (Gentoo package `media-sound/moc`), the app integrates with MOC (Music On Console):

**For proper MOC integration with full format support, configure the following USE flags:**

```bash
# MOC package with format support
media-sound/moc aac alsa ffmpeg libsamplerate oss wavpack

# FFmpeg compatibility layer
media-video/ffmpeg-compat openh264

# FFmpeg with codec support
media-video/ffmpeg chromium codec2 jack lame libdrm openal opencl opengl opus oss snappy sndio vaapi vdpau webp x264 x265
```

You can set these in `/etc/portage/package.use` or use `emerge` with USE flags:
```bash
USE="aac alsa ffmpeg libsamplerate oss wavpack" emerge -av media-sound/moc
USE="openh264" emerge -av media-video/ffmpeg-compat
USE="chromium codec2 jack lame libdrm openal opencl opengl opus oss snappy sndio vaapi vdpau webp x264 x265" emerge -av media-video/ffmpeg
```

**Features:**
- **Playlist synchronization**: The GTK playlist mirrors MOC's playlist from `~/.moc/playlist.m3u`
- **Bidirectional sync**: Changes in either the GTK app or MOC are synchronized
- **Player controls**: Playback controls (play, pause, volume, shuffle) control MOC when available
- **File type handling**: MOC handles audio files; video containers (MP4, MKV, WebM, etc.) use the internal GStreamer player
- **Automatic server management**: MOC server is started automatically and shut down when the app closes

### 🎨 Automatic Metadata Fetching

The player automatically searches and downloads missing metadata (especially album art) from online sources:

- **Smart detection**: When a track is missing cover art or metadata, the player automatically searches online
- **Multiple sources**: Uses MusicBrainz, Cover Art Archive, and iTunes Search API for maximum coverage
- **Beautiful placeholder**: When no cover art is available, displays a modern gradient placeholder with a music icon instead of a gray box
- **Background fetching**: Metadata is fetched asynchronously so the UI remains responsive
- **Intelligent caching**: Downloaded metadata and album art are cached locally to avoid repeated requests
- **Rate limiting**: Respects API rate limits (e.g., MusicBrainz's 1 request/second limit)

**How it works:**
1. When a track is loaded, the player checks if album art exists
2. If missing, it searches online using the track's title, artist, and album information
3. The best match is selected based on title/artist similarity and duration matching
4. Album art is downloaded and cached in `~/.cache/musicplayer/art/`
5. The UI updates automatically when metadata is found

**Sources used:**
- **MusicBrainz**: Open music encyclopedia with comprehensive metadata
- **Cover Art Archive**: High-quality album art (part of MusicBrainz)
- **iTunes Search API**: Fast fallback for popular tracks

---

<details>
<summary><h2>📚 Technical Documentation</h2></summary>

---

## 🏗️ Project Structure Explained

```
MusicPlayer/
│
├── 🚀 main.py                    # The starting point - run this!
│
├── 📦 core/                      # The "brain" - logic without UI
│   ├── audio_player.py           # GStreamer playback
│   ├── bluetooth_manager.py      # Device discovery & connection
│   ├── bluetooth_sink.py         # A2DP sink mode (speaker mode!)
│   ├── metadata.py               # Reading ID3 tags, album art
│   ├── metadata_fetcher.py      # Automatic online metadata fetching
│   ├── moc_controller.py         # MOC (Music On Console) integration
│   ├── mpris2.py                 # MPRIS2 desktop integration
│   ├── music_library.py          # Scanning folders for music
│   └── playlist_manager.py       # Queue management
│
├── 🎨 ui/                        # The "face" - what users see
│   ├── main_window.py            # Main application window
│   ├── dock_manager.py           # Detachable panels
│   └── components/               # Reusable UI pieces
│       ├── bluetooth_panel.py    # Bluetooth controls
│       ├── library_browser.py    # File browser
│       ├── metadata_panel.py     # Now playing info & album art
│       ├── player_controls.py    # Play/pause/seek
│       └── playlist_view.py      # Queue display
│
├── 📋 requirements.txt           # Python packages needed
└── 📄 README.md                  # You're reading it!
```

### The MVC Pattern (Sort Of)

We follow a pattern where:
- **Model** = `core/` (data and logic)
- **View** = `ui/` (what users see)
- **Controller** = callbacks connecting them

This separation makes code easier to understand and modify!

---

## 🔧 How the Bluetooth Speaker Mode Works

This is the coolest IoT feature! Let's trace through what happens:

### 1️⃣ Enable Speaker Mode

At startup, all Bluetooth functionality is **inactive and cleared** in the UI.  
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

### 2️⃣ Phone Connects

When your phone pairs and connects (no manual Scan/Connect needed from the app):

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

### 3️⃣ Audio Flows

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
emerge -av media-plugins/gst-plugins-wavpack   # WavPack audio
emerge -av media-plugins/gst-plugins-openh264  # H.264 video
```

### "MOC error: Failed to add track to MOC playlist!"

This error can occur during app initialization or when syncing playlists:

```bash
# Check if MOC server is running
mocp --info

# If not running, start it manually
mocp --server

# Check if the track file exists
ls -l /path/to/your/track.mp3

# If files were moved, reload the playlist
# The app will automatically skip invalid tracks when syncing to MOC
```

### "Songs don't automatically advance to the next track!"

If playback stops when a song finishes instead of automatically playing the next song, ensure autonext is enabled. The app should automatically advance to the next track when a song finishes. When shuffle is enabled, tracks play in random order.

### "Panel layout is messed up!"

```bash
# Reset to default layout
rm ~/.config/musicplayer/layout.json
```

### "Missing icons (placeholders shown)!"

```bash
# Install Adwaita icon theme
emerge -av x11-themes/adwaita-icon-theme

# Set icon theme (add to ~/.config/gtk-4.0/settings.ini)
echo "[Settings]" > ~/.config/gtk-4.0/settings.ini
echo "gtk-icon-theme-name=Adwaita" >> ~/.config/gtk-4.0/settings.ini
```

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

</details>

---

<details>
<summary><h2>🧠 Learning Resources & Challenges</h2></summary>

## 🧠 Understanding IoT Through This Project

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

---

## 🔵 Deep Dive: Bluetooth (The Wireless Magic)

Bluetooth is the wireless protocol that lets devices talk to each other within short range (~10 meters). Let's see how it works in our code!

### How Devices Find Each Other

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
        print(f"Error starting discovery: {e}")
        return False
```

**What's happening:**
1. We ask the Bluetooth adapter to start scanning
2. The adapter broadcasts "Hey! Anyone out there?"
3. Nearby devices respond with their names and addresses
4. Our code collects these responses

### The Bluetooth Stack

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

### 🧪 Challenge #1: Bluetooth Explorer

**Difficulty:** ⭐⭐☆☆☆

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

**🎯 Your Mission:** 
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

---

## 🔌 Deep Dive: D-Bus (The System's Nervous System)

D-Bus is like the nervous system of your Linux computer. Different programs send messages to each other through D-Bus, just like neurons sending signals!

### Why D-Bus?

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

### Signals: Events You Can Listen To!

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

### 🧪 Challenge #2: D-Bus Detective

**Difficulty:** ⭐⭐⭐☆☆

Use the `dbus-monitor` command to spy on D-Bus messages:

```bash
# Watch all Bluetooth-related messages
dbus-monitor --system "sender='org.bluez'"
```

Now try:
1. Turn Bluetooth on/off in your settings
2. Pair a device
3. Connect/disconnect a device

**🎯 Your Mission:**
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

---

## 🎼 Deep Dive: GStreamer (The Audio Pipeline)

GStreamer is like a factory assembly line, but for media! Audio goes in one end, gets processed through different stages, and comes out the speakers.

### The Pipeline Concept

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Source  │ →  │ Decoder  │ →  │  Volume  │ →  │   Sink   │
│ (file)   │    │ (MP3→PCM)│    │ (adjust) │    │(speakers)│
└──────────┘    └──────────┘    └──────────┘    └──────────┘
    📁             🔧              🔊              🔈
```

Each box is called an **element**, and they connect via **pads**.

### Our Audio Player (Simplified)

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

### 🧪 Challenge #3: Build Your Own Pipeline

**Difficulty:** ⭐⭐⭐⭐☆

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

**🎯 Your Mission:**
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

To make it interactive (adjust volume while playing):
```bash
gst-launch-1.0 audiotestsrc freq=440 ! audioconvert ! volume volume=0.5 ! autoaudiosink
# Then in another terminal:
gst-launch-1.0 -e audiotestsrc freq=440 ! audioconvert ! volume volume=0.3 ! autoaudiosink
```

For a more complex example with multiple effects:
```bash
gst-launch-1.0 audiotestsrc wave=sine freq=440 ! audioconvert ! volume volume=0.7 ! autoaudiosink
```

</details>

> **📚 Learn More:** [GStreamer Application Development Manual](https://gstreamer.freedesktop.org/documentation/application-development/index.html)

---

## 🖼️ Deep Dive: GTK (Making It Look Good)

GTK is the toolkit we use to create the graphical interface. Buttons, windows, lists — all GTK!

### The Widget Tree

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

### Creating a Button

```python
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# Create a button
button = Gtk.Button(label="Click Me!")

# Connect a function to the click event
button.connect("clicked", lambda btn: print("Button was clicked!"))
```

### 🧪 Challenge #4: Add a Feature

**Difficulty:** ⭐⭐⭐⭐⭐

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

**Alternative: Using GLib.idle_add for thread safety:**
```python
from gi.repository import GLib

def _send_notification_safe(self, title: str, artist: str):
    GLib.idle_add(self._send_now_playing_notification, title, artist)
```

</details>

> **📚 Learn More:** [GTK4 Python Tutorial](https://pygobject.readthedocs.io/en/latest/)

---

## 💡 IoT Project Ideas (What's Next?)

Now that you understand the basics, here are some projects to try:

### Beginner Projects

1. **🌡️ Temperature Display**
   - Connect a Bluetooth temperature sensor
   - Show readings in a GTK window
   - Log data to a file

2. **💡 Smart Light Controller**
   - Control Bluetooth LED bulbs
   - Create color presets
   - Schedule on/off times

### Intermediate Projects

3. **🎮 Bluetooth Game Controller**
   - Read gamepad inputs via Bluetooth
   - Map buttons to keyboard shortcuts
   - Create a GUI for configuration

4. **🏠 Home Automation Hub**
   - Discover and manage multiple BLE devices
   - Create "scenes" (e.g., "Movie Mode" dims lights, starts music)

### Advanced Projects

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

### 🐧 Gentoo Linux (Your Operating System!)

- 📖 [**Gentoo Handbook (Full Installation)**](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation) - The complete guide to building your system from scratch. We **strongly recommend** the full manual approach — you'll understand Linux at a level most people never reach!
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

</details>

---

<div align="center">

**Happy hacking! 🎉**

*Remember: Every expert was once a beginner.* 

*The only way to learn is to build things!*

</div>
