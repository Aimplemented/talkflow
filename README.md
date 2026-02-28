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
| **Client GUI** | `client/gui.py` | Windows/macOS/Linux | Full-featured GUI with system tray |
| **Client CLI** | `client/client.py` | All platforms | Command-line interface |
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
  "server": "192.168.1.100:9876",
  "hotkey": "f9",
  "mic_device": null,
  "mic_device_name": "System Default",
  "minimize_to_tray": true,
  "play_sounds": true,
  "auto_start_on_launch": false
}
```

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
