# TalkFlow

**Real-time push-to-talk voice dictation with client-server architecture.**

Hold your hotkey, speak, release — transcribed text appears wherever your cursor is. TalkFlow uses a powerful GPU server running Faster-Whisper for fast, accurate transcription while lightweight clients run on any machine.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TALKFLOW ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐      │
│   │  Windows Client │     │   macOS Client  │     │  Linux Client   │      │
│   │   (TalkFlow)    │     │   (TalkFlow)    │     │   (TalkFlow)    │      │
│   │                 │     │                 │     │                 │      │
│   │  ┌───────────┐  │     │  ┌───────────┐  │     │  ┌───────────┐  │      │
│   │  │  Hotkey   │  │     │  │  Hotkey   │  │     │  │  Hotkey   │  │      │
│   │  │ Listener  │  │     │  │ Listener  │  │     │  │ Listener  │  │      │
│   │  └─────┬─────┘  │     │  └─────┬─────┘  │     │  └─────┬─────┘  │      │
│   │        │        │     │        │        │     │        │        │      │
│   │  ┌─────▼─────┐  │     │  ┌─────▼─────┐  │     │  ┌─────▼─────┐  │      │
│   │  │   Audio   │  │     │  │   Audio   │  │     │  │   Audio   │  │      │
│   │  │  Capture  │  │     │  │  Capture  │  │     │  │  Capture  │  │      │
│   │  └─────┬─────┘  │     │  └─────┬─────┘  │     │  └─────┬─────┘  │      │
│   │        │        │     │        │        │     │        │        │      │
│   └────────┼────────┘     └────────┼────────┘     └────────┼────────┘      │
│            │                       │                       │               │
│            └───────────────────────┼───────────────────────┘               │
│                                    │                                        │
│                          WebSocket │ (16kHz PCM audio)                      │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                         TRANSCRIPTION SERVER                         │  │
│   │                    (Docker / Linux with NVIDIA GPU)                  │  │
│   │  ┌─────────────────────────────────────────────────────────────┐    │  │
│   │  │                      FastAPI Server                          │    │  │
│   │  │                    (WebSocket endpoint)                      │    │  │
│   │  │                                                              │    │  │
│   │  │   ┌──────────────┐    ┌───────────────────────────────┐     │    │  │
│   │  │   │  WebSocket   │───▶│      Faster-Whisper           │     │    │  │
│   │  │   │   Handler    │    │   (large-v3 model, CUDA)      │     │    │  │
│   │  │   └──────────────┘    └───────────────────────────────┘     │    │  │
│   │  │                                                              │    │  │
│   │  └─────────────────────────────────────────────────────────────┘    │  │
│   │                                                                      │  │
│   │  Port: 9876                GPU: NVIDIA (CUDA 12.x)                  │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                          WebSocket │ (JSON: transcribed text)               │
│                                    ▼                                        │
│            ┌───────────────────────┼───────────────────────┐               │
│            │                       │                       │               │
│   ┌────────┼────────┐     ┌────────┼────────┐     ┌────────┼────────┐      │
│   │        ▼        │     │        ▼        │     │        ▼        │      │
│   │  ┌───────────┐  │     │  ┌───────────┐  │     │  ┌───────────┐  │      │
│   │  │ Keystroke │  │     │  │ Keystroke │  │     │  │ Keystroke │  │      │
│   │  │ Injector  │  │     │  │ Injector  │  │     │  │ Injector  │  │      │
│   │  └─────┬─────┘  │     │  └─────┬─────┘  │     │  └─────┬─────┘  │      │
│   │        │        │     │        │        │     │        │        │      │
│   │        ▼        │     │        ▼        │     │        ▼        │      │
│   │  [Text appears  │     │  [Text appears  │     │  [Text appears  │      │
│   │   at cursor]    │     │   at cursor]    │     │   at cursor]    │      │
│   │                 │     │                 │     │                 │      │
│   │  Windows Client │     │   macOS Client  │     │  Linux Client   │      │
│   └─────────────────┘     └─────────────────┘     └─────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User holds hotkey** → Hotkey listener detects press
2. **Audio capture starts** → Records 16kHz mono PCM from microphone
3. **User releases hotkey** → Audio capture stops
4. **Audio sent to server** → WebSocket streams PCM data
5. **Server transcribes** → Faster-Whisper processes audio (GPU-accelerated)
6. **Text returned** → Server sends JSON response with transcription
7. **Text injected** → Keystroke injector types text at cursor position

### Components

| Component | Location | Platform | Description |
|-----------|----------|----------|-------------|
| **Server** | `server/` | Linux + Docker | Faster-Whisper transcription (GPU) |
| **Client GUI** | `client/gui.py` | Windows/macOS/Linux | GUI with Settings + Dashboard tabs and system tray |
| **Client CLI** | `client/client.py` | All platforms | Command-line interface |
| **Clipboard delivery** | `client/clipboard_injector.py` | Windows/macOS/Linux | DeskFlow paste delivery (copy → sync → paste → restore) |
| **Installer Scripts** | `TalkFlow-Install.*` | Windows | Automated Python environment setup |
| **Build System** | `client/build_installer.py` | Windows | PyInstaller + Inno Setup |

---

## Multi-Machine Setup

### Prerequisites

#### Server Machine (Linux)
- **Docker** with NVIDIA Container Toolkit
- **NVIDIA GPU** with 8GB+ VRAM (RTX 3070 or better recommended)
- **CUDA 12.x** drivers installed
- Network accessible from client machines

#### Client Machines (Windows/macOS/Linux)
- **Python 3.10+** (or use the Windows installer)
- **Microphone** access
- Network connectivity to server

---

## Server Setup

### Option 1: Docker Compose (Recommended)

```bash
# On your Linux server with NVIDIA GPU
cd server

# Start the transcription server
docker compose up -d

# Check logs
docker compose logs -f

# Verify it's running
curl http://localhost:9876/health
```

### Option 2: Manual Docker

```bash
docker run -d \
  --name talkflow-server \
  --gpus all \
  -p 9876:9876 \
  -e WHISPER_MODEL=large-v3 \
  talkflow-server:latest
```

### Server Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `WHISPER_MODEL` | `large-v3` | Model size: tiny, base, small, medium, large-v3 |
| `DEVICE` | `cuda` | Device: cuda, cpu |
| `COMPUTE_TYPE` | `float16` | Precision: float16, int8, float32 |
| `PORT` | `9876` | Server port |

### Firewall Configuration

Allow incoming connections on port 9876:

```bash
# UFW (Ubuntu)
sudo ufw allow 9876/tcp

# firewalld (RHEL/Fedora)
sudo firewall-cmd --permanent --add-port=9876/tcp
sudo firewall-cmd --reload
```

---

## Client Setup

### Windows (Installer)

The easiest way to install on Windows:

1. **Download** `TalkFlow-Setup-1.0.0.exe` from releases
2. **Run** the installer
3. **Configure** server address in the GUI
4. **Start** using your hotkey!

Alternatively, use the automated setup scripts:

```powershell
# PowerShell (recommended)
.\TalkFlow-Install.ps1

# Or Command Prompt
TalkFlow-Install.bat
```

### Windows (Manual)

```powershell
# Install Python dependencies
cd client
pip install -r requirements.txt

# Run the GUI
python gui.py

# Or run the CLI
python client.py --server 192.168.1.100:9876
```

### macOS

```bash
# Install dependencies
cd client
pip3 install -r requirements.txt

# Grant microphone access in System Settings → Privacy & Security → Microphone

# Run the client
python3 gui.py
# or
python3 client.py --server 192.168.1.100:9876
```

### Linux

```bash
# Install system dependencies (Debian/Ubuntu)
sudo apt-get install python3-pip portaudio19-dev

# Install Python dependencies
cd client
pip3 install -r requirements.txt

# Run the client
python3 gui.py
```

---

## Configuration

### Client Configuration (`client/config.json`)

```json
{
  "backend": "groq",
  "server": "192.168.1.100:9876",
  "hotkey": "f9",
  "mic_device": null,
  "mic_device_name": "System Default",
  "delivery_mode": "local",
  "paste_sync_delay_ms": 250,
  "paste_restore_delay_ms": 700,
  "minimize_to_tray": true,
  "play_sounds": true,
  "auto_start_on_launch": false
}
```

`delivery_mode` controls where the transcript lands:

| Value | Behavior |
|-------|----------|
| `local` | Type the text at the cursor on the machine running TalkFlow (single-machine use). |
| `deskflow_paste` | Copy the text and paste it, so **DeskFlow** forwards it to whichever screen currently has the cursor. See [DeskFlow Integration](#deskflow-integration). |

### Hotkey Options

TalkFlow supports any key combination:

| Hotkey | Config Value | Notes |
|--------|--------------|-------|
| F9 | `f9` | Default, least likely to conflict |
| F10 | `f10` | Alternative function key |
| Ctrl+Shift+D | `ctrl+shift+d` | Modifier combo |
| Ctrl+Win | `ctrl+cmd` | `cmd` = Windows key |
| Ctrl+Alt+V | `ctrl+alt+v` | Voice-themed shortcut |

Use the **Record Hotkey** button in the GUI to capture any key combination.

---

## DeskFlow Integration

TalkFlow is designed to pair with [DeskFlow](https://github.com/deskflow/deskflow)
(the open-source software KVM, formerly Synergy). The goal: **one keyboard, one
mouse, one microphone** on your main machine, but dictation that lands on
*whichever screen your cursor is currently on*.

### How it works

Run TalkFlow on your **DeskFlow server** — the machine that physically has the
keyboard, mouse, and microphone (the "primary"). Set delivery mode to
**DeskFlow** (`deskflow_paste`). Then:

1. You hold the hotkey and speak. Audio is captured on the server and
   transcribed (Groq or your GPU server).
2. TalkFlow copies the transcript to the clipboard. DeskFlow **syncs the
   clipboard** to the screen your cursor is on.
3. TalkFlow sends a paste keystroke (Ctrl+V). DeskFlow's server-side keyboard
   hook **forwards injected keystrokes from the primary**, so the paste is
   delivered to the active remote screen — and the text appears there.

This is the same clipboard-paste technique used by tools like Wispr Flow,
combined with DeskFlow's built-in clipboard sync and input forwarding. No extra
agent is required on the client machines — DeskFlow does the routing.

```
   ┌─────────────────────────── DeskFlow PRIMARY (your PC) ──────────────────────────┐
   │  keyboard + mouse + mic                                                          │
   │  ┌──────────┐   hold hotkey    ┌───────────┐   transcript    ┌───────────────┐  │
   │  │  TalkFlow│ ───────────────▶ │ transcribe│ ──────────────▶ │ clipboard +   │  │
   │  │  (server)│                  │(Groq/GPU) │                 │ paste (Ctrl+V)│  │
   │  └──────────┘                  └───────────┘                 └──────┬────────┘  │
   └─────────────────────────────────────────────────────────────────────┼──────────┘
                                                                          │ DeskFlow
                                  clipboard sync + forwarded paste ───────┤ forwards to
                                                                          ▼ active screen
                          ┌─────────────────┐               ┌─────────────────┐
                          │   Mac Mini      │      or       │  Ubuntu box     │
                          │ (DeskFlow client)│              │(DeskFlow client)│
                          │  text pasted ✓  │               │  text pasted ✓  │
                          └─────────────────┘               └─────────────────┘
```

### Setup checklist

1. **Install + run TalkFlow on the DeskFlow primary** (the machine with the
   mic/keyboard/mouse). On the other screens you only need DeskFlow running as a
   client — no TalkFlow needed.
2. In TalkFlow's **Settings → Delivery**, choose **DeskFlow — paste to whichever
   screen has the cursor**.
3. Make sure DeskFlow's **clipboard sharing is enabled** (it is by default).
4. **Pick a bare function-key hotkey (F8 / F9).** Because the primary forwards
   all keystrokes to the active screen, a letter-based combo would "leak" to the
   remote machine while you hold it. A lone function key is harmless there.
5. **Cross-OS modifier mapping:** if your active screen runs a different OS than
   the primary (e.g. a Windows primary pasting to macOS), enable DeskFlow's
   Cmd↔Ctrl mapping for that screen so the forwarded Ctrl+V becomes Cmd+V.

### Tuning the paste timing

If pastes occasionally arrive empty or land before the clipboard has synced,
increase `paste_sync_delay_ms` (the wait between copy and paste). If your real
clipboard gets clobbered, increase `paste_restore_delay_ms`.

### Live dashboard

The desktop GUI has a **Dashboard** tab showing live status: service
running/stopped, active backend, delivery mode, hotkey, a manual server-health
check, and a feed of recent transcripts with their delivery result.

### Dictating onto another screen — the TalkFlow Agent (recommended)

There's a catch with the clipboard‑paste approach: **when DeskFlow gives another
screen the keyboard, it forwards your hotkey to that screen and swallows it on
the primary.** So a hotkey held while you're on a remote screen never reaches
the PC — nothing records. (If you only ever dictate while the cursor is on the
primary, clipboard‑paste mode is fine; for true "speak while on the other
screen" dictation you need the Agent.)

The Agent model catches the hotkey **on the screen that currently has the
keyboard**, then asks the PC (which has the mic) to record:

```
  Agent (Ubuntu / Mac)              Host (PC — has the mic + Whisper/Groq)
  --------------------              --------------------------------------
  hold F9      ── start ──▶          record the PC microphone
  release F9   ── stop  ──▶          stop, transcribe
               ◀── text ──           return the transcript
  type it here (local inject)
```

**On the PC (host):** in the GUI's **Delivery** section, tick **"Host remote
agents"** and Start — or run it headless:

```bash
cd client
python talkflow_host.py            # reads config.json for backend/key/mic; listens on :9877
```

Make sure your firewall allows inbound TCP on the host port (9877). Note the
PC's IP (LAN or Tailscale).

**On each remote screen (Ubuntu "AI5090", Mac Mini):** install the small client
and run the agent, pointing it at the PC:

```bash
# one-time: Python deps + (Linux) a typing tool
pip install websockets pynput
sudo apt install xdotool          # Linux/X11 only; macOS needs no extra tool

cd client
python talkflow_agent.py --host <PC_IP>:9877 --hotkey f9
```

Now, while controlling that screen, hold F9, speak, release — the text is typed
into the focused app **on that screen**. Because each agent injects locally,
there's no Ctrl‑vs‑Cmd problem and no clipboard juggling.

Notes:
- Use a LAN IP if the machines share a network, or a **Tailscale** IP to dictate
  across networks.
- On Linux the agent's global hotkey works best under **X11**; Wayland restricts
  global key capture.
- Only the agent that started a recording receives its transcript, so multiple
  screens never type over each other.

### Dictating onto a Wayland screen — the Stream Deck command trigger

On modern Wayland desktops (GNOME 46+, e.g. Ubuntu 25.10) DeskFlow injects
forwarded input through **libei / the RemoteDesktop portal**. By design those
events are delivered straight to the focused app and are **invisible to evdev,
pynput, and global shortcuts** — so the Agent above can't catch a hotkey on a
Wayland client, and neither can anything else. There is no DeskFlow setting to
change this; libei is the only Wayland injection path it has.

The fix is to trigger recording with something that is **not a keystroke at
all**. A **Stream Deck** (or any programmable macropad) fires a *command* over
USB‑HID through its own software, so it never enters the keyboard event stream
DeskFlow hooks — it works no matter which screen the cursor is on. Everything
runs on the PC; the transcript is delivered with the same clipboard‑paste path,
landing wherever your cursor is.

Because a Stream Deck button runs a command that returns immediately (it can't
*hold* a recording open across two presses), TalkFlow splits into a small
**daemon** that owns the recording state and a **trigger** the button fires.

**On the PC (with the mic), run the daemon once** (e.g. at login):

```bash
cd client
python streamdeck_daemon.py daemon --backend groq --groq-key gsk_xxx
# or self-hosted:  python streamdeck_daemon.py daemon --backend server --server <PC_IP>:9876
```

**Point a Stream Deck button** (System → Open, or a "Run command" plugin) at one
of these. A single toggle button is the simplest:

```bash
python streamdeck_daemon.py toggle      # press = start, press again = stop + transcribe
```

Prefer push‑to‑talk? Use a button's separate key‑down / key‑up actions:

```bash
python streamdeck_daemon.py start        # on key-down
python streamdeck_daemon.py stop         # on key-up
```

On Windows, use `pythonw.exe` for the trigger to avoid a console window flash.
The trigger needs only the Python standard library, so it works even on a
machine without the audio packages installed.

Notes:
- The daemon listens on `127.0.0.1:9878` (override with `--port`); the trigger
  connects there and exits in milliseconds.
- `python streamdeck_daemon.py status` / `ping` report daemon state — handy for a
  Stream Deck button that shows whether it's recording.
- Same clipboard‑paste delivery as DeskFlow mode, so the cross‑OS Cmd↔Ctrl
  mapping and `--sync-delay` / `--restore-delay` tuning notes above still apply.

---

## Building from Source

### Building the Windows Executable

```bash
cd client

# Install build dependencies
pip install pyinstaller pillow cairosvg

# Build the executable
python build_installer.py

# Output: dist/TalkFlow.exe
```

### Creating the Windows Installer

1. Install [Inno Setup 6.x](https://jrsoftware.org/isinfo.php)
2. Build the executable first (see above)
3. Open `installer.iss` in Inno Setup Compiler
4. Click **Build → Compile**
5. Output: `installer_output/TalkFlow-Setup-1.0.0.exe`

### Build Options

```bash
# Clean build (removes previous artifacts)
python build_installer.py --clean

# Debug build (with console window)
python build_installer.py --debug

# Skip icon conversion
python build_installer.py --skip-icon
```

---

## Troubleshooting

### Server Issues

**"CUDA out of memory"**
- Reduce model size: `WHISPER_MODEL=medium` or `small`
- Ensure no other GPU processes are running

**"Connection refused"**
- Check firewall settings
- Verify server is running: `docker ps`
- Test locally first: `curl http://localhost:9876/health`

### Client Issues

**"Cannot reach server"**
- Verify server IP and port
- Check network connectivity: `ping <server-ip>`
- Ensure firewall allows outbound connections

**"No audio captured"**
- Check microphone permissions
- Select correct microphone in settings
- Test microphone with system tools

**"Hotkey not detected"**
- Some hotkeys may conflict with system shortcuts
- Try a different hotkey (F9, F10, F8)
- Run as administrator on Windows if needed

**"Text not appearing"**
- Click in a text field before using hotkey
- Check that the target application accepts keyboard input
- On Windows, some apps need focus restoration

---

## Network Diagram (Multi-Machine)

```
                           ┌─────────────────────────────────┐
                           │         HOME NETWORK            │
                           │       192.168.1.0/24            │
                           └─────────────────────────────────┘
                                          │
          ┌───────────────────────────────┼───────────────────────────────┐
          │                               │                               │
          ▼                               ▼                               ▼
┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│   Gaming PC         │       │   GPU Server        │       │   Laptop            │
│   192.168.1.10      │       │   192.168.1.100     │       │   192.168.1.20      │
│                     │       │                     │       │                     │
│   TalkFlow Client   │◄─────►│   TalkFlow Server   │◄─────►│   TalkFlow Client   │
│   (Windows)         │  WS   │   (Docker/Linux)    │  WS   │   (Windows/macOS)   │
│                     │       │                     │       │                     │
│   config.json:      │       │   RTX 4090 GPU      │       │   config.json:      │
│   server:           │       │   Port 9876         │       │   server:           │
│   192.168.1.100:9876│       │                     │       │   192.168.1.100:9876│
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘
```

---

## Performance

| Model | VRAM | Speed (RTX 4090) | Accuracy |
|-------|------|------------------|----------|
| tiny | 1 GB | ~50x realtime | Lower |
| base | 1 GB | ~40x realtime | Basic |
| small | 2 GB | ~25x realtime | Good |
| medium | 5 GB | ~10x realtime | Better |
| large-v3 | 10 GB | ~5x realtime | Best |

For real-time dictation, `large-v3` on a modern GPU provides the best balance of speed and accuracy.

---

## License

Private — AI Implemented © 2026
